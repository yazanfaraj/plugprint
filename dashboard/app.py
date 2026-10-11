"""
app.py — the plugprint live dashboard (the "screen").

Reads today's CSV that receiver.py is filling and shows:
  * power right now, energy used today, what it cost in AED
  * a live chart of power over the last few minutes
  * energy used in each hour of today

Run it:   py -m streamlit run app.py
It opens in your browser at http://localhost:8501 and refreshes every second.
"""
from datetime import datetime
import io

import altair as alt
import pandas as pd
import streamlit as st

from config import COLUMNS, DEFAULT_TARIFF_AED_PER_KWH, LIVE_DATA_DIR, MAX_GAP_SECONDS

LOCAL_TZ = datetime.now().astimezone().tzinfo   # the laptop's time zone (Dubai)
LINE_COLOR = "#2a78d6"                           # one hue for one series
WINDOWS = {"2 minutes": 120, "10 minutes": 600, "1 hour": 3600, "Today": None}

st.set_page_config(page_title="plugprint", page_icon="⚡", layout="wide")


# ---------------------------------------------------------------------------
# Reading the data — only the NEW rows each second
# ---------------------------------------------------------------------------
# Re-reading a whole day of data every second would get slow (5 readings a
# second = 432,000 rows a day). So we remember how far into the file we got,
# like a bookmark, and only read what was added since.
def load_new_rows():
    path = LIVE_DATA_DIR / f"{datetime.now():%Y-%m-%d}.csv"
    state = st.session_state
    if state.get("path") != path:                 # first run, or it's a new day
        state.path, state.offset = path, 0
        state.df = pd.DataFrame(columns=COLUMNS, dtype=float)
    if not path.exists():
        return state.df

    with open(path, "rb") as f:
        f.seek(state.offset)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1                  # only use complete lines
    if end == 0:
        return state.df
    state.offset += end

    text = chunk[:end].decode()
    if text.startswith("time,"):                  # skip the header line
        text = text.split("\n", 1)[1]
    if text.strip():
        new = pd.read_csv(io.StringIO(text), names=COLUMNS)
        state.df = new if state.df.empty else pd.concat([state.df, new], ignore_index=True)
    return state.df


def add_energy(df):
    """Energy for each reading = power x time since the previous reading (D18)."""
    dt = df["time"].diff().fillna(0)
    dt = dt.where(dt <= MAX_GAP_SECONDS, 0)      # gap = plug was offline, count nothing
    out = df.assign(
        when=pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(LOCAL_TZ),
        joules=df["p"] * dt,                      # watts x seconds = joules
    )
    return out


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.title("⚡ plugprint")
st.caption("Live energy monitor for one power strip")

with st.sidebar:
    st.header("Settings")
    tariff = st.number_input(
        "Electricity price (AED per kWh)", min_value=0.0, max_value=2.0,
        value=DEFAULT_TARIFF_AED_PER_KWH, step=0.01, format="%.2f",
        help="Dubai (DEWA) first slab incl. fuel surcharge + VAT ≈ 0.31. "
             "Check your own bill for the exact figure.",
    )
    window_name = st.radio("Chart shows the last…", list(WINDOWS), index=0)


@st.fragment(run_every="1s")   # this part of the page redraws itself every second
def live_view():
    df = load_new_rows()
    if df.empty:
        st.info("No readings yet today. Start **receiver.py** and **fake_plug.py** "
                "(or the real plug), and they'll appear here within a second.")
        return

    df = add_energy(df)
    latest = df.iloc[-1]
    age = datetime.now().timestamp() - latest["time"]
    kwh_today = df["joules"].sum() / 3.6e6       # 1 kWh = 3,600,000 joules

    if age < 3:
        st.success("● Live")
    else:
        st.warning(f"No new readings for {age:,.0f} s — is the plug or receiver running?")

    # --- Headline numbers --------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Power now", f"{latest['p']:,.0f} W")
    c2.metric("Energy today", f"{kwh_today:.3f} kWh")
    c3.metric("Cost today", f"{kwh_today * tariff:.2f} AED")
    c4.metric("Power factor", f"{latest['pf']:.2f}",
              help="1.00 = heater-like. Lower = motors and chargers.")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Voltage", f"{latest['v']:.1f} V")
    d2.metric("Current", f"{latest['i']:.2f} A")
    d3.metric("Apparent power", f"{latest['s']:,.0f} VA")
    d4.metric("Sampling rate", f"{latest['rate']:,.0f} Hz",
              help="Should stay at 4,000 Hz (D17).")

    # --- Power over time ---------------------------------------------------
    seconds = WINDOWS[window_name]
    recent = df if seconds is None else df[df["time"] >= latest["time"] - seconds]
    # Long windows: average into 1 s / 10 s buckets so the chart stays fast
    if seconds is None or seconds > 600:
        bucket = "10s" if seconds is None else "1s"
        recent = (recent.set_index("when")["p"].resample(bucket).mean()
                  .dropna().reset_index())

    st.subheader(f"Power — last {window_name.lower()}" if seconds else "Power — today")
    power_chart = (
        alt.Chart(recent)
        .mark_line(color=LINE_COLOR, strokeWidth=2, interpolate="step-after")
        .encode(
            x=alt.X("when:T", title=None, axis=alt.Axis(format="%H:%M:%S", grid=False)),
            y=alt.Y("p:Q", title="Watts", scale=alt.Scale(zero=True)),
            tooltip=[alt.Tooltip("when:T", title="Time", format="%H:%M:%S"),
                     alt.Tooltip("p:Q", title="Watts", format=",.0f")],
        )
        .properties(height=280)
    )
    st.altair_chart(power_chart, width="stretch")

    # --- Energy per hour -----------------------------------------------------
    st.subheader("Energy used each hour today")
    # Group by hour of the day (0-23) and always show all 24 slots
    hourly = (df.groupby(df["when"].dt.hour)["joules"].sum() / 3.6e6).reindex(range(24), fill_value=0)
    hourly = pd.DataFrame({"hour": [f"{h:02d}:00" for h in range(24)], "kwh": hourly.values})
    hourly["aed"] = hourly["kwh"] * tariff
    energy_chart = (
        alt.Chart(hourly)
        .mark_bar(color=LINE_COLOR, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("hour:O", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
            y=alt.Y("kwh:Q", title="kWh"),
            tooltip=[alt.Tooltip("hour:O", title="Hour"),
                     alt.Tooltip("kwh:Q", title="kWh", format=".3f"),
                     alt.Tooltip("aed:Q", title="AED", format=".2f")],
        )
        .properties(height=220)
    )
    st.altair_chart(energy_chart, width="stretch")


live_view()
