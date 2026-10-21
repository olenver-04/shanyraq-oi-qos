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
/* Қазақша Ә Ғ Қ Ң Ө Ұ Ү Һ І таңбаларын қамтитын кирилл қаріптері. */
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700;800&family=Noto+Serif:ital,wght@0,500;0,600;0,700;0,800;1,600;1,700&display=swap');
:root {
  --forest: #163F37;
  --forest-2: #235F51;
  --mint: #DBEDE5;
  --sand: #F8F5ED;
  --paper: #FFFEFA;
  --gold: #C69E58;
  --gold-light: #F6DEA8;
  --ink: #193A33;
  --ink-soft: #425D53;
  --muted: #62776D;
  --stroke: #E2E3D9;
  --body-font: 'Noto Sans', 'DejaVu Sans', Arial, sans-serif;
  --heading-font: 'Noto Serif', 'DejaVu Serif', Georgia, serif;
}
html, body, .stApp, .stApp button, .stApp input, .stApp textarea,
.stApp select, .stApp label, [class*="st-"] {
  font-family: var(--body-font);
  font-kerning: normal;
}
.stApp {
  color: var(--ink);
  background:
    radial-gradient(ellipse 900px 480px at 100% -6%, rgba(233,213,174,.35) 0%, transparent 76%),
    radial-gradient(ellipse 600px 500px at -8% 92%, rgba(196,222,205,.37) 0%, transparent 78%),
    #F8F5ED;
}
.block-container {max-width: 1340px; padding-top: 1.3rem; padding-bottom: 3.4rem;}
[data-testid="stHeader"] {background: transparent;}
#MainMenu, footer {visibility: hidden;}
[data-testid="stMarkdownContainer"] p {line-height: 1.75;}
h1,h2,h3 {font-family:var(--heading-font);color:var(--ink);line-height:1.23;}
/* Контрастная и крупная форма на телефонах. */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
  background: #FFFFFF;
  border: 1.5px solid #CAD6CB;
  border-radius: 16px;
  color: #19392F;
  font-family: var(--body-font);
  font-weight: 500;
  font-size: 1.06rem;
  line-height: 1.65;
  padding: 12px 15px;
  transition: border-color .2s, box-shadow .2s;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {color: #7A8D81;opacity:1;}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: #3D8A73;
  box-shadow: 0 0 0 3px rgba(60,138,116,.13);
}
[data-testid="stWidgetLabel"] p, [data-testid="stRadio"] label,
[data-testid="stSelectbox"] label {color:#21483E;font-size:1rem;font-weight:700;line-height:1.6;}
[data-testid="stRadio"] label p {font-size:.98rem;line-height:1.5;}
[data-testid="stFormSubmitButton"] button[kind="primary"],
.stButton button[kind="primary"] {
  border:none;
  color:#FFFEF8;
  background:linear-gradient(120deg,#20584B,#368774);
  box-shadow:0 7px 16px rgba(24,77,63,.13);
  border-radius:15px;
  font-weight:800;
  font-size:1.02rem;
  min-height:3.2rem;
  letter-spacing:.005em;
}
.stButton button, .stDownloadButton button, .stLinkButton a {
  font-family:var(--body-font);
  border-radius:14px;
  font-weight:700;
  font-size:.94rem;
  line-height:1.35;
  min-height:2.9rem;
}
/* Логотип с небольшим национальным акцентом. */
.brandline {
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  flex-wrap:wrap;
  padding:7px 0 21px;
  color:#1E5146;
  font-size:.83rem;
}
.brandline .brand {
  display:inline-flex;
  align-items:center;
  gap:9px;
  font-family:var(--heading-font);
  font-size:1.1rem;
  font-weight:700;
  letter-spacing:-.018em;
  line-height:1.45;
  color:#155043;
}
.brandline .crumb {
  color:#657E70;
  font-weight:700;
  font-size:.74rem;
  letter-spacing:.07em;
  line-height:1.7;
}
/* Большой заголовок — главный акцент на проекторе. */
.hero {
  position:relative;
  overflow:hidden;
  border-radius:30px;
  padding:41px 43px 35px;
  background:linear-gradient(112deg,#103930 0%,#205448 62%,#34725F 100%);
  color:#FFFAED;
  box-shadow:0 20px 45px rgba(14,56,45,.18);
  min-height:305px;
  isolation:isolate;
}
.hero::before {
  content:"";
  position:absolute;
  inset:0;
  opacity:.09;
  background-image:repeating-linear-gradient(135deg,transparent 0px,transparent 23px,#EDD29B 24px,transparent 25px);
  pointer-events:none;
}
.hero::after {
  content:"";
  position:absolute;
  width:420px;height:420px;
  border:1px solid rgba(243,206,137,.22);
  border-radius:50%;top:-260px;right:-38px;
  box-shadow:0 0 0 38px #F0D49A12,0 0 0 76px #F0D49A0D;
  pointer-events:none;
}
.hero-content {position:relative;z-index:2;max-width:760px;}
.eyebrow {
  display:inline-block;
  color:#FFE9BA;
  border:1px solid rgba(244,212,153,.55);
  background:rgba(255,255,255,.07);
  border-radius:100px;
  padding:8px 15px;
  font-family:var(--body-font);
  font-size:.75rem;
  font-weight:800;
  letter-spacing:.075em;
  line-height:1.45;
}
.hero h1 {
  color:#FFFCF5;
  font-family:var(--heading-font);
  font-size:clamp(2.8rem,5.2vw,4.85rem);
  line-height:1.2;
  letter-spacing:-.036em;
  font-weight:700;
  margin:19px 0 18px;
  text-wrap:balance;
  text-shadow:0 2px 12px rgba(0,0,0,.08);
}
.hero h1 em {
  color:var(--gold-light);
  font-family:var(--heading-font);
  font-style:italic;
  font-weight:700;
  text-decoration:underline;
  text-decoration-color:rgba(249,222,166,.35);
  text-decoration-thickness:2px;
  text-underline-offset:9px;
}
.hero p {
  color:#EAF2E9;
  font-family:var(--body-font);
  font-size:clamp(1.03rem,1.6vw,1.18rem);
  font-weight:500;
  line-height:1.83;
  letter-spacing:.003em;
  max-width:640px;
  margin:0 0 19px;
}
.hero-mini {
  color:#F4D6A0;
  font-weight:800;
  font-size:.77rem;
  line-height:1.7;
  letter-spacing:.035em;
}
.shanyraq-wrap {
  display:flex;
  justify-content:center;
  align-items:center;
  max-width:340px;
  margin:auto;
  filter:drop-shadow(0 12px 24px #061d1848);
  animation:float 7s ease-in-out infinite;
}
.shanyraq-svg {width:100%;max-width:320px;}
.hero-decoration {position:absolute;width:270px;right:8px;top:0;z-index:1;opacity:.24;pointer-events:none;}
@keyframes float {0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
.ornament-line {
  height:10px;
  margin:17px auto 27px;
  border-radius:99px;
  background:
    repeating-linear-gradient(90deg,
    #BC9455 0px,#BC9455 5px,transparent 5px,transparent 20px,
    #257568 20px,#257568 25px,transparent 25px,transparent 40px);
  opacity:.46;
}
.section-eyebrow {
  font-size:.79rem;
  font-weight:800;
  letter-spacing:.095em;
  line-height:1.55;
  color:#956D32;
  text-transform:uppercase;
  margin-bottom:3px;
}
.section-title {
  font-family:var(--heading-font);
  font-weight:700;
  color:#15473C;
  font-size:clamp(1.85rem,2.9vw,2.7rem);
  line-height:1.34;
  letter-spacing:-.026em;
  margin:8px 0 13px;
  text-wrap:balance;
}
.section-sub {color:#566D60;font-size:1rem;line-height:1.7;margin-bottom:19px;}
/* Три задания с крупными названиями и видимой иерархией. */
.activity-row {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin:16px 0 29px;}
.activity-card {
  position:relative;
  background:#FFFEFA;
  border:1px solid #E2E2D7;
  border-radius:22px;
  padding:22px 22px 20px;
  min-height:165px;
  box-shadow:0 9px 26px rgba(29,59,42,.055);
  overflow:hidden;
}
.activity-card::after {
  position:absolute;right:14px;bottom:-7px;
  font-family:var(--heading-font);
  font-size:4.8rem;
  font-weight:800;
  color:rgba(185,148,88,.10);
  line-height:1;
  pointer-events:none;
}
.activity-card:nth-child(1)::after{content:"01";}
.activity-card:nth-child(2)::after{content:"02";}
.activity-card:nth-child(3)::after{content:"03";}
.activity-card .ico {
  display:inline-flex;width:46px;height:46px;
  justify-content:center;align-items:center;
  border-radius:15px;background:#E5F1EA;
  font-size:1.42rem;margin-bottom:12px;
}
.activity-card .label {
  position:relative;z-index:1;
  font-family:var(--heading-font);
  font-weight:700;
  color:#21483C;
  font-size:clamp(1.04rem,1.3vw,1.22rem);
  line-height:1.5;
  letter-spacing:-.01em;
}
.activity-card .mini {position:relative;z-index:1;margin-top:8px;font-size:.86rem;color:#61776A;line-height:1.6;}
/* QR в основном экране уже крупный, здесь улучшаем подписи. */
.qr-card {background:#fff;border:1px solid #e4e0d3;border-radius:23px;padding:14px 14px 10px;
 box-shadow:0 12px 28px #123f3212;text-align:center;}
.qr-note {color:#224B40;font-size:1rem;font-weight:800;line-height:1.5;margin:3px 0 8px;}
.qr-muted {color:#506E60;font-size:.89rem;font-weight:600;line-height:1.65;margin:6px 0 8px;}
/* Форма ученика: читаемая инструкция, примеры, подсказки. */
.task-header {
  background:linear-gradient(120deg,#E8F2E8 0%,#EFF5EC 100%);
  border:1px solid #D1E2D3;
  border-radius:23px;
  padding:24px 25px 26px;
  margin:15px 0 21px;
  box-shadow:0 5px 18px rgba(27,75,53,.035);
}
.task-header .over {font-size:.76rem;line-height:1.7;letter-spacing:.055em;font-weight:800;color:#337A67;}
.task-header h3 {
  font-family:var(--heading-font);
  font-size:clamp(1.65rem,2.2vw,2.24rem);
  font-weight:700;
  line-height:1.4;
  letter-spacing:-.018em;
  margin:8px 0 13px;
  color:#15483E;
}
.task-header p {color:#264E42;font-size:1.07rem;font-weight:500;line-height:1.8;margin:4px 0 14px;}
.task-header small {color:#406D5E;font-weight:700;font-size:.92rem;line-height:1.65;}
.note-card {
  background:#FFFEFA;
  border:1px solid #E3E1D5;
  padding:24px;
  border-radius:21px;
  box-shadow:0 8px 23px #123f3210;
  margin-bottom:19px;
}
.note-label {color:#9A6F31;font-size:.77rem;font-weight:800;letter-spacing:.085em;line-height:1.6;}
.note-content {color:#284D41;font-size:1.02rem;line-height:1.85;font-weight:500;margin-top:11px;}
.note-secondary {color:#677D70;font-size:.91rem;line-height:1.6;margin-top:14px;}
/* Живая стена: крупные имена, цитаты и удобочитаемые ответы. */
.wall-head {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:20px 0 16px;}
.live-pill {display:inline-flex;align-items:center;gap:9px;border:1px solid #A6D4BF;
 color:#116247;background:#E4F3E8;padding:9px 14px;border-radius:99px;
 font-size:.79rem;letter-spacing:.03em;font-weight:800;line-height:1.45;}
.live-dot {width:8px;height:8px;background:#1D9B71;border-radius:50%;box-shadow:0 0 0 5px #22a57b1a;
 animation:pulse 2.4s ease-in-out infinite;}
@keyframes pulse {0%,100%{opacity:1}50%{opacity:.5}}
.wall-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:17px;margin:20px 0;}
.response-card {
  position:relative;
  background:#FFFEFA;
  border-radius:22px;
  border:1px solid #E5E3D8;
  border-top:4px solid #C69D62;
  padding:24px 23px 19px;
  box-shadow:0 11px 25px rgba(28,59,43,.065);
  min-height:202px;
  overflow-wrap:anywhere;
  transition:transform .2s,box-shadow .2s;
  overflow:hidden;
}
.response-card::after {
  content:'“';
  position:absolute;
  right:16px;top:55px;
  font-family:var(--heading-font);
  font-size:5.2rem;
  line-height:1;
  font-weight:700;
  color:rgba(176,143,88,.12);
  pointer-events:none;
}
.response-card:hover {transform:translateY(-3px);box-shadow:0 17px 30px rgba(28,59,43,.12);}
.response-card.design {border-top-color:#2F9280;}
.response-card.reflection {border-top-color:#D0AC69;}
.response-card.fresh {animation:reveal .75s cubic-bezier(.18,.8,.32,1) both;}
@keyframes reveal {from{opacity:0;transform:translateY(16px) scale(.975)}to{opacity:1;transform:translateY(0) scale(1)}}
.card-top {position:relative;z-index:1;display:flex;gap:12px;align-items:center;min-width:0;}
.avatar {width:44px;height:44px;flex:0 0 44px;border-radius:15px;display:flex;align-items:center;
 justify-content:center;background:#E5F2E9;font-family:var(--heading-font);
 font-weight:700;color:#1C6E59;font-size:1.28rem;}
.card-name {font-size:1.09rem;color:#194C3E;font-weight:800;line-height:1.5;overflow-wrap:anywhere;}
.card-activity {color:#667D70;font-size:.77rem;font-weight:700;margin-top:3px;line-height:1.6;}
.card-text {position:relative;z-index:1;font-family:var(--body-font);
 font-size:clamp(1.08rem,1.3vw,1.21rem);
 font-weight:500;letter-spacing:.002em;color:#253F35;line-height:1.82;
 white-space:pre-wrap;margin:21px 0 24px;}
.card-foot {display:flex;align-items:center;justify-content:space-between;gap:12px;
 font-size:.76rem;font-weight:700;color:#71867A;
 border-top:1px solid #EAE9DD;padding-top:13px;}
.empty {background:#FFFEF8;border:2px dashed #D7DDCD;border-radius:22px;
 padding:62px 24px;text-align:center;color:#526B5E;font-size:1.03rem;line-height:1.7;}
.empty strong {color:#1C5144;display:block;font-family:var(--heading-font);
 font-size:1.45rem;line-height:1.4;margin-bottom:9px;}
.bottom-note {text-align:center;margin:44px 0 7px;font-size:.83rem;letter-spacing:.045em;
 color:#668072;font-weight:800;line-height:1.7;}
/* Мобильные экраны, узкий проектор и люди с отключённой анимацией. */
@media(max-width:760px) {
  .block-container {padding:1rem .78rem 2.5rem;}
  .hero {padding:26px 23px 28px;min-height:unset;border-radius:23px;}
  .hero h1 {font-size:clamp(2.35rem,9vw,3.25rem);line-height:1.25;}
  .hero p {font-size:1rem;line-height:1.75;}
  .hero-mini {font-size:.72rem;}
  .activity-row {grid-template-columns:1fr;gap:11px;}
  .activity-card {min-height:unset;padding:17px 19px;}
  .activity-card .ico {margin:0 11px 0 0;vertical-align:middle;}
  .activity-card .label {display:inline;}
  .activity-card .mini {margin:8px 0 0;}
  .task-header {padding:21px;}
  .wall-grid {grid-template-columns:1fr;}
  .response-card {min-height:unset;}
  .brandline .crumb {display:none;}
  .hero-decoration {width:175px;opacity:.11;right:-35px;top:25px;}
  .section-title {font-size:1.92rem;}
}
@media(prefers-reduced-motion: reduce) {
  .shanyraq-wrap,.live-dot,.response-card.fresh{animation:none;}
  .response-card,.response-card:hover {transition:none;transform:none;}
}
</style>
"""


def brandline(section: str):
    st.markdown(
        f'<div class="brandline"><span class="brand">✦ Шаңыраққа ой қос!</span>'
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
            f'Жалпы жауап саны: <b style="color:#1b594d;font-size:1.16rem">{total}</b>'
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
