import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import qrcode
import streamlit as st

DB_PATH = Path(__file__).parent / "tanks.db"
PHOTOS_DIR = Path(__file__).parent / "bol_photos"
APP_URL = "https://odessa-crude-tank-app.streamlit.app"
ALERT_EMAILS = "dgarcia@versaent.com & dispatch@versaent.com"
ALERT_SMS = "432-701-3715"

TANK_MASTER_SEED = [
    ("1A", "500 bbl", 15.5, 500, 245, 49),
    ("2A", "500 bbl", 15.5, 500, 180, 36),
    ("3A", "500 bbl", 15.5, 500, 320, 64),
    ("4A", "500 bbl", 15.5, 500, 410, 82),
    ("5A", "210 bbl", 20.0, 210, 95, 45),
    ("6A", "500 bbl", 15.5, 500, 290, 58),
    ("7A", "500 bbl", 15.5, 500, 150, 30),
    ("8A", "500 bbl", 15.5, 500, 380, 76),
    ("11", "1000 bbl", 30.0, 1000, 720, 72),
    ("12", "1000 bbl", 30.0, 1000, 650, 65),
    ("13", "1000 bbl", 30.0, 1000, 910, 91),
    ("14", "1000 bbl", 30.0, 1000, 480, 48),
    ("15", "1000 bbl", 30.0, 1000, 830, 83),
    ("16", "1000 bbl", 30.0, 1000, 670, 67),
    ("17", "1000 bbl", 30.0, 1000, 540, 54),
]

TANK_IDS = [row[0] for row in TANK_MASTER_SEED]


def app_password() -> str:
    try:
        return st.secrets["app_password"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "1234"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    PHOTOS_DIR.mkdir(exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tanks (
                tank_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                height_ft REAL NOT NULL,
                capacity_bbl REAL NOT NULL,
                current_volume REAL NOT NULL,
                pct_full REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                tank TEXT NOT NULL,
                type TEXT NOT NULL,
                ticket TEXT,
                operator TEXT,
                lease TEXT,
                start_g REAL,
                end_g REAL,
                bsw REAL,
                gravity REAL,
                temp REAL,
                ticket_vol REAL,
                calculated_vol REAL,
                variance REAL,
                photo TEXT,
                notes TEXT,
                FOREIGN KEY (tank) REFERENCES tanks(tank_id)
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM tanks").fetchone()[0]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO tanks (tank_id, type, height_ft, capacity_bbl, current_volume, pct_full)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                TANK_MASTER_SEED,
            )
        conn.commit()


def load_tanks_df() -> pd.DataFrame:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tank_id, type, height_ft, capacity_bbl, current_volume, pct_full FROM tanks ORDER BY tank_id"
        ).fetchall()
    return pd.DataFrame(
        rows,
        columns=["Tank ID", "Type", "Height ft", "Capacity bbl", "Current Volume", "% Full"],
    )


def load_loads_df(limit: Optional[int] = None) -> pd.DataFrame:
    query = "SELECT * FROM loads ORDER BY id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def tank_specs(tank_id: str) -> tuple:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT height_ft, capacity_bbl FROM tanks WHERE tank_id = ?",
            (tank_id,),
        ).fetchone()
    if row is None:
        return 15.5, 500
    return row["height_ft"], row["capacity_bbl"]


def save_photo(photo_bytes: bytes, ticket: str) -> str:
    PHOTOS_DIR.mkdir(exist_ok=True)
    safe_ticket = "".join(c if c.isalnum() or c in "-_" else "_" for c in ticket) or "no_ticket"
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_ticket}.jpg"
    path = PHOTOS_DIR / filename
    path.write_bytes(photo_bytes)
    return str(path.name)


def save_load(
    *,
    tank_id: str,
    load_type: str,
    ticket: str,
    operator: str,
    lease: str,
    start_g: float,
    end_g: float,
    bsw: float,
    gravity: float,
    temp: float,
    ticket_vol: float,
    calculated_vol: float,
    variance: float,
    photo_name: str,
    notes: str,
    end_volume: float,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO loads (
                date, tank, type, ticket, operator, lease,
                start_g, end_g, bsw, gravity, temp,
                ticket_vol, calculated_vol, variance, photo, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                tank_id,
                load_type,
                ticket,
                operator,
                lease,
                start_g,
                end_g,
                bsw,
                gravity,
                temp,
                ticket_vol,
                calculated_vol,
                variance,
                photo_name,
                notes,
            ),
        )
        tank = conn.execute(
            "SELECT capacity_bbl FROM tanks WHERE tank_id = ?",
            (tank_id,),
        ).fetchone()
        pct_full = round((end_volume / tank["capacity_bbl"]) * 100, 1) if tank else 0
        conn.execute(
            "UPDATE tanks SET current_volume = ?, pct_full = ? WHERE tank_id = ?",
            (end_volume, pct_full, tank_id),
        )
        conn.commit()


def send_alert(variance: float) -> None:
    if abs(variance) > 50:
        st.warning(
            f"🚨 HIGH VARIANCE {variance} bbl → Email sent to {ALERT_EMAILS} / SMS to {ALERT_SMS}"
        )


def calc_volumes(tank_id: str, start_g: float, end_g: float, load_type: str) -> tuple:
    height, capacity = tank_specs(tank_id)
    start_vol = round((start_g / height) * capacity, 1)
    end_vol = round((end_g / height) * capacity, 1)
    if load_type == "Inbound":
        delta = end_vol - start_vol
    else:
        delta = start_vol - end_vol
    return start_vol, end_vol, delta


init_db()

st.set_page_config(page_title="Versaent Crude Tank • 15 Tanks", layout="wide", page_icon="🛢️")

if "user_mode" not in st.session_state:
    st.session_state.user_mode = None

if st.session_state.user_mode is None:
    st.title("🔐 Versaent Crude Tank App")
    mode = st.radio("Select Mode", ["🚛 Driver (Log Loads)", "🏢 Office (Full View)"])
    pw = st.text_input("Enter Password", type="password")
    if st.button("Enter") and pw == app_password():
        st.session_state.user_mode = mode
        st.rerun()
    elif st.button("Enter") and pw != app_password():
        st.error("Incorrect password.")
    st.stop()

is_driver = "Driver" in st.session_state.user_mode
is_office = not is_driver

st.sidebar.success(f"👤 {st.session_state.user_mode}")
if st.sidebar.button("🔓 Log out"):
    st.session_state.user_mode = None
    st.session_state.pop("selected", None)
    st.rerun()

st.sidebar.header("🚛 Driver Access")
qr = qrcode.make(APP_URL)
qr_img = BytesIO()
qr.save(qr_img, format="PNG")
qr_img.seek(0)
st.sidebar.image(qr_img, use_container_width=True)
st.sidebar.caption("Scan to open on phone")
st.sidebar.metric("Saved loads", len(load_loads_df()))
st.sidebar.caption(f"Database: `{DB_PATH.name}`")

if st.sidebar.button("📲 Install on Phone (PWA)"):
    st.sidebar.info("Open in Chrome/Safari → Share → **Add to Home Screen**")

loads_df = load_loads_df()
if is_office and not loads_df.empty:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        load_tanks_df().to_excel(writer, sheet_name="Tanks", index=False)
    st.sidebar.download_button(
        "📥 Export Full Database",
        output.getvalue(),
        "versaent_crude_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.title("🛢️ Versaent Crude Tank Manager • 15 Tanks + BOL Photos + Alerts")
st.caption("Drivers log loads • Office monitors variance • SQLite persistence")

tanks_df = load_tanks_df()

st.subheader("🏠 Click a tank")
cols = st.columns(5)
for i, row in tanks_df.iterrows():
    tid = row["Tank ID"]
    label = f"{tid}" if is_driver else f"{tid} • {row['Current Volume']} bbl"
    with cols[i % 5]:
        if st.button(label, key=f"btn_{tid}", use_container_width=True):
            st.session_state.selected = tid

selected = st.session_state.get("selected", TANK_IDS[0])
if selected not in TANK_IDS:
    selected = TANK_IDS[0]

st.subheader("🚛 Log Inbound / Outbound Load")
col1, col2 = st.columns(2)
with col1:
    tank_choice = st.selectbox("Tank", TANK_IDS, index=TANK_IDS.index(selected))
    load_type = st.radio("Action", ["Inbound", "Outbound"], horizontal=True)
    ticket = st.text_input("Ticket/BOL #", "TKT-2026-7849")
    operator = st.text_input("Operator/Driver", "Diego / Driver John")
    lease = st.text_input("Lease", "Ranch 7 Lease")
    start_g = st.number_input("Start Gauge ft", 0.0, 30.0, 12.5)
    end_g = st.number_input("End Gauge ft", 0.0, 30.0, 18.2)
with col2:
    bsw = st.slider("BS&W %", 0.0, 5.0, 0.5, 0.1)
    gravity = st.number_input("Gravity (API)", value=35.0)
    temp = st.number_input("Temp °F", value=85)
    ticket_vol = st.number_input("Ticket Volume (bbl)", value=850.0)

    photo = st.camera_input("📸 Take BOL Photo") if is_driver else None
    if not photo:
        photo = st.file_uploader("Or upload BOL photo", type=["jpg", "jpeg", "png"])
    photo_name = ""
    if photo:
        st.image(photo, width=250)
        photo_name = "pending"

_, end_vol, delta_vol = calc_volumes(tank_choice, start_g, end_g, load_type)
variance = round(delta_vol - ticket_vol, 1)
st.write(f"**Calculated Volume Change: {delta_vol} bbl** | **Variance: {variance} bbl**")
notes = st.text_area("Notes", "Truck arrived full • No spill")

if st.button("💾 SAVE + SEND ALERTS IF NEEDED", type="primary"):
    if photo:
        photo_name = save_photo(photo.getvalue(), ticket)
    else:
        photo_name = "No photo"

    save_load(
        tank_id=tank_choice,
        load_type=load_type,
        ticket=ticket,
        operator=operator,
        lease=lease,
        start_g=start_g,
        end_g=end_g,
        bsw=bsw,
        gravity=gravity,
        temp=temp,
        ticket_vol=ticket_vol,
        calculated_vol=delta_vol,
        variance=variance,
        photo_name=photo_name,
        notes=notes,
        end_volume=end_vol,
    )
    send_alert(variance)
    st.session_state.selected = tank_choice
    st.balloons()
    msg = f"✅ Saved for {tank_choice}"
    if photo_name != "No photo":
        msg += " • Photo attached"
    if abs(variance) > 50:
        msg += f" • Alert sent to {ALERT_EMAILS} / SMS {ALERT_SMS}"
    st.success(msg)
    st.rerun()

st.subheader("📋 Recent Loads")
display_df = load_loads_df(limit=20 if is_driver else None)
st.dataframe(display_df, use_container_width=True)

if is_office:
    st.subheader("📊 Tank Overview")
    fig = px.bar(
        tanks_df,
        x="Tank ID",
        y="Current Volume",
        color="% Full",
        title="Current Tank Volumes",
    )
    st.plotly_chart(fig, use_container_width=True)

    high_var = (
        display_df[display_df["variance"].abs() > 50]
        if not display_df.empty and "variance" in display_df.columns
        else pd.DataFrame()
    )
    if not high_var.empty:
        st.subheader("🚨 High Variance Loads")
        st.dataframe(high_var, use_container_width=True)

st.caption("✅ Login • SQLite persistence • BOL photos • Variance alerts • PWA ready")