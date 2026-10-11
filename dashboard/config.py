"""
Shared settings for the plugprint dashboard.

All three scripts (fake_plug.py, receiver.py, app.py) import from here, so a
number only ever has to be changed in one place.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# How readings travel from the plug to the laptop (D23)
# ---------------------------------------------------------------------------
# The plug "shouts" every reading to the whole home network (UDP broadcast) on
# this port number. The receiver listens on the same port. A port is like an
# apartment number: the network gets the message to the right building (the
# laptop), the port gets it to the right door (our program).
UDP_PORT = 4210

# ---------------------------------------------------------------------------
# Where readings are saved
# ---------------------------------------------------------------------------
# One CSV file per day, e.g. data/live/2026-10-11.csv
# These files are git-ignored: they're personal and they grow large.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIVE_DATA_DIR = PROJECT_ROOT / "data" / "live"

# Columns in every CSV row (and keys in every message from the plug)
COLUMNS = ["time", "v", "i", "p", "s", "pf", "rate", "late"]

# ---------------------------------------------------------------------------
# Money (D24)
# ---------------------------------------------------------------------------
# Dubai (DEWA) home tariff, first slab: 23 fils/kWh + 6.5 fils fuel surcharge,
# then + 5% VAT  ->  about 0.31 AED per kWh. You can change it live in the
# dashboard's sidebar (e.g. for Abu Dhabi, check a real bill).
DEFAULT_TARIFF_AED_PER_KWH = 0.31

# ---------------------------------------------------------------------------
# Energy maths safety net
# ---------------------------------------------------------------------------
# Energy = power x time between readings. If two readings are further apart
# than this (plug unplugged, WiFi dropped), we DON'T assume the power stayed
# on during the gap.
MAX_GAP_SECONDS = 2.0
