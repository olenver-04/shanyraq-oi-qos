"""Шаңыраққа ой қос! — интерактивный кластер для урока казахского языка.

Deploy to Streamlit Community Cloud with app.py and requirements.txt.
Set ADMIN_PASSWORD in Streamlit App settings -> Secrets (never in GitHub).
"""

from __future__ import annotations

import csv
import hmac
import html
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path

import qrcode
import streamlit as st

st.set_page_config(
    page_title="Шаңыраққа ой қос! · Білім кластері",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_PATH = Path(__file__).with_name("shanyraq_responses.db")
TOPICS = {
    "reflection": {
        "title": "Киіз үй · мұра",
        "emoji": "🏡",
        "question": "Киіз үйді бір сөзбен қалай сипаттайсың?",
        "examples": "Шаңырақ, бірлік, дәстүр, мұра, кереге...",
        "color": "#AC7943",
        "pale": "#FFF2DE",
    },
    "design": {
        "title": "Дизайн өнері",
        "emoji": "🎨",
        "question": "Киіз үй дизайнына қандай идея қосар едің?",
        "examples": "Ою-өрнек, табиғи материал, жылы жарық...",
        "color": "#277B70",
        "pale": "#E7F3ED",
    },
    "punctuation": {
        "title": "Тыныс белгілері",
        "emoji": "✍️",
        "question": "Бүгін қандай тыныс белгісін есте сақтадың?",
        "examples": "Тырнақша «», жақша (), нүктелі үтір ;",
        "color": "#80669B",
        "pale": "#F0ECF8",
    },
}
DISPLAY_LIMIT = 40


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    # Compatible with the original «Шаңыраққа ой қос!» responses table.
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            activity TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")


def add_response(name: str, topic: str, word: str):
    name = " ".join(name.split())
    word = " ".join(word.split())
    if topic not in TOPICS:
        raise ValueError("Unknown topic")
    if not (2 <= len(name) <= 40 and 2 <= len(word) <= 42):
        raise ValueError("Invalid input length")
    with db() as conn:
        conn.execute(
            "INSERT INTO responses(student_name, activity, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, topic, word, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def list_responses(topic: str = "all", limit: int = 100000):
    if topic != "all" and topic not in TOPICS:
        raise ValueError("Unknown topic")
    with db() as conn:
        if topic == "all":
            return conn.execute(
                "SELECT * FROM responses ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM responses WHERE activity=? ORDER BY id DESC LIMIT ?",
            (topic, limit),
        ).fetchall()


def topic_counts():
    counts = {key: 0 for key in TOPICS}
    with db() as conn:
        for r in conn.execute("SELECT activity, COUNT(*) AS n FROM responses GROUP BY activity"):
            if r["activity"] in counts:
                counts[r["activity"]] = r["n"]
    return counts


def delete_response(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM responses WHERE id=?", (item_id,))


def clear_responses(topic: str):
    if topic != "all" and topic not in TOPICS:
        raise ValueError("Unknown topic")
    with db() as conn:
        if topic == "all":
            conn.execute("DELETE FROM responses")
        else:
            conn.execute("DELETE FROM responses WHERE activity=?", (topic,))


def csv_safe(value: str):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_csv(rows):
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["№", "Оқушының аты", "Негізгі сөз / ой", "Уақыты (UTC)"])
    for item in rows:
        writer.writerow([
            item["id"], csv_safe(item["student_name"]),
            csv_safe(item["message"]), item["created_at"],
        ])
    return out.getvalue().encode("utf-8-sig")


def escaped(value):
    return html.escape(str(value), quote=True)


def qr_image(url):
    qr = qrcode.QRCode(box_size=12, border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="#184A40", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def public_urls():
    base = st.context.url.split("?", 1)[0].rstrip("/") + "/"
    return base, base + "?view=student", base + "?view=admin"


def shanyrak_svg(cx=700, cy=435):
    """Draw a lightweight vector shanyrak that stays sharp on the projector."""
    rays = []
    for a in range(0, 360, 22):
        radians = math.radians(a)
        x1, y1 = cx + 83 * math.cos(radians), cy + 83 * math.sin(radians)
        x2, y2 = cx + 115 * math.cos(radians), cy + 115 * math.sin(radians)
        rays.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            'stroke="#D6A559" stroke-width="7" stroke-linecap="round"/>'
        )
    lines = []
    # Interlaced wood lattice, clipped to the interior circle.
    for d in (-42, -14, 14, 42):
        lines.append(f'<line x1="{cx+d}" y1="{cy-77}" x2="{cx+d}" y2="{cy+77}"/>')
        lines.append(f'<line x1="{cx-77}" y1="{cy+d}" x2="{cx+77}" y2="{cy+d}"/>')
    return f'''
    <defs>
      <radialGradient id="shglow"><stop stop-color="#E6C57D" stop-opacity=".32"/>
        <stop offset="1" stop-color="#E6C57D" stop-opacity="0"/></radialGradient>
      <clipPath id="shclip"><circle cx="{cx}" cy="{cy}" r="75"/></clipPath>
    </defs>
    <circle cx="{cx}" cy="{cy}" r="142" fill="url(#shglow)" />
    <circle cx="{cx}" cy="{cy}" r="119" fill="#FAF4E5" stroke="#C69245" stroke-width="11"/>
    <circle cx="{cx}" cy="{cy}" r="107" fill="none" stroke="#E5CA96" stroke-width="3"/>
    {''.join(rays)}
    <circle cx="{cx}" cy="{cy}" r="81" fill="#24594B" stroke="#D6A559" stroke-width="8"/>
    <g clip-path="url(#shclip)" stroke="#E9CF96" stroke-width="10" stroke-linecap="round">
    {''.join(lines)}</g>
    <circle cx="{cx}" cy="{cy}" r="78" fill="none" stroke="#EBD6AD" stroke-width="4"/>
    <circle cx="{cx}" cy="{cy}" r="8" fill="#FFF3D1"/>
    '''


def ray_slots():
    """Forty carefully spaced positions on three concentric rings around the yurt roof.

    Each response sits on the end of a visible uyk-style wooden spoke.  These
    coordinates keep labels legible on a 16:10 classroom projector.
    """
    cx, cy = 800, 505
    rings = (
        (10, 286, 255, math.radians(144.2)),
        (14, 440, 352, math.radians(193.1)),
        (16, 613, 442, math.radians(65.3)),
    )
    slots = []
    for count, radius_x, radius_y, phase in rings:
        for idx in range(count):
            angle = phase + 2 * math.pi * idx / count
            dx = radius_x * math.cos(angle)
            dy = radius_y * math.sin(angle)
            slots.append((cx + dx, cy + dy, angle))
    return slots


def cluster_svg(rows, fresh_ids: set[int]):
    """Draw one radiating branch per student, each with a name and a word."""
    width, height, cx, cy = 1600, 1010, 800, 505
    slots = ray_slots()
    chronological = list(reversed(list(rows)))[:DISPLAY_LIMIT]
    rays, labels, ornaments = [], [], []
    palette = (
        ('#BF8D4C', '#FFF6E3'),
        ('#34856C', '#E8F5EC'),
        ('#9972A2', '#F7EEFA'),
        ('#BD7664', '#FFF0E9'),
        ('#5A809F', '#EAF3FC'),
    )

    for item, (x, y, angle) in zip(chronological, slots):
        item_id = int(item['id'])
        word = ' '.join(item['message'].split())
        name = ' '.join(item['student_name'].split())
        shown_word = word if len(word) <= 18 else word[:17].rstrip() + '…'
        shown_name = name if len(name) <= 20 else name[:19].rstrip() + '…'
        accent, paper = palette[(item_id - 1) % len(palette)]
        is_new = item_id in fresh_ids
        css_fresh = ' fresh' if is_new else ''

        # Gold uyk/ray: start at the outer edge of the center shanyrak.
        vx, vy = x - cx, y - cy
        distance = math.hypot(vx, vy)
        ux, uy = vx / distance, vy / distance
        start_x, start_y = cx + ux * 132, cy + uy * 132
        # End behind the word so the card appears physically attached to the ray.
        end_x, end_y = x - ux * 22, y - uy * 22
        tooltip = escaped(f'{name} — {word}')
        rays.append(
            f'<g class="ray{css_fresh}">'
            f'<line x1="{start_x:.1f}" y1="{start_y:.1f}" '
            f'x2="{end_x:.1f}" y2="{end_y:.1f}" '
            'stroke="#B17C38" stroke-width="7" stroke-linecap="round" opacity=".58"/>'
            f'<line x1="{start_x:.1f}" y1="{start_y:.1f}" '
            f'x2="{end_x:.1f}" y2="{end_y:.1f}" '
            'stroke="#F6DDB0" stroke-width="2.5" stroke-linecap="round" opacity=".85"/>'
            '</g>'
        )
        # Individual tags show the word ON the end of its ray (not floating nearby).
        labels.append(
            f'<g class="word-petal{css_fresh}" transform="translate({x:.1f} {y:.1f})" '
            'role="group" tabindex="0">'
            f'<title>{tooltip}</title>'
            '<rect x="-87" y="-34" width="174" height="68" rx="23" '
            f'fill="{paper}" stroke="{accent}" stroke-width="2.1"/>'
            f'<path d="M-60,-34 Q0,-47 60,-34" fill="none" stroke="{accent}" '
            'stroke-width="2.1" opacity=".6"/>'
            f'<circle cx="-69" cy="-19" r="4" fill="{accent}"/>'
            f'<circle cx="69" cy="-19" r="4" fill="{accent}"/>'
            f'<text class="branch-word" x="0" y="-2" text-anchor="middle" '
            f'fill="#204D40" textLength="{min(150, max(1,len(shown_word))*9.7):.0f}" '
            f'lengthAdjust="spacingAndGlyphs">{escaped(shown_word)}</text>'
            f'<text class="branch-name" x="0" y="22" text-anchor="middle" '
            f'fill="{accent}">{escaped(shown_name)}</text>'
            '</g>'
        )

    # Repeat small national motifs in the corners; do not obscure the branches.
    for px, py in ((65, 70), (1535, 70), (65, 940), (1535, 940)):
        ornaments.append(
            f'<g opacity=".40" transform="translate({px} {py})" fill="none" '
            'stroke="#B68B4B" stroke-width="3">'
            '<path d="M-17 0 Q-17 -17 0 -17 Q17 -17 17 0 Q17 17 0 17 Q-9 17 -9 7"/>'
            '<circle r="4" fill="#B68B4B" stroke="none"/></g>'
        )

    label = f'{len(chronological)} оқушының ойы' if chronological else 'Жауаптар әлі жоқ'
    return (
        '<div class="cluster-holder">'
        f'<svg class="cluster-canvas" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escaped(label)}">'
        '<defs>'
        '<radialGradient id="warm-paper"><stop stop-color="#FFFFFF"/>'
        '<stop offset="1" stop-color="#FBF5E8"/></radialGradient>'
        '<pattern id="soft-dots" width="50" height="50" patternUnits="userSpaceOnUse">'
        '<circle cx="4" cy="4" r="1.1" fill="#D5C3A0" opacity=".38"/></pattern>'
        '</defs>'
        '<rect x="0" y="0" width="1600" height="1010" rx="30" fill="url(#warm-paper)"/>'
        '<rect x="0" y="0" width="1600" height="1010" rx="30" fill="url(#soft-dots)"/>'
        '<ellipse cx="800" cy="505" rx="630" ry="451" fill="none" '
        'stroke="#D9C29A" stroke-width="1.5" stroke-dasharray="2 14" opacity=".5"/>'
        '<ellipse cx="800" cy="505" rx="450" ry="358" fill="none" '
        'stroke="#D9C29A" stroke-dasharray="2 13" opacity=".4"/>'
        + ''.join(ornaments)
        + ''.join(rays)
        + shanyrak_svg(cx, cy)
        + ''.join(labels)
        + '</svg></div>'
    )


CSS = r'''
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700;800&family=Noto+Serif:wght@500;600;700;800&display=swap');
:root {--ink:#1B4A3C;--gold:#C69852;--sans:'Noto Sans','DejaVu Sans',sans-serif;--serif:'Noto Serif','DejaVu Serif',serif;}
.stApp {background:radial-gradient(ellipse 600px 420px at 90% 0%,#E9DAC040,transparent),#F8F5ED;color:var(--ink);font-family:var(--sans);}
html,body,[data-testid="stMarkdownContainer"], .stApp input, .stApp textarea,.stApp button {font-family:var(--sans);}
.block-container {max-width:1400px;padding-top:1rem;padding-bottom:3rem;}
[data-testid="stHeader"]{background:transparent} #MainMenu,footer{visibility:hidden}
.brand {font-family:var(--serif);font-weight:800;font-size:1.15rem;color:#276352;margin-bottom:16px}
.eyebrow {font-size:.76rem;letter-spacing:.13em;font-weight:800;color:#F4D5A4}
.hero {position:relative;overflow:hidden;background:linear-gradient(115deg,#154437,#275D4C 68%,#3C7961);color:#fffaf0;border-radius:28px;padding:33px 37px;min-height:230px;box-shadow:0 16px 35px #133C3020;}
.hero::after{content:'✦';position:absolute;font-size:16rem;color:#E6CB9430;right:35px;top:-85px;pointer-events:none}
.hero h1 {position:relative;z-index:1;font-family:var(--serif);font-weight:800;font-size:clamp(2rem,4.3vw,3.8rem);line-height:1.27;color:#fff9ec;margin:9px 0 12px}
.hero h1 em{color:#F3D49B;font-style:normal}
.hero p {font-size:1rem;color:#E6F1E8;line-height:1.8;max-width:810px;margin:0}
.kicker {font-size:.78rem;font-weight:800;letter-spacing:.085em;color:#A77336;margin-top:23px}
.section-title{font-family:var(--serif);font-size:clamp(1.6rem,2.3vw,2.35rem);font-weight:700;color:#174C3E;line-height:1.4;margin:4px 0 8px}
.secondary-text {color:#587266;font-size:.97rem;line-height:1.8}
.qr-wrap{text-align:center;padding:17px 8px;background:#fffefa;border:1px solid #E3DDCE;border-radius:24px;}
.qr-head{font-weight:800;color:#2B6752;font-size:1rem;text-align:center;line-height:1.6}
.topic-strip {display:flex;flex-wrap:wrap;gap:10px;padding:6px 0 12px}
.topic-chip{border:1px solid #DADDCB;border-radius:999px;background:#FFFEF9;padding:8px 13px;color:#285849;font-size:.87rem;font-weight:700}
 .cluster-holder {width:100%;border:1px solid #E5DAC4;border-radius:28px;overflow:hidden;box-shadow:0 18px 38px #1C49371A;background:#FFFEF8}
.cluster-canvas{display:block;width:100%;height:auto;max-height:80vh;min-height:430px}
.branch-word{font-family:var(--sans);font-size:20px;font-weight:800;letter-spacing:-.015em}
.branch-name{font-family:var(--sans);font-size:13px;font-weight:800}
.center-caption{font-family:var(--sans);font-size:14px;font-weight:800;letter-spacing:.17em;fill:#9D7139}
.word-petal{cursor:help;outline:none;filter:drop-shadow(0 4px 6px #7B684024)}
.word-petal:hover,.word-petal:focus{filter:drop-shadow(0 5px 12px #1B4A3C66)}
.word-petal:hover rect,.word-petal:focus rect{stroke-width:3.5}
.word-petal.fresh{animation:branch-pop .85s cubic-bezier(.16,1.5,.37,1) both;transform-box:fill-box;transform-origin:center}
.ray.fresh{animation:ray-appear .9s ease-out both}
@keyframes branch-pop {0%{opacity:0;scale:.65}60%{opacity:1;scale:1.10}100%{scale:1}}
@keyframes ray-appear{0%{opacity:0}100%{opacity:1}}

.live {display:inline-flex;gap:9px;align-items:center;background:#E4F3E8;border:1px solid #BCD9C4;color:#1F6E54;border-radius:999px;padding:9px 13px;font-size:.76rem;font-weight:800;white-space:nowrap}
.live:before{content:'';width:8px;height:8px;background:#40AA7C;border-radius:50%;box-shadow:0 0 0 5px #67B69738}
.stat-line{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:12px 0}
.wall-count{font-weight:700;font-size:.94rem;color:#547064}
.wall-count b{font-size:1.15rem;color:#1B604B}
.empty-hint{background:#FFFDF5;border-radius:17px;border:1px dashed #D8CCAA;padding:13px 19px;color:#6F7157;font-size:.9rem;line-height:1.7;margin-top:10px}
.form-note{background:#EFF6ED;border:1px solid #D0E2D1;border-radius:23px;padding:22px 24px;margin:16px 0 22px;color:#265F4E;line-height:1.75}
.form-note strong{display:block;font-family:var(--serif);font-size:1.3rem;margin-bottom:6px;color:#1C513F}
[data-testid="stTextInput"] input {border:1.5px solid #CEDBCD;background:#fff;border-radius:14px;padding:10px;font-size:1.1rem;min-height:3.2rem;color:#173F33}
[data-testid="stWidgetLabel"] p{font-weight:700;color:#215544;font-size:1rem}
[data-testid="stFormSubmitButton"] button[kind="primary"],.stButton button[kind="primary"]{background:#236C57;color:white;border:0;border-radius:13px;min-height:3.2rem;font-weight:800}
.stButton button,.stDownloadButton button,.stLinkButton a{border-radius:13px;font-weight:700}
.tip{color:#5A7667;font-size:.86rem;line-height:1.7;margin:12px 0}
.footer-text{text-align:center;color:#9C7442;font-weight:800;letter-spacing:.08em;font-size:.8rem;margin:27px 0}
@media(max-width:760px){.block-container{padding:1rem .75rem 2rem}.hero{padding:24px 22px;min-height:unset;border-radius:21px}.hero h1{font-size:2.2rem}.hero::after{right:-24px;font-size:11rem}.cluster-canvas{min-height:unset;max-height:unset}.branch-word{font-size:20px}}
@media(prefers-reduced-motion:reduce){.word-petal.fresh,.ray.fresh{animation:none}}
</style>
'''


def header(title="ОРТАҚ ЭКРАН"):
    st.markdown(
        f'<div class="brand">✦ Шаңыраққа ой қос! &nbsp;·&nbsp; <span style="font-family:var(--sans);font-size:.75rem;color:#8C7655">{escaped(title)}</span></div>',
        unsafe_allow_html=True,
    )


def wall_page(student_url: str):
    header("ИНТЕРАКТИВТІ КЛАСТЕР")
    a, b = st.columns([4.5, 1.25], gap="large", vertical_alignment="center")
    with a:
        st.markdown(
            '<div class="hero"><div class="eyebrow">✦ ҚАЗАҚ ТІЛІ · ҰЛТТЫҚ МҰРА</div>'
            '<h1>Шаңыраққа <em>ой қос!</em> 🏡</h1>'
            '<p>Киіз үй – ғажап сәулет туындысы. Дизайн өнерінің даму тарихы. '
            'Тырнақша, жақша, нүктелі үтір.</p></div>',
            unsafe_allow_html=True,
        )
    with b:
        st.markdown('<div class="qr-wrap"><div class="qr-head">📱 QR-КОДТЫ СКАНЕРЛЕ</div></div>', unsafe_allow_html=True)
        st.image(qr_image(student_url), use_container_width=True)
        st.link_button("✍️ Ойымды қосу", student_url, use_container_width=True)
    st.markdown('<div class="kicker">БІЗДІҢ ОРТАҚ КЛАСТЕРІМІЗ</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Әр ой — шаңырақтың бір уығы ✨</div>', unsafe_allow_html=True)

    @st.fragment(run_every="2s")
    def live_cluster():
        latest = list_responses(limit=DISPLAY_LIMIT)
        counts = topic_counts()
        total = sum(counts.values())
        previous = st.session_state.get("previous_cluster_ids")
        ids = {int(r["id"]) for r in latest}
        fresh = ids - previous if previous is not None else set()
        st.session_state["previous_cluster_ids"] = ids
        st.markdown(
            '<div class="stat-line">'
            f'<div class="wall-count">💬 Барлық жауап: <b>{total}</b>'
            f' &nbsp; · &nbsp; Кластерде: <b>{len(latest)}</b></div>'
            '<div class="live">ЖАНДЫ ШАҢЫРАҚ · 2 СЕК</div></div>', unsafe_allow_html=True,
        )
        st.html(cluster_svg(latest, fresh))
        if total == 0:
            st.markdown('<div class="empty-hint">🌿 Шаңырақ жаңа ойларды күтіп тұр! QR-кодты сканерлеп, өз сөзіңді қос.</div>', unsafe_allow_html=True)
        if total > DISPLAY_LIMIT:
            st.caption(f"Шаңырақта соңғы {DISPLAY_LIMIT} ой көрсетіледі. Барлық {total} жауап мұғалімнің панелінде сақталады (сервер қайта іске қосылғанша).")
        with st.expander("📜 Ойларды тізім түрінде көру"):
            for r in latest:
                st.markdown(f'**🌿 {escaped(r["student_name"])}:** {escaped(r["message"])}')

    live_cluster()
    st.markdown('<div class="footer-text">✦ БІР ШАҢЫРАҚ АСТЫНДА — БІРЛІК ПЕН БІЛІМ ✦</div>', unsafe_allow_html=True)


def student_page(wall_url: str):
    header("ОҚУШЫ ПАРАҒЫ")
    st.markdown(
        '<div class="hero"><div class="eyebrow">🌿 СӘЛЕМ, ЖАС ЖАСАМПАЗ!</div>'
        '<h1>Шаңыраққа <em>өз ойыңды қос!</em></h1>'
        '<p>Бір сөз немесе қысқа тіркес жаз. Сөзің шаңырақтың бір уығына айналады!</p></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.8, 1], gap="large")
    with left:
        st.markdown('<div class="form-note"><strong>💡 Қалай қатысамын?</strong>'
                    '1. Атыңды жаз.<br>2. Сабақтан есте қалған бір сөз немесе қысқа ой жаз.<br>'
                    '3. «Шаңыраққа қосу» батырмасын бас. Сөзің шаңырақтың бір уығында пайда болады.</div>',
                    unsafe_allow_html=True)
        with st.form("cluster_form", clear_on_submit=False):
            name = st.text_input("👤 Атың", placeholder="Мысалы: Айдана", max_chars=40)
            word = st.text_input(
                "✨ Бір сөз немесе қысқа тіркес",
                placeholder="Мысалы: Бірлік, Шаңырақ, Ою-өрнек...",
                max_chars=42,
            )
            submitted = st.form_submit_button("🌟 Шаңыраққа қосу", type="primary", use_container_width=True)
        if submitted:
            try:
                # Keep the original database schema, without asking students to select a topic.
                add_response(name, "reflection", word)
            except ValueError:
                st.warning("Атыңды (кемі 2 әріп) және бір сөзіңді (2–42 таңба) дұрыс толтыр.")
            except sqlite3.Error:
                st.error("Жауапты сақтау мүмкін болмады. Қайта жіберіп көр.")
            else:
                st.success(f"🎉 Жарайсың, {name.strip()}! Ойың кластерге қосылды.")
                st.balloons()
        st.link_button("👀 Ортақ кластерді көру", wall_url, use_container_width=True)
        st.markdown('<div class="tip">🌿 Өз ойыңды жаз. Атың мен сөзің проектордан көрсетіледі.</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="kicker">ОЙЛАНУҒА КӨМЕК</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="form-note"><strong>🌿 Қандай сөз есіңде қалды?</strong>'
            'Киіз үй, ұлттық өнер, дизайн немесе тыныс белгілері туралы ойыңды жаз.'
            '<br><small>Мысалы: Шаңырақ · Бірлік · Мұра · Ою-өрнек · Тырнақша</small></div>',
            unsafe_allow_html=True,
        )


def admin_password():
    try:
        return str(st.secrets["ADMIN_PASSWORD"]).strip()
    except (KeyError, FileNotFoundError):
        return os.environ.get("ADMIN_PASSWORD", "").strip()


def admin_page(wall_url: str):
    header("МҰҒАЛІМ ПАНЕЛІ")
    st.markdown('<div class="section-title">🔒 Мұғалімнің басқару панелі</div>', unsafe_allow_html=True)
    password = admin_password()
    if not password:
        st.warning("Құпиясөз орнатылмаған. Streamlit Cloud → App settings → Secrets ішінен ADMIN_PASSWORD қосыңыз.")
        st.code('ADMIN_PASSWORD = "Өзіңіздің_күрделі_құпиясөзіңіз"', language="toml")
        return

    if not st.session_state.get("admin_authorized", False):
        with st.form("admin_login"):
            supplied = st.text_input("Құпиясөз", type="password")
            login = st.form_submit_button("🔓 Кіру", type="primary")
        if login:
            if hmac.compare_digest(supplied, password):
                st.session_state["admin_authorized"] = True
                st.rerun()
            else:
                st.error("Құпиясөз қате.")
        return

    if st.button("🔒 Шығу"):
        st.session_state["admin_authorized"] = False
        st.rerun()

    all_rows = list_responses()
    st.metric("🌿 Барлық жауап", len(all_rows))

    st.subheader("📥 Жауаптарды сақтау")
    st.download_button(
        "⬇️ Барлық жауапты CSV файлымен жүктеу",
        data=export_csv(all_rows), file_name="shanyraq_cluster_zhauaptar.csv",
        mime="text/csv", use_container_width=True, disabled=not all_rows,
    )
    st.caption("CSV ішінде оқушының аты, жазылған ойы мен уақыты бар.")

    st.divider()
    st.subheader("🗑️ Бір жауапты өшіру")
    if all_rows:
        by_id = {int(r["id"]): r for r in all_rows}
        item_id = st.selectbox(
            "Қай жауапты жоямыз?", list(by_id),
            format_func=lambda key: f'#{key} · {by_id[key]["student_name"]} · {by_id[key]["message"][:50]}',
        )
        if st.button("Таңдалған жауапты жою"):
            delete_response(int(item_id))
            st.rerun()
    else:
        st.info("Әзірге жауап жоқ.")

    st.divider()
    st.subheader("🧹 Шаңырақты тазалау")
    confirm = st.checkbox("Иә, барлық жауаптарды біржола жойғым келеді.")
    if st.button("Шаңырақты тазалау", disabled=not confirm or not all_rows):
        clear_responses("all")
        st.rerun()
    st.info("Бұл тегін Streamlit Cloud серверінде SQLite уақытша сақталады. Қайта іске қосқанда жауаптар жойылуы мүмкін: сабақ соңында CSV жүктеңіз.")
    st.link_button("↗ Ортақ экран", wall_url)


def main():
    init_db()
    st.markdown(CSS, unsafe_allow_html=True)
    wall_url, student_url, _ = public_urls()
    view = st.query_params.get("view", "wall")
    if view == "student":
        student_page(wall_url)
    elif view == "admin":
        admin_page(wall_url)
    else:
        wall_page(student_url)


if __name__ == "__main__":
    main()
