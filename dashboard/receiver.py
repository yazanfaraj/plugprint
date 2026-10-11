"""
receiver.py — the laptop's "mailbox" for plugprint readings.

Listens on UDP port 4210 for messages from the plug (real or fake), stamps each
one with the laptop's clock (the ESP32 has no real-time clock), and appends it
to today's CSV file in data/live/. The dashboard reads that file.

Why a separate program? It keeps recording even when the dashboard is closed,
and the CSV files it builds up become training data for the ML part later.

Run it:   py receiver.py          (Ctrl+C to stop)
"""
import csv
import json
import socket
import time
from datetime import datetime

from config import COLUMNS, LIVE_DATA_DIR, UDP_PORT


def todays_file():
    return LIVE_DATA_DIR / f"{datetime.now():%Y-%m-%d}.csv"


def main():
    LIVE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))  # 0.0.0.0 = listen on every network the laptop is on
    sock.settimeout(1.0)              # wake up every second so Ctrl+C works on Windows
    print(f"Receiver listening on UDP port {UDP_PORT}. Saving to {LIVE_DATA_DIR}")
    print("Waiting for the plug... (Ctrl+C to stop)")

    current_path, f, writer = None, None, None
    last_key = None        # to drop accidental duplicate messages
    count, last_report = 0, time.monotonic()
    sender = None

    try:
        while True:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                if sender and time.monotonic() - last_report > 5:
                    print("  ...no readings in the last few seconds")
                    last_report = time.monotonic()
                continue

            try:
                msg = json.loads(data)
                row = {k: float(msg[k]) for k in COLUMNS[1:]}
            except (ValueError, KeyError, TypeError):
                print(f"  ignored a message I don't understand from {addr[0]}")
                continue

            key = (addr[0], msg.get("t_ms"))
            if key == last_key:
                continue
            last_key = key

            # New day (or first message) -> open the right file
            path = todays_file()
            if path != current_path:
                if f:
                    f.close()
                is_new = not path.exists()
                f = open(path, "a", newline="")
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(COLUMNS)
                current_path = path
                print(f"Writing to {path.name}")

            if sender != addr[0]:
                sender = addr[0]
                print(f"Getting readings from {sender}")

            writer.writerow([f"{time.time():.3f}"] + [row[k] for k in COLUMNS[1:]])
            f.flush()  # so the dashboard sees it straight away

            count += 1
            if time.monotonic() - last_report > 5:
                print(f"saved {count:6d} readings | latest: {row['p']:7.1f} W")
                last_report = time.monotonic()
    except KeyboardInterrupt:
        print("\nReceiver stopped.")
    finally:
        if f:
            f.close()


if __name__ == "__main__":
    main()
