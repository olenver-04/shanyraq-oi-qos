"""Шаңыраққа ой қос! — interactive Kazakh lesson feedback wall.

Run: streamlit run app.py
Deploy: GitHub + https://share.streamlit.io/
Set ADMIN_PASSWORD in Streamlit Cloud → App settings → Secrets.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import html
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import qrcode
import streamlit as st


st.set_page_config(
    page_title="Шаңыраққа ой қос! | Интерактивті сабақ",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_PATH = Path(__file__).with_name("shanyraq_responses.db")
ALMATY = ZoneInfo("Asia/Almaty")
ACTIVITIES = {
    "punctuation": {
        "emoji": "✍️",
        "title": "Сөйлем құрастыр",
        "label": "1 · Тыныс белгілері",
        "tag": "ТЫРНАҚША · ЖАҚША · НҮКТЕЛІ ҮТІР",
        "prompt": "Киіз үй туралы сөйлем құрастыр. «Тырнақша», (жақша) немесе нүктелі үтірді (;) дұрыс қолдан.",
        "placeholder": "Мысалы: «Шаңырақ» – киіз үйдің ең маңызды бөліктерінің бірі.",
        "example": "Кереге (киіз үйдің қабырғасы) тор көздерден тұрады; ол жиналып, оңай тасымалданады.",
        "hint": "Сөйлеміңде кемінде бір тыныс белгісі болсын: «...» / (...) / ;",
        "tone": "#8a6040",
    },
    "design": {
        "emoji": "🎨",
        "title": "Мен дизайнер болсам...",
        "label": "2 · Дизайн идеясы",
        "tag": "ДИЗАЙН · ҰЛТТЫҚ ӨНЕР · БОЛАШАҚ",
        "prompt": "Егер сен дизайнер болсаң, заманауи киіз үйді қалай безендірер едің? Бір ерекше идея ұсын.",
        "placeholder": "Мысалы: Мен киіз үйдің ішін ұлттық оюлармен және жылы жарықпен безендірер едім...",
        "example": "Мен киіз үйге күн энергиясымен жұмыс істейтін жарық орнатар едім, ал ішкі көрінісін ұлттық нақышта жасар едім.",
        "hint": "Ұлттық дәстүр мен заманауи технологияны үйлестіруге тырыс.",
        "tone": "#1b7776",
    },
    "reflection": {
        "emoji": "💭",
        "title": "Бүгін мен білдім...",
        "label": "3 · Рефлексия",
        "tag": "ОЙ ТОЛҒАУ · САБАҚ ҚОРЫТЫНДЫСЫ",
        "prompt": "Бүгін киіз үй, дизайн өнері немесе тыныс белгілері туралы қандай жаңа білім алдың?",
        "placeholder": "Мысалы: Бүгін мен шаңырақтың мағынасын және нүктелі үтірдің қолданылуын білдім...",
        "example": "Бүгін мен киіз үйдің бөліктерін және тырнақшаның қандай жағдайда қолданылатынын білдім.",
        "hint": "Бір сөйлем жеткілікті. Ең маңызды ойыңды жаз.",
        "tone": "#956f32",
    },
}
STAGES = list(ACTIVITIES)


@contextmanager
def db():
    """A new connection per action avoids sharing connections between students."""
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=20000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            activity TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('active_stage', 'punctuation')")


def add_response(name: str, stage: str, message: str):
    if stage not in ACTIVITIES:
        raise ValueError("Unknown activity")
    name = " ".join(name.strip().split())
    message = message.strip()
    if not 2 <= len(name) <= 40 or not 3 <= len(message) <= 400:
        raise ValueError("Invalid name or feedback length")
    with db() as con:
        con.execute(
            "INSERT INTO responses(student_name, activity, message, created_at) VALUES(?,?,?,?)",
            (name, stage, message, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def list_responses(stage: str = "all", limit: int = 120):
    with db() as con:
        if stage == "all":
            return con.execute("SELECT * FROM responses ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        if stage not in ACTIVITIES:
            raise ValueError("Unknown activity")
        return con.execute(
            "SELECT * FROM responses WHERE activity = ? ORDER BY id DESC LIMIT ?",
            (stage, limit),
        ).fetchall()


def response_counts():
    with db() as con:
        rows = con.execute("SELECT activity, COUNT(*) AS n FROM responses GROUP BY activity").fetchall()
    data = {stage: 0 for stage in STAGES}
    for row in rows:
        if row["activity"] in data:
            data[row["activity"]] = row["n"]
    return data


def get_stage():
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='active_stage'").fetchone()
    stage = row["value"] if row else "punctuation"
    return stage if stage in ACTIVITIES else "punctuation"


def set_stage(stage: str):
    if stage not in ACTIVITIES:
        raise ValueError("Unknown activity")
    with db() as con:
        con.execute("UPDATE settings SET value=? WHERE key='active_stage'", (stage,))


def delete_response(response_id: int):
    with db() as con:
        con.execute("DELETE FROM responses WHERE id=?", (response_id,))


def clear_responses(stage: str = "all"):
    with db() as con:
        if stage == "all":
            con.execute("DELETE FROM responses")
        elif stage in ACTIVITIES:
            con.execute("DELETE FROM responses WHERE activity=?", (stage,))
        else:
            raise ValueError("Unknown activity")


def safe_csv_cell(value):
    text = str(value)
    # Keep spreadsheet software from evaluating user-controlled content as a formula.
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def export_csv(rows):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["№", "Оқушының аты", "Белсенділік", "Пікір", "Уақыты (UTC)"])
    for row in rows:
        act = ACTIVITIES.get(row["activity"], {})
        writer.writerow([
            row["id"], safe_csv_cell(row["student_name"]),
            act.get("title", "—"), safe_csv_cell(row["message"]), row["created_at"],
        ])
    return buffer.getvalue().encode("utf-8-sig")


def has_required_punctuation(message: str):
    return (
        ("«" in message and "»" in message)
        or ("(" in message and ")" in message)
        or (";" in message)
        or (message.count('"') >= 2)
        or ("“" in message and "”" in message)
    )


def qr_png(url: str):
    qr = qrcode.QRCode(
        version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12, border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#183b36", back_color="#ffffff")
    mem = BytesIO()
    image.save(mem, format="PNG")
    return mem.getvalue()


def esc(value):
    return html.escape(str(value), quote=True)


def shanyrak_svg():
    """A custom vector shanyrak graphic, no third-party image files required."""
    spokes = []
    for deg in range(0, 360, 18):
        a = math.radians(deg)
        x1, y1 = 150 + 82 * math.cos(a), 150 + 82 * math.sin(a)
        x2, y2 = 150 + 124 * math.cos(a), 150 + 124 * math.sin(a)
        spokes.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            'stroke="#d8ad61" stroke-width="6" stroke-linecap="round"/>'
        )
    return """<svg class="shanyraq-svg" viewBox="0 0 300 300" role="img" aria-label="Шаңырақ өрнегі">
    <defs><radialGradient id="g1"><stop stop-color="#f7e0ae" stop-opacity=".18"/>
    <stop offset="1" stop-color="#f7e0ae" stop-opacity="0"/></radialGradient></defs>
    <circle cx="150" cy="150" r="147" fill="url(#g1)"/>
    <circle cx="150" cy="150" r="129" fill="none" stroke="#e7c383" stroke-width="9"/>
    <circle cx="150" cy="150" r="112" fill="none" stroke="#e7c383" stroke-width="3" opacity=".6"/>
    """ + "".join(spokes) + """
    <circle cx="150" cy="150" r="76" fill="#163e3a" stroke="#d8ad61" stroke-width="7"/>
    <g stroke="#e7c383" stroke-width="11" stroke-linecap="round" opacity=".98">
    <path d="M104 83 L104 217 M150 77 L150 223 M196 83 L196 217"/>
    <path d="M83 104 L217 104 M77 150 L223 150 M83 196 L217 196"/>
    </g>
    <circle cx="150" cy="150" r="75" fill="none" stroke="#e7c383" stroke-width="6"/>
    <circle cx="150" cy="150" r="10" fill="#e7c383"/>
    </svg>"""


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Playfair+Display:wght@600;700&display=swap');
:root { --pine:#143e38; --pine2:#1c5e57; --gold:#c39a58; --cream:#f8f5ed; --ink:#17372f; --muted:#6e7970; }
html, body, [class*="st-"] { font-family:'Manrope',sans-serif; }
.stApp { background: radial-gradient(ellipse 690px 420px at 96% -7%,#e8e3d2 0%,transparent 75%),
                       radial-gradient(ellipse 640px 380px at -9% 90%,#e4eee6 0%,transparent 78%),#f8f5ed; }
.block-container { max-width:1280px; padding-top:1.3rem; padding-bottom:3.5rem; }
[data-testid="stHeader"] { background:transparent; }
#MainMenu,footer {visibility:hidden;}
[data-testid="stMarkdownContainer"] p { line-height:1.6; }
h1,h2,h3 { color:#17372f; }
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea { background:#fffdf8;
   border:1px solid #d9d8ca; border-radius:13px; color:#17372f; font-size:1.03rem; }
[data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus { border-color:#3e8d7d; }
[data-testid="stRadio"] label { color:#143e38; }
[data-testid="stFormSubmitButton"] button[kind="primary"], .stButton button[kind="primary"] {
  border:none; color:white; background:linear-gradient(110deg,#19574e,#2d8274);
  border-radius:13px; font-weight:800; min-height:3rem; }
.stButton button, .stDownloadButton button, .stLinkButton a { border-radius:13px; font-weight:700; }
.brandline {display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;
 padding:6px 0 18px;color:#1a4940;font-size:.8rem;font-weight:800;letter-spacing:.10em;}
.brandline .brand {font-family:'Manrope',sans-serif;font-size:1.04rem;letter-spacing:0;color:#165248;}
.brandline .crumb {color:#88958b;font-weight:700;font-size:.77rem;}
.hero {position:relative;overflow:hidden;border-radius:26px;padding:34px 34px 28px;
 background:linear-gradient(118deg,#143e38,#20564d 62%,#356b57);color:#fff8e9;
 box-shadow:0 18px 36px #11392e1b;min-height:275px;}
.hero::before {content:"";position:absolute;inset:0;pointer-events:none;opacity:.16;
 background-image:repeating-linear-gradient(45deg,transparent 0px,transparent 25px,#e7c383 26px,transparent 27px);}
.hero::after {content:"";position:absolute;width:360px;height:360px;border:1px solid #b99c6b55;
 border-radius:50%;top:-220px;right:0;box-shadow:0 0 0 35px #b99c6b12,0 0 0 70px #b99c6b0a;}
.hero-content {position:relative;z-index:2;max-width:700px;}
.eyebrow {display:inline-block;color:#f7dfad;border:1px solid #e3bd7480;background:#ffffff12;
 border-radius:99px;padding:7px 13px;font-size:.68rem;font-weight:800;letter-spacing:.15em;}
.hero h1 {color:#fffbf2;font-family:'Playfair Display',Georgia,serif;font-size:clamp(2.5rem,5vw,4.6rem);
 line-height:1.12;letter-spacing:-.035em;margin:17px 0 12px;font-weight:700;}
.hero h1 em {color:#eacb8c;font-style:normal;}
.hero p {color:#e1eee4;font-size:1.03rem;max-width:570px;margin:0 0 15px;}
.hero-mini {color:#d5bd86;font-weight:800;font-size:.76rem;letter-spacing:.06em;}
.shanyraq-wrap {display:flex;justify-content:center;align-items:center;max-width:340px;margin:auto;
 filter:drop-shadow(0 12px 24px #061d1848);animation:float 7s ease-in-out infinite;}
.shanyraq-svg {width:100%;max-width:320px;}
.hero-decoration { position:absolute; width:270px; right:8px; top:0px; z-index:1; opacity:.22; pointer-events:none; }
@keyframes float {0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
.ornament-line {height:12px;margin:14px auto 21px;background:repeating-linear-gradient(90deg,
 #b89c67 0px,#b89c67 4px,transparent 4px,transparent 16px,#217468 16px,#217468 20px,transparent 20px,transparent 32px);
 opacity:.4;border-radius:99px;}
.section-eyebrow {font-size:.72rem;font-weight:800;letter-spacing:.18em;color:#987740;text-transform:uppercase;}
.section-title {font-family:'Playfair Display',Georgia,serif;font-weight:700;color:#163e36;
 font-size:clamp(1.55rem,2.7vw,2.3rem);margin:6px 0;}
.section-sub {color:#788379;font-size:.91rem;margin-bottom:16px;}
.activity-row {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:12px 0 24px;}
.activity-card {background:#fffef9;border:1px solid #e5e2d7;border-radius:20px;padding:19px;
 min-height:150px;box-shadow:0 7px 20px #183c2b08;}
.activity-card .ico {display:inline-flex;width:43px;height:43px;justify-content:center;align-items:center;
 border-radius:13px;background:#eef3ec;font-size:1.42rem;margin-bottom:13px;}
.activity-card .label {font-weight:800;color:#244a41;font-size:.94rem;line-height:1.3;}
.activity-card .mini {margin-top:6px;font-size:.77rem;color:#7b867b;}
.qr-card {background:#ffffff;border:1px solid #e4e0d3;border-radius:23px;padding:14px 14px 10px;
 box-shadow:0 12px 28px #123f3212;text-align:center;}
.qr-note {font-weight:800;color:#234d42;font-size:.9rem;margin:2px 0;}
.qr-muted {color:#6b8277;font-size:.76rem;}
.task-header {background:#e8efe7;border:1px solid #dae5d6;border-radius:20px;padding:22px;
 margin:12px 0 20px;}
.task-header .over {font-size:.73rem;letter-spacing:.13em;font-weight:800;color:#578578;}
.task-header h3 {font-family:'Playfair Display',Georgia,serif;font-size:1.75rem;margin:8px 0;color:#173e37;}
.task-header p {color:#36544c;font-size:1.04rem;margin:4px 0 12px;}
.task-header small {color:#729185;font-weight:700;}
.note-card {background:#fffefa;border:1px solid #e5e0d4;padding:22px;border-radius:20px;
 box-shadow:0 8px 22px #123f3210;margin-bottom:18px;}
.note-label {color:#b08845;font-size:.72rem;font-weight:800;letter-spacing:.14em;}
.note-content {color:#395a4f;font-size:.93rem;line-height:1.8;margin-top:9px;}
.note-secondary {color:#849188;font-size:.81rem;margin-top:14px;}
.wall-head {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:16px 0;}
.live-pill {display:inline-flex;align-items:center;gap:7px;border:1px solid #a9d8c6;
 color:#196f57;background:#e5f3e9;padding:8px 12px;border-radius:99px;font-size:.76rem;font-weight:800;}
.live-dot {width:8px;height:8px;background:#22a57b;border-radius:50%;box-shadow:0 0 0 5px #22a57b1a;
 animation:pulse 2.4s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.wall-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:15px;margin:18px 0;}
.response-card {background:#fffefa;border-radius:20px;border:1px solid #e7e2d4;
 border-top:4px solid #c8a367;padding:20px 20px 18px;box-shadow:0 9px 26px #1c3b2b10;
 min-height:176px;overflow-wrap:anywhere;transition:transform .2s,box-shadow .2s;}
.response-card:hover{transform:translateY(-3px);box-shadow:0 14px 30px #1c3b2b18;}
.response-card.design{border-top-color:#1a8b7b;}
.response-card.reflection{border-top-color:#c5aa65;}
.response-card.fresh{animation:reveal .75s cubic-bezier(.18,.8,.32,1) both;}
@keyframes reveal{from{opacity:0;transform:translateY(16px) scale(.975)}to{opacity:1;transform:translateY(0) scale(1)}}
.card-top{display:flex;gap:10px;align-items:center;min-width:0;}
.avatar{width:39px;height:39px;flex:0 0 39px;border-radius:13px;display:flex;align-items:center;
 justify-content:center;background:#e8f0e7;font-weight:800;color:#176d58;font-size:1.15rem;}
.card-name{font-size:.93rem;color:#194639;font-weight:800;overflow-wrap:anywhere;}
.card-activity{color:#869187;font-size:.69rem;font-weight:700;margin-top:3px;}
.card-text{font-size:1rem;color:#335348;line-height:1.75;white-space:pre-wrap;margin:18px 0;}
.card-foot{display:flex;align-items:center;justify-content:space-between;
 font-size:.72rem;color:#879589;border-top:1px solid #eee9df;padding-top:11px;}
.empty{background:#fffef8;border:2px dashed #dfdfcc;border-radius:20px;
 padding:58px 24px;text-align:center;color:#668073;font-size:1rem;}
.empty strong{color:#1e5348;display:block;font-size:1.23rem;margin-bottom:8px;}
.bottom-note{text-align:center;margin:38px 0 4px;font-size:.72rem;color:#8c988e;font-weight:700;}
@media(max-width:760px){.block-container{padding:1rem .75rem 2rem;}
 .hero{padding:24px 21px;min-height:unset}.hero h1{font-size:2.45rem}.activity-row{grid-template-columns:1fr;gap:9px;}
 .activity-card{min-height:unset;padding:15px;}.activity-card .ico{margin:0 9px 0 0;vertical-align:middle;}
 .shanyraq-wrap{max-width:230px}.hero-decoration{width:165px;opacity:.12;right:-35px;top:25px}.wall-grid{grid-template-columns:1fr}.brandline .crumb{display:none;}}
</style>
"""


def brandline(section: str):
    st.markdown(
        f'<div class="brandline"><span class="brand">◈ ШАҢЫРАҚҚА ОЙ ҚОС!</span>'
        f'<span class="crumb">ҚАЗАҚ ТІЛІ · КИІЗ ҮЙ · ДИЗАЙН &nbsp; / &nbsp; {esc(section)}</span></div>',
        unsafe_allow_html=True,
    )


def activities_html():
    cards = []
    details = {
        "punctuation": "Тырнақша · жақша · нүктелі үтір",
        "design": "Ұлттық нақыштағы жаңа идея",
        "reflection": "Сабақтан алған әсерің",
    }
    for key, act in ACTIVITIES.items():
        cards.append(
            '<div class="activity-card">'
            f'<span class="ico">{act["emoji"]}</span>'
            f'<div class="label">{esc(act["title"])}</div>'
            f'<div class="mini">{esc(details[key])}</div></div>'
        )
    return '<div class="activity-row">' + "".join(cards) + '</div>'


def card_markup(row, fresh=False):
    key = row["activity"]
    act = ACTIVITIES.get(key, ACTIVITIES["reflection"])
    raw_name = row["student_name"]
    name = esc(raw_name)
    letter = esc(raw_name[:1].upper()) if raw_name else "✦"
    message = esc(row["message"])
    try:
        time_str = datetime.fromisoformat(row["created_at"]).astimezone(ALMATY).strftime("%H:%M")
    except (ValueError, TypeError):
        time_str = ""
    cls = "response-card " + (key if key in ACTIVITIES else "") + (" fresh" if fresh else "")
    return (
        f'<article class="{cls}">'
        '<div class="card-top">'
        f'<span class="avatar">{letter}</span>'
        f'<div><div class="card-name">{name}</div>'
        f'<div class="card-activity">{act["emoji"]} {esc(act["title"])}</div></div></div>'
        f'<div class="card-text">{message}</div>'
        f'<div class="card-foot"><span>✦ ОҚУШЫ ПІКІРІ</span><span>{time_str}</span></div>'
        '</article>'
    )


def base_urls():
    base = st.context.url.split("?", 1)[0].rstrip("/") + "/"
    return base, base + "?view=student", base + "?view=admin"


def wall_page(student_url: str):
    brandline("ОРТАҚ ЭКРАН")
    left, right = st.columns([3.9, 1.25], gap="medium", vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="hero"><div class="hero-content">'
            '<span class="eyebrow">✦ ҰЛТТЫҚ МҰРА · ИНТЕРАКТИВТІ САБАҚ</span>'
            '<h1>Шаңыраққа <em>ой қос!</em> 🏡</h1>'
            '<p>Киіз үй – ғажап сәулет туындысы. Дизайн өнерінің даму тарихы. '
            'Тырнақша, жақша, нүктелі үтір.</p>'
            '<div class="hero-mini">☀ ӨЗ ОЙЫҢДЫ БӨЛІС · ЖАҢА ИДЕЯ ҰСЫН · БІЛІМІҢДІ БЕКІТ</div>'
            '</div><div class="hero-decoration">' + shanyrak_svg() + '</div></div>', unsafe_allow_html=True,
        )
    with right:
        st.markdown('<div class="qr-note">📱 Оқушыларға арналған QR</div>', unsafe_allow_html=True)
        st.image(qr_png(student_url), width=255)
        st.markdown('<div class="qr-muted">Сканерле де, өз ойыңды жаз!</div>', unsafe_allow_html=True)
        st.link_button("✍️ Жауап жазу", student_url, use_container_width=True)
    st.markdown('<div class="ornament-line"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-eyebrow">БІЗДІҢ ҮШ ТАПСЫРМАМЫЗ</div>', unsafe_allow_html=True)
    st.markdown(activities_html(), unsafe_allow_html=True)
    st.markdown('<div class="section-eyebrow">LIVE · ПІКІРЛЕР ҚАБЫРҒАСЫ</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Әр ой — бір жаңа өрнек ✨</div>', unsafe_allow_html=True)
    selected = st.radio(
        "Жауаптарды сүзгілеу",
        ["all", *STAGES],
        format_func=lambda k: "🌿 Барлығы" if k == "all" else f'{ACTIVITIES[k]["emoji"]} {ACTIVITIES[k]["title"]}',
        horizontal=True,
    )

    @st.fragment(run_every="2s")
    def live_wall():
        items = list_responses(selected)
        counts = response_counts()
        total = sum(counts.values())
        st.markdown(
            f'<div class="wall-head"><span style="color:#798a7c;font-weight:700;font-size:.86rem">'
            f'Жалпы жауап саны: <b style="color:#1b594d">{total}</b>'
            '</span><span class="live-pill"><i class="live-dot"></i> ТІКЕЛЕЙ ЭФИР · 2 СЕК</span></div>',
            unsafe_allow_html=True,
        )
        prior = st.session_state.get("known_wall_ids")
        ids = {row["id"] for row in items}
        # First page load shows existing cards without marking all as "new".
        added = ids - prior if prior is not None else set()
        st.session_state["known_wall_ids"] = ids
        if not items:
            st.markdown('<div class="empty">🏡<strong>Алғашқы ойды бірге бастайық!</strong>'
                        'QR-кодты сканерлеп, бірінші пікірді қалдыр.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="wall-grid">' + "".join(
                card_markup(item, fresh=(item["id"] in added)) for item in items
            ) + '</div>', unsafe_allow_html=True)
            if total > len(items) and selected == "all":
                st.caption(f"Соңғы {len(items)} пікір көрсетілген. Барлық пікірді мұғалім CSV арқылы жүктей алады.")

    live_wall()
    st.markdown('<div class="bottom-note">✦ БІР ШАҢЫРАҚ АСТЫНДА — МЫҢ ИДЕЯ ✦</div>', unsafe_allow_html=True)


def student_page(wall_url: str):
    brandline("ОҚУШЫ ПАРАҒЫ")
    st.markdown(
        '<div class="hero"><div class="hero-content">'
        '<span class="eyebrow">🌿 СӘЛЕМ, ЖАС ЖАСАМПАЗ!</span>'
        '<h1>Ойыңды <em>ортаға сал!</em> ✨</h1>'
        '<p>Өз атыңды жаз, қызық тапсырманы таңда және сыныппен бір ойыңды бөліс.</p>'
        '<div class="hero-mini">🏡 КИІЗ ҮЙ · ✍️ ТІЛ МӘДЕНИЕТІ · 🎨 ДИЗАЙН</div>'
        '</div><div class="hero-decoration">' + shanyrak_svg() + '</div></div>', unsafe_allow_html=True,
    )
    st.markdown('<div class="ornament-line"></div>', unsafe_allow_html=True)
    left, right = st.columns([1.8, 1.0], gap="large")
    with left:
        st.markdown('<div class="section-eyebrow">ҚАДАМ 01 · ӨЗІҢДІ ТАНЫСТЫР</div>', unsafe_allow_html=True)
        name = st.text_input("👤 Атың / есімің", placeholder="Мысалы: Айдана", max_chars=40, key="student_name")
        st.markdown('<div class="section-eyebrow">ҚАДАМ 02 · ТАПСЫРМАНЫ ТАҢДА</div>', unsafe_allow_html=True)
        if "selected_activity" not in st.session_state:
            st.session_state.selected_activity = get_stage()
        stage = st.radio(
            "Үш тапсырманың бірін таңда:", STAGES,
            format_func=lambda k: f'{ACTIVITIES[k]["emoji"]} {ACTIVITIES[k]["title"]}',
            key="selected_activity",
        )
        act = ACTIVITIES[stage]
        st.markdown(
            '<div class="task-header">'
            f'<div class="over">{esc(act["tag"])}</div>'
            f'<h3>{act["emoji"]} {esc(act["title"])}</h3>'
            f'<p>{esc(act["prompt"])}</p>'
            f'<small>💡 {esc(act["hint"])}</small>'
            '</div>', unsafe_allow_html=True,
        )
        with st.form("reply_form", clear_on_submit=True):
            response = st.text_area(
                "✍️ Өз жауабыңды жаз:",
                placeholder=act["placeholder"], max_chars=400, height=155,
            )
            submit = st.form_submit_button("🌟 Жауабымды жіберу", type="primary", use_container_width=True)
        if submit:
            clean_name = " ".join(name.split())
            clean_response = response.strip()
            if len(clean_name) < 2:
                st.warning("👤 Алдымен атыңды жаз (кемінде 2 таңба).")
            elif len(clean_response) < 3:
                st.warning("✍️ Жауабыңды толық жазып көр.")
            elif stage == "punctuation" and not has_required_punctuation(clean_response):
                st.warning('Сөйлемде «тырнақша», (жақша) немесе нүктелі үтірді (;) қолданып көр.')
            else:
                try:
                    add_response(clean_name, stage, clean_response)
                    st.success(f"🎉 Жарайсың, {clean_name}! Жауабың экранға шықты!")
                    st.balloons()
                except (sqlite3.Error, ValueError):
                    st.error("Сақтау кезінде мәселе шықты. Қайта жіберіп көр.")
        st.link_button("👀 Барлық жауаптарды көру", wall_url, use_container_width=True)
    with right:
        st.markdown('<div class="note-card"><div class="note-label">✦ СӨЙЛЕМ ҮЛГІСІ</div>'
                    '<div class="note-content">' + esc(act["example"]) + '</div>'
                    '<div class="note-secondary">Мысалды көшірмей, өз ойыңды жазуға тырыс 😊</div>'
                    '</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="note-card"><div class="note-label">📚 САБАҚ ТАҚЫРЫПТАРЫ</div>'
            '<div class="note-content">🏡 Киіз үй – ғажап сәулет туындысы<br>'
            '🎨 Дизайн өнерінің даму тарихы<br>'
            '✍️ Тырнақша · Жақша · Нүктелі үтір</div>'
            '</div>', unsafe_allow_html=True,
        )
    st.markdown('<div class="bottom-note">✦ СЕНІҢ ОЙЫҢ — ШАҢЫРАҚТАҒЫ БІР ӨРНЕК ✦</div>', unsafe_allow_html=True)


def admin_password():
    # Never commit secrets.toml into GitHub. Configured in Streamlit Cloud Secrets.
    try:
        return str(st.secrets["ADMIN_PASSWORD"]).strip()
    except (KeyError, FileNotFoundError):
        return os.environ.get("ADMIN_PASSWORD", "").strip()


def admin_page(wall_url: str):
    brandline("МҰҒАЛІМ ПАНЕЛІ")
    st.markdown('<div class="section-eyebrow">🔒 ТЕК МҰҒАЛІМ ҮШІН</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Сабақты басқару</div>', unsafe_allow_html=True)
    password = admin_password()
    if not password:
        st.warning("Әкімші құпиясөзі орнатылмаған. Streamlit Cloud → App settings → Secrets бөлімінде ADMIN_PASSWORD орнатыңыз.")
        st.code('ADMIN_PASSWORD = "өз-күрделі-құпиясөзіңіз"', language="toml")
        return

    if not st.session_state.get("admin_logged_in", False):
        with st.form("admin_signin"):
            entered = st.text_input("Құпиясөз", type="password")
            go = st.form_submit_button("🔓 Кіру", type="primary")
        if go:
            if hmac.compare_digest(entered, password):
                st.session_state["admin_logged_in"] = True
                st.rerun()
            else:
                st.error("Құпиясөз қате.")
        return

    if st.button("🔒 Шығу", key="admin_logout"):
        st.session_state["admin_logged_in"] = False
        st.rerun()

    counts = response_counts()
    cols = st.columns(4)
    cols[0].metric("🌿 Барлығы", sum(counts.values()))
    for i, key in enumerate(STAGES):
        cols[i + 1].metric(f'{ACTIVITIES[key]["emoji"]} {ACTIVITIES[key]["title"]}', counts[key])
    st.divider()
    st.subheader("🎛️ Сабақтың ағымдағы тапсырмасы")
    st.caption("Бұл тапсырма оқушы алғаш кіргенде алдын ала таңдалып тұрады. Оқушылар басқа тапсырманы да таңдай алады.")
    current = get_stage()
    choice = st.selectbox("Тапсырма", STAGES, index=STAGES.index(current),
                          format_func=lambda k: f'{ACTIVITIES[k]["emoji"]} {ACTIVITIES[k]["title"]}')
    if st.button("✅ Ағымдағы тапсырманы орнату", use_container_width=True):
        set_stage(choice)
        st.success("Ағымдағы тапсырма орнатылды!")

    st.divider()
    st.subheader("📥 Жауаптарды сақтау")
    all_items = list_responses(limit=100_000)
    st.download_button(
        "⬇️ Барлық жауапты CSV түрінде жүктеу",
        data=export_csv(all_items), file_name="shanyraq_zhauaptar.csv",
        mime="text/csv", use_container_width=True,
        disabled=not all_items,
    )
    st.caption("CSV файлын Excel арқылы аша аласыз. Ішінде оқушы аты, тапсырма және жауап сақталады.")

    st.divider()
    st.subheader("🧹 Жауаптарды басқару")
    if not all_items:
        st.info("Әзірге жауап жоқ.")
    else:
        options = [row["id"] for row in all_items]
        lookup = {row["id"]: row for row in all_items}
        item_id = st.selectbox("Бір жауапты таңдаңыз", options,
            format_func=lambda v: f'#{v} · {lookup[v]["student_name"]} · {lookup[v]["message"][:55]}')
        if st.button("🗑️ Таңдалған жауапты өшіру"):
            delete_response(item_id)
            st.rerun()
        st.markdown("**Бір бөлімді немесе барлық жауаптарды тазалау**")
        clean_stage = st.selectbox("Қай бөлім?", ["all", *STAGES],
            format_func=lambda k: "🌿 Барлық жауаптар" if k == "all" else f'{ACTIVITIES[k]["emoji"]} {ACTIVITIES[k]["title"]}')
        confirm = st.checkbox("Өшіруді растаймын. Бұл әрекетті қайтару мүмкін емес.")
        if st.button("🧹 Таңдалған бөлімді тазалау", disabled=not confirm):
            clear_responses(clean_stage)
            st.rerun()

    st.link_button("↗ Ортақ экранға өту", wall_url)


def main():
    init_db()
    st.markdown(CSS, unsafe_allow_html=True)
    wall_url, student_url, _ = base_urls()
    view = st.query_params.get("view", "wall")
    if view == "student":
        student_page(wall_url)
    elif view == "admin":
        admin_page(wall_url)
    else:
        wall_page(student_url)


if __name__ == "__main__":
    main()
