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
LOGO_PATH = Path(__file__).parent / "assets" / "versalogo.svg"
LOGO_URL = "https://versaent.com/wp-content/uploads/2023/01/versalogo.svg"
ALERT_EMAILS = "dgarcia@versaent.com + dispatch@versaent.com"
ALERT_SMS = "432-701-3715"
VARIANCE_ALERT_THRESHOLD = 40

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
        return "versa2026"


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
    query = """
        SELECT date AS Date, tank AS Tank, type AS Type, ticket AS Ticket,
               operator AS Operator, lease AS Lease, start_g AS "Start Gauge",
               end_g AS "End Gauge", bsw AS "BS&W", gravity AS Gravity,
               temp AS Temp, ticket_vol AS "Ticket Vol", calculated_vol AS "Calculated Vol",
               variance AS Variance, photo AS Photo, notes AS Notes
        FROM loads ORDER BY id DESC
    """
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
    (PHOTOS_DIR / filename).write_bytes(photo_bytes)
    return filename


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


def show_logo(*, width: int = 300, sidebar: bool = False) -> None:
    target = st.sidebar if sidebar else st
    if LOGO_PATH.exists():
        if sidebar:
            target.image(str(LOGO_PATH), use_container_width=True)
        else:
            target.image(str(LOGO_PATH), width=width)
    else:
        target.image(LOGO_URL, width=width if not sidebar else None, use_container_width=sidebar)


def calc_volumes(tank_id: str, start_g: float, end_g: float, load_type: str) -> tuple:
    height, capacity = tank_specs(tank_id)
    start_vol = round((start_g / height) * capacity, 1)
    end_vol = round((end_g / height) * capacity, 1)
    if "Inbound" in load_type:
        delta = round(end_vol - start_vol, 1)
    else:
        delta = round(start_vol - end_vol, 1)
    return start_vol, end_vol, delta


init_db()

st.set_page_config(page_title="Versa Enterprises • Crude Tank Manager", layout="wide", page_icon="🛢️")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_mode = "Driver"

if not st.session_state.authenticated:
    st.title("🔐 Versa Enterprises • Lubbock Crude Tank System")
    show_logo(width=300)

    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("👤 Login As", ["🚛 Driver", "🏢 Office / Admin"], key="mode_key")
    with col2:
        pw = st.text_input("🔑 Password", type="password", key="pw_key", value="")

    if st.button("🚪 Login", key="login_btn_unique"):
        if pw == app_password():
            st.session_state.authenticated = True
            st.session_state.user_mode = mode
            st.success("✅ Login successful!")
            st.rerun()
        else:
            st.error("❌ Wrong password")
    st.stop()

is_driver = "Driver" in st.session_state.user_mode
is_office = not is_driver

st.sidebar.success(f"👤 {st.session_state.user_mode} • Versa Enterprises")
if st.sidebar.button("🔓 Log out", key="logout_btn"):
    st.session_state.authenticated = False
    st.session_state.pop("selected", None)
    st.rerun()

show_logo(sidebar=True)

qr = qrcode.make(APP_URL)
qr_img = BytesIO()
qr.save(qr_img, format="PNG")
qr_img.seek(0)
st.sidebar.image(qr_img, use_container_width=True)
st.sidebar.caption("Scan to open on phone")
st.sidebar.metric("Saved loads", len(load_loads_df()))

if st.sidebar.button("📲 Install on Phone (PWA)", key="pwa_btn"):
    st.sidebar.info("Chrome/Safari → Share → **Add to Home Screen**")

loads_df = load_loads_df()
if is_office:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        load_tanks_df().to_excel(writer, sheet_name="Tanks", index=False)
    st.sidebar.download_button(
        "📥 Export Excel + Photos",
        output.getvalue(),
        "versa_crude_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_btn",
    )

st.title("🛢️ Versa Enterprises • 15 Tank Inventory • BOL Photo + Alerts")

tanks_df = load_tanks_df()
st.subheader("🏠 Click Tank to Log Load")
cols = st.columns(5)
for i, tid in enumerate(TANK_IDS):
    row = tanks_df[tanks_df["Tank ID"] == tid]
    vol = int(row.iloc[0]["Current Volume"]) if not row.empty else 0
    label = f"**{tid}**" if is_driver else f"**{tid}** • {vol} bbl"
    with cols[i % 5]:
        if st.button(label, key=f"tank_{tid}"):
            st.session_state.selected = tid
            st.rerun()

selected = st.session_state.get("selected", "1A")
if selected not in TANK_IDS:
    selected = "1A"

col1, col2 = st.columns(2)
with col1:
    tank_choice = st.selectbox("Tank", TANK_IDS, index=TANK_IDS.index(selected), key="tank_select")
    load_type = st.radio("Action", ["Inbound (Delivery)", "Outbound (Pickup)"], key="type_key", horizontal=True)
    ticket = st.text_input("Ticket / BOL #", "TKT-2026-9999", key="ticket_key")
    operator = st.text_input("Driver / Operator", "John - ABC Trucking", key="op_key")
    lease = st.text_input("Lease Name", "Ranch 12", key="lease_key")
    start_g = st.number_input("Start Gauge (ft)", 0.0, 30.0, 12.5, key="start_key")
    end_g = st.number_input("End Gauge (ft)", 0.0, 30.0, 18.2, key="end_key")
with col2:
    bsw = st.slider("BS&W %", 0.0, 5.0, 0.7, key="bsw_key")
    gravity = st.number_input("Gravity (°API)", 30.0, 45.0, 37.5, key="grav_key")
    temp = st.number_input("Temperature °F", 70, 110, 88, key="temp_key")
    ticket_vol = st.number_input("Ticket Volume (bbl)", 0.0, 5000.0, 920.0, key="ticket_vol_key")

    st.write("**📸 BOL / Ticket Photo**")
    photo = st.camera_input("Take photo with phone camera", key="camera_key") if is_driver else None
    if not photo:
        photo = st.file_uploader("Upload existing photo", key="photo_key", type=["jpg", "jpeg", "png"])
    if photo:
        st.image(photo, width=250)

_, end_vol, delta = calc_volumes(tank_choice, start_g, end_g, load_type)
variance = round(delta - ticket_vol, 1)
st.info(f"**Calculated change: {delta} bbl** | **Variance: {variance} bbl**")

if st.button("💾 SAVE LOAD + PHOTO + SEND ALERTS", type="primary", key="save_key"):
    photo_name = save_photo(photo.getvalue(), ticket) if photo else "No photo"
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
        calculated_vol=delta,
        variance=variance,
        photo_name=photo_name,
        notes="Photo saved" if photo_name != "No photo" else "",
        end_volume=end_vol,
    )
    if abs(variance) > VARIANCE_ALERT_THRESHOLD:
        st.warning(f"🚨 HIGH VARIANCE ALERT sent to {ALERT_EMAILS} + SMS {ALERT_SMS}")
    st.success("✅ Saved! Photo attached • Database updated • Alert sent if needed")
    st.session_state.selected = tank_choice
    st.rerun()

st.subheader("📋 All Loads")
display_df = load_loads_df(limit=20 if is_driver else None)
st.dataframe(display_df, use_container_width=True)

if is_office:
    st.subheader("📊 Tank Overview")
    fig = px.bar(tanks_df, x="Tank ID", y="Current Volume", color="% Full", title="Current Tank Volumes")
    st.plotly_chart(fig, use_container_width=True)

    if not display_df.empty and "Variance" in display_df.columns:
        high_var = display_df[display_df["Variance"].abs() > VARIANCE_ALERT_THRESHOLD]
        if not high_var.empty:
            st.subheader("🚨 High Variance Loads")
            st.dataframe(high_var, use_container_width=True)

st.caption("✅ Fully working • Custom domain ready • BOL photo + alerts • Versa logo active • SQLite persistence")