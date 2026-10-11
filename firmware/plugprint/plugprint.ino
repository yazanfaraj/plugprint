/*
 * plugprint — firmware skeleton (ESP32)
 * ------------------------------------------------------------
 * What this does, in order, forever:
 *   1. Stays connected to whichever known WiFi is in range (Dubai or Abu Dhabi)  -> D4
 *   2. Takes a "snapshot": 800 voltage + 800 current samples at a steady 4 kHz,
 *      i.e. exactly 10 mains cycles (200 ms)                                      -> D17
 *   3. Turns the snapshot into Vrms, Irms, real power, apparent power, PF          -> D18
 *   4. Prints the result plus a timing report to the Serial Monitor
 *   5. Sends the result over WiFi to the laptop dashboard (UDP broadcast)      -> D23
 *
 * No sensors yet? Leave SIMULATE_SENSORS at 1: the board invents a clean 230 V
 * mains wave and a 1000 W kettle-like current, so you can check the maths.
 * Expected output with simulation on: V ~ 230 V, I ~ 4.35 A, P ~ 1000 W, PF ~ 1.00
 *
 * Calibration numbers below are THEORETICAL STARTING GUESSES from the circuit
 * design. Real values get measured in Weeks 2-3 (multimeter + known loads).
 */

#include <WiFi.h>
#include <WiFiMulti.h>
#include <WiFiUdp.h>
#include <math.h>
#include "secrets.h"  // your WiFi names/passwords (never uploaded to GitHub)

// ============================================================
// Settings
// ============================================================
#define SIMULATE_SENSORS 1  // 1 = fake waves (no sensors needed), 0 = read real pins

const int PIN_VOLTAGE = 34;  // ZMPT101B via 10k/22k divider (D6, D7)
const int PIN_CURRENT = 35;  // SCT-013 via 82 ohm burden + bias (D6, D10)

const uint32_t SAMPLE_RATE_HZ    = 4000;                       // per channel (D17)
const uint32_t SAMPLE_PERIOD_US  = 1000000UL / SAMPLE_RATE_HZ; // 250 us between samples
const int      SAMPLES_PER_CYCLE = 80;                         // 4000 / 50 Hz
const int      CYCLES_PER_BLOCK  = 10;                         // 10 cycles = 200 ms snapshot
const int      BLOCK_SIZE        = SAMPLES_PER_CYCLE * CYCLES_PER_BLOCK;  // 800

// Calibration: how many real volts / amps one ADC step is worth.
// Current: 0.041 V per amp across the burden (D10); one ADC step ~ 3.3 V / 4095.
//   -> 1 A = 0.041 / 3.3 * 4095 ~ 50.9 steps  -> 1 step ~ 0.0197 A
// Voltage: assumes the ZMPT trimpot is set so 325 V peak mains -> 1.0 V peak at the
//   module, x0.69 divider -> 0.69 V peak ~ 853 steps -> 1 step ~ 0.381 V
float V_CAL = 0.381f;   // volts per ADC step  (placeholder until calibrated)
float I_CAL = 0.0197f;  // amps per ADC step   (placeholder until calibrated)

const uint32_t WIFI_RETRY_MS = 10000;  // how often to retry if WiFi drops
const uint16_t UDP_PORT      = 4210;   // the laptop's dashboard/receiver.py listens here (D23)

// ============================================================
// Globals
// ============================================================
WiFiMulti wifiMulti;
WiFiUDP   udp;
uint16_t  vRaw[BLOCK_SIZE];  // raw ADC readings, 0..4095
uint16_t  iRaw[BLOCK_SIZE];
uint32_t  lastWifiAttempt = 0;

struct Measurement {
  float vrms, irms, realPower, apparentPower, powerFactor;
  float vBias, iBias;          // measured mid-points in ADC steps (expect ~2130 and ~2048)
  float actualRateHz;          // how fast we really sampled
  uint32_t worstLateUs;        // the most any sample was late
};

// ============================================================
// Reading the sensors (real or simulated)
// ============================================================
#if SIMULATE_SENSORS
uint32_t simSampleIndex = 0;  // keeps the fake wave continuous between snapshots

void readSamplePair(uint16_t &v, uint16_t &i) {
  const float t = simSampleIndex++ / (float)SAMPLE_RATE_HZ;  // seconds
  const float w = 2.0f * PI * 50.0f * t;                      // 50 Hz (D2)
  // Voltage: 230 V RMS = 325 V peak, sitting on the ~1.72 V divider mid-point (D7)
  const float vSteps = 2135.0f + (325.0f / V_CAL) * sinf(w);
  // Current: 1000 W resistive load -> 4.35 A RMS = 6.15 A peak, in step with V,
  // sitting on the 1.65 V bias (D8)
  const float iSteps = 2048.0f + (6.15f / I_CAL) * sinf(w);
  // A little random noise, like a real ADC (about +/-3 steps)
  v = (uint16_t)(vSteps + random(-3, 4));
  i = (uint16_t)(iSteps + random(-3, 4));
}
#else
void readSamplePair(uint16_t &v, uint16_t &i) {
  v = analogRead(PIN_VOLTAGE);
  i = analogRead(PIN_CURRENT);  // read right after V: tiny time offset, fixed in calibration
}
#endif

// ============================================================
// Step 2: take one snapshot at a steady 4 kHz
// ============================================================
// Like a metronome: every 250 us we take one V and one I reading. We note how
// late each "tick" was, so we can prove the timing holds with WiFi running.
void captureBlock(uint32_t &worstLateUs, float &actualRateHz) {
  worstLateUs = 0;
  uint32_t next = micros();
  uint32_t firstSampleUs = 0, lastSampleUs = 0;

  for (int n = 0; n < BLOCK_SIZE; n++) {
    while ((int32_t)(micros() - next) < 0) { /* wait for the next tick */ }
    const uint32_t now  = micros();
    const uint32_t late = now - next;
    if (late > worstLateUs) worstLateUs = late;
    if (n == 0) firstSampleUs = now;
    lastSampleUs = now;

    readSamplePair(vRaw[n], iRaw[n]);
    next += SAMPLE_PERIOD_US;
  }

  // 800 samples have 799 gaps between them (like fence posts vs. gaps)
  const uint32_t elapsed = lastSampleUs - firstSampleUs;  // ~199,750 us if all went well
  actualRateHz = (BLOCK_SIZE - 1) * 1e6f / (float)elapsed;
}

// ============================================================
// Step 3: turn the snapshot into power numbers (D18)
// ============================================================
Measurement computePower(uint32_t worstLateUs, float actualRateHz) {
  Measurement m;

  // (a) Find each wave's middle line (the DC bias) = the average reading.
  //     Because the snapshot is exactly 10 whole cycles, the AC part averages to 0.
  double vSum = 0, iSum = 0;
  for (int n = 0; n < BLOCK_SIZE; n++) { vSum += vRaw[n]; iSum += iRaw[n]; }
  m.vBias = vSum / BLOCK_SIZE;
  m.iBias = iSum / BLOCK_SIZE;

  // (b) Subtract the bias, convert to real volts/amps, accumulate.
  double vSq = 0, iSq = 0, vi = 0;
  for (int n = 0; n < BLOCK_SIZE; n++) {
    const double v = (vRaw[n] - m.vBias) * V_CAL;
    const double i = (iRaw[n] - m.iBias) * I_CAL;
    vSq += v * v;
    iSq += i * i;
    vi  += v * i;
  }

  // (c) The D18 formulas
  m.vrms          = sqrt(vSq / BLOCK_SIZE);   // V_rms = sqrt(mean(v^2))
  m.irms          = sqrt(iSq / BLOCK_SIZE);   // I_rms = sqrt(mean(i^2))
  m.realPower     = vi / BLOCK_SIZE;          // P = mean(v*i)
  m.apparentPower = m.vrms * m.irms;          // S = Vrms * Irms
  m.powerFactor   = (m.apparentPower > 0.5f) ? m.realPower / m.apparentPower : 0.0f;

  m.worstLateUs  = worstLateUs;
  m.actualRateHz = actualRateHz;
  return m;
}

// ============================================================
// Step 1: WiFi (D4) — remembers both networks, joins whichever is in range
// ============================================================
void setupWifi() {
  WiFi.mode(WIFI_STA);
  wifiMulti.addAP(WIFI_SSID_DUBAI,     WIFI_PASS_DUBAI);
  wifiMulti.addAP(WIFI_SSID_ABU_DHABI, WIFI_PASS_ABU_DHABI);

  Serial.println("Connecting to WiFi...");
  if (wifiMulti.run(10000) == WL_CONNECTED) {
    Serial.printf("Connected to \"%s\", IP %s\n",
                  WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
  } else {
    Serial.println("No known WiFi found. Measuring anyway; will retry every 10 s.");
  }
  lastWifiAttempt = millis();
}

// Only retries BETWEEN snapshots, so it never disturbs the sampling rhythm.
void maintainWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiAttempt < WIFI_RETRY_MS) return;
  lastWifiAttempt = millis();
  if (wifiMulti.run(5000) == WL_CONNECTED) {
    Serial.printf("Reconnected to \"%s\", IP %s\n",
                  WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
  }
}

// ============================================================
// Step 4: print
// ============================================================
void printMeasurement(const Measurement &m) {
  Serial.printf("V=%6.1f V  I=%6.3f A  P=%7.1f W  S=%7.1f VA  PF=%5.2f",
                m.vrms, m.irms, m.realPower, m.apparentPower, m.powerFactor);
  Serial.printf("  | bias V=%4.0f I=%4.0f", m.vBias, m.iBias);
  Serial.printf("  | rate=%6.1f Hz, worst late=%3lu us",
                m.actualRateHz, (unsigned long)m.worstLateUs);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("  | WiFi: %s\n", WiFi.SSID().c_str());
  } else {
    Serial.println("  | WiFi: --");
  }
}

// ============================================================
// Step 5: send to the laptop (D23)
// ============================================================
// "Shouts" the reading to every device on the home network (UDP broadcast), so
// the ESP32 never needs to know the laptop's address: works in both homes.
// The message format matches dashboard/fake_plug.py exactly.
// Takes about a millisecond and happens between snapshots, so sampling is undisturbed.
void sendMeasurement(const Measurement &m) {
  if (WiFi.status() != WL_CONNECTED) return;
  char msg[192];
  snprintf(msg, sizeof(msg),
           "{\"t_ms\":%lu,\"v\":%.1f,\"i\":%.3f,\"p\":%.1f,\"s\":%.1f,"
           "\"pf\":%.2f,\"rate\":%.1f,\"late\":%lu}",
           (unsigned long)millis(), m.vrms, m.irms, m.realPower, m.apparentPower,
           m.powerFactor, m.actualRateHz, (unsigned long)m.worstLateUs);
  udp.beginPacket(WiFi.broadcastIP(), UDP_PORT);
  udp.print(msg);
  udp.endPacket();
}

// ============================================================
// Arduino entry points
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== plugprint firmware skeleton ===");
  Serial.println(SIMULATE_SENSORS ? "Mode: SIMULATED sensors" : "Mode: REAL sensors");

  analogReadResolution(12);  // readings 0..4095
  // (default ADC attenuation already covers ~0-3.1 V, which fits our 0.9-2.41 V signals)

  setupWifi();
}

void loop() {
  uint32_t worstLateUs;
  float actualRateHz;
  captureBlock(worstLateUs, actualRateHz);                    // ~200 ms
  Measurement m = computePower(worstLateUs, actualRateHz);    // a few ms
  printMeasurement(m);
  sendMeasurement(m);                                         // ~1 ms
  maintainWifi();
}
