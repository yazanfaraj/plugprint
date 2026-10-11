"""
fake_plug.py — pretends to be the plugprint ESP32 until the real board arrives.

It sends exactly the same kind of message the real firmware will send: one
small JSON text every 200 ms (one "snapshot", D22), shouted to the whole
network on UDP port 4210 (D23).

To make the dashboard interesting, it imagines a power strip with a few
appliances that switch on and off at random, like a real home.

Run it:   py fake_plug.py          (Ctrl+C to stop)
"""
import json
import math
import random
import socket
import time

from config import UDP_PORT

SNAPSHOT_SECONDS = 0.2  # the real firmware sends one reading every 200 ms (D22)

# ---------------------------------------------------------------------------
# The imaginary power strip.
#   watts   = how much real power it uses when on
#   pf      = its power factor (1.0 = kettle-like heater, lower = motors/chargers)
#   on_for  = (shortest, longest) time it stays on, in seconds
#   chance  = chance per second that it switches on while it's off
# Numbers are typical values, not measurements.
# ---------------------------------------------------------------------------
APPLIANCES = {
    "kettle":         {"watts": 2000, "pf": 1.00, "on_for": (60, 150),  "chance": 0.004},
    "fan":            {"watts": 55,   "pf": 0.90, "on_for": (120, 600), "chance": 0.010},
    "lamp":           {"watts": 60,   "pf": 1.00, "on_for": (180, 900), "chance": 0.008},
    "laptop charger": {"watts": 65,   "pf": 0.55, "on_for": (300, 1200), "chance": 0.010},
    "iron":           {"watts": 1200, "pf": 1.00, "on_for": (60, 240),  "chance": 0.003},
}

STANDBY_WATTS = 3  # little things that are always on (an LED, a phone dock...)


class FakeStrip:
    def __init__(self):
        # For each appliance: the time it should switch off (0 = it's off)
        self.off_at = {name: 0.0 for name in APPLIANCES}

    def update(self, now, dt):
        """Randomly switch appliances on/off. Prints whenever something changes."""
        for name, a in APPLIANCES.items():
            if self.off_at[name] and now >= self.off_at[name]:
                self.off_at[name] = 0.0
                print(f"  [fake] {name} switched OFF")
            elif not self.off_at[name] and random.random() < a["chance"] * dt:
                # A UAE power strip has a 13 A fuse (~3,000 W). Like a sensible
                # person, the fake home never runs the kettle AND the iron together.
                if self.total_watts() + a["watts"] > 3000:
                    continue
                self.off_at[name] = now + random.uniform(*a["on_for"])
                print(f"  [fake] {name} switched ON")

    def total_watts(self):
        return sum(a["watts"] for n, a in APPLIANCES.items() if self.off_at[n])

    def reading(self, t_ms):
        """Combine everything that's on into one reading, like the clamp would see."""
        # Each appliance has "useful" power P and "sloshing" power Q.
        # The clamp sees them all added together (currents add on one wire).
        P, Q = STANDBY_WATTS, 0.0
        for name, a in APPLIANCES.items():
            if self.off_at[name]:
                P += a["watts"]
                Q += a["watts"] * math.tan(math.acos(a["pf"]))
        noise = random.uniform(0.995, 1.005)  # a little measurement wobble
        p, q = P * noise, Q * noise
        S = math.hypot(p, q)  # apparent power: how hard the wires work (D18)

        # Mains voltage wanders a little around 230 V and sags slightly under
        # heavy load (more current -> more voltage lost in the house wiring).
        v = 230 + random.gauss(0, 0.6) - S / 1000
        i = S / v
        pf = p / S if S > 0.5 else 0.0

        return {
            "t_ms": t_ms,                       # time since the plug started
            "v": round(v, 1),                   # Vrms, volts
            "i": round(i, 3),                   # Irms, amps
            "p": round(p, 1),                   # real power, watts
            "s": round(S, 1),                   # apparent power, VA
            "pf": round(pf, 2),                 # power factor
            "rate": 4000.0,                     # sampling rate the plug achieved (D17)
            "late": random.randint(2, 15),      # worst sample lateness, microseconds
        }


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP = no handshake, just send
    strip = FakeStrip()
    start = time.monotonic()

    print(f"Fake plug running: sending a reading every {SNAPSHOT_SECONDS*1000:.0f} ms "
          f"to UDP port {UDP_PORT}. Ctrl+C to stop.")
    next_tick = start
    sent = 0
    while True:
        now = time.monotonic()
        strip.update(now, SNAPSHOT_SECONDS)
        msg = strip.reading(int((now - start) * 1000))
        # The fake plug lives on the same laptop as the receiver, so it sends to
        # 127.0.0.1 ("this computer"). The real plug will broadcast to the whole
        # network instead — the receiver doesn't care which, it just listens.
        sock.sendto(json.dumps(msg).encode(), ("127.0.0.1", UDP_PORT))

        sent += 1
        if sent % 25 == 0:  # every 5 seconds
            print(f"sent {sent:6d} readings | now: {msg['p']:7.1f} W, PF {msg['pf']:.2f}")

        next_tick += SNAPSHOT_SECONDS
        time.sleep(max(0.0, next_tick - time.monotonic()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFake plug stopped.")
