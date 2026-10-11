# plugprint — AI-powered energy monitor (NILM)

A small device that sits between a wall socket and a power strip, measures the electricity flowing through it, and uses machine learning to work out **which appliances are on** (kettle, fan, laptop charger…) and how much each one costs to run in AED, all from a **single measurement point**. The technique is called *non-intrusive load monitoring* (NILM).

> 🚧 Work in progress. Target completion: December 2026.

## How it works

1. **Sense:** a clip-on current transformer (SCT-013) measures current and a ZMPT101B module measures mains voltage (230 V / 50 Hz).
2. **Sample:** an ESP32 reads both waveforms 4,000 times per second each (80 samples per mains cycle).
3. **Compute:** Vrms, Irms, real power `P = mean(v·i)`, apparent power, power factor, and harmonic content.
4. **Stream:** results go over WiFi to a live dashboard (watts, energy, cost in AED).
5. **Identify:** an ML model recognises each appliance's electrical "fingerprint" (power level, power factor, harmonics, start-up shape).

## Repository layout

| Folder | What's inside |
|---|---|
| `firmware/plugprint/` | ESP32 Arduino sketch |
| `Simulations/` | Falstad circuit simulation of the sensor front end |
| `ml/` *(coming)* | Feature extraction + appliance classifier |
| `dashboard/` | Live dashboard (Streamlit) + a fake plug for testing — see its README |

## Building the firmware

1. Install the [Arduino IDE 2](https://www.arduino.cc/en/software) and the **esp32 by Espressif Systems** board package.
2. In `firmware/plugprint/`, copy `secrets_example.h` → `secrets.h` and fill in your WiFi details (it is git-ignored).
3. Open `firmware/plugprint/plugprint.ino`, select **ESP32 Dev Module**, and click **Verify** / **Upload**.
4. Serial Monitor at **115200 baud**.

With `SIMULATE_SENSORS 1` (default) the board generates a synthetic 230 V / 1000 W signal, so the expected readout is ≈ 230 V, 4.35 A, 1000 W, PF 1.00.

## Safety

Mains voltage can kill. All mains-side wiring in this project is assembled in a university lab, checked by a technician and sealed in an enclosure. The ESP32 side is isolated from the mains by the current transformer and the voltage-sensor transformer.
