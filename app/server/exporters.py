"""Transcript exports: SRT, VTT, TXT, JSON, CSV, DOCX and PDF (Indic fonts embedded)."""
import csv
import io
import json
from pathlib import Path

from .config import APP_NAME, AUTHOR, WEB_DIR

FONT_DIR = WEB_DIR / "assets" / "fonts"
SPEAKER_COLOURS = ["1F5FAD", "B5402A", "2E7D32", "7B3FA0", "8C6D00", "00796B", "C2185B", "455A64"]


def ts(t: float, sep=",") -> str:
    t = max(0.0, float(t))
    h, rem = divmod(int(round(t * 1000)), 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600:d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:d}:{t % 60:02d}"


def _rows(project: dict, text_mode: str):
    names = project.get("speakers") or {}
    tr = (project.get("translation") or {}).get("texts") or []
    for i, s in enumerate(project["segments"]):
        sp = names.get(s.get("speaker") or "", s.get("speaker") or "")
        orig = s["text"]
        trans = tr[i] if i < len(tr) else ""
        if text_mode == "translation" and trans:
            text = trans
        elif text_mode == "both" and trans:
            text = f"{orig}\n{trans}"
        else:
            text = orig
        yield s, sp, text


def to_srt(p, text_mode="original", speakers=True) -> str:
    out = []
    for n, (s, sp, text) in enumerate(_rows(p, text_mode), 1):
        lab = f"[{sp}] " if speakers and sp else ""
        out.append(f"{n}\n{ts(s['start'])} --> {ts(s['end'])}\n{lab}{text}\n")
    return "\n".join(out)


def to_vtt(p, text_mode="original", speakers=True) -> str:
    out = ["WEBVTT", ""]
    for s, sp, text in _rows(p, text_mode):
        lab = f"<v {sp}>" if speakers and sp else ""
        out.append(f"{ts(s['start'], '.')} --> {ts(s['end'], '.')}\n{lab}{text}\n")
    return "\n".join(out)


def to_txt(p, text_mode="original", speakers=True, timestamps=True) -> str:
    out = []
    for s, sp, text in _rows(p, text_mode):
        pre = (f"[{clock(s['start'])}] " if timestamps else "") + (f"{sp}: " if speakers and sp else "")
        out.append(pre + text)
    return "\n".join(out) + "\n"


def to_json(p, **_) -> str:
    keep = {k: p.get(k) for k in ("name", "language", "engine", "duration", "speakers", "segments", "translation", "created")}
    return json.dumps(keep, ensure_ascii=False, indent=2)


def to_csv(p, text_mode="original", **_) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["start", "end", "speaker", "text", "confidence"])
    for s, sp, text in _rows(p, text_mode):
        w.writerow([f"{s['start']:.3f}", f"{s['end']:.3f}", sp, text, s.get("conf", "")])
    return "﻿" + buf.getvalue()  # BOM so Excel opens Indic text correctly


def to_docx(p, dst: Path, text_mode="original", speakers=True, timestamps=True) -> Path:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Nirmala UI"
    st.font.size = Pt(11)
    rpr = st.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(a), "Nirmala UI")
    doc.add_heading(p.get("name") or "Transcript", level=1)
    meta = doc.add_paragraph()
    meta.add_run(f"Language: {p.get('language') or '-'}   Engine: {p.get('engine') or '-'}   "
                 f"Duration: {clock(p.get('duration') or 0)}").italic = True
    colours = {}
    for s, sp, text in _rows(p, text_mode):
        para = doc.add_paragraph()
        if timestamps:
            r = para.add_run(f"[{clock(s['start'])}] ")
            r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        if speakers and sp:
            col = colours.setdefault(sp, SPEAKER_COLOURS[len(colours) % len(SPEAKER_COLOURS)])
            r = para.add_run(sp + ": ")
            r.bold = True
            r.font.color.rgb = RGBColor.from_string(col)
        para.add_run(text)
    doc.add_paragraph().add_run(f"Created with {APP_NAME} — {AUTHOR}").font.size = Pt(8)
    doc.save(str(dst))
    return dst


def to_pdf(p, dst: Path, text_mode="original", speakers=True, timestamps=True) -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 15)
    pdf.add_font("NotoSans", "", str(FONT_DIR / "NotoSans_400Regular.ttf"))
    pdf.add_font("NotoSans", "B", str(FONT_DIR / "NotoSans_700Bold.ttf"))
    pdf.add_font("NotoBeng", "", str(FONT_DIR / "NotoSansBengali_400Regular.ttf"))
    pdf.add_font("NotoBeng", "B", str(FONT_DIR / "NotoSansBengali_700Bold.ttf"))
    pdf.add_font("NotoDeva", "", str(FONT_DIR / "NotoSansDevanagari_400Regular.ttf"))
    pdf.add_font("NotoDeva", "B", str(FONT_DIR / "NotoSansDevanagari_700Bold.ttf"))
    pdf.set_fallback_fonts(["NotoBeng", "NotoDeva"])
    try:
        pdf.set_text_shaping(True)  # correct conjuncts and vowel signs (uses HarfBuzz)
    except Exception:
        pass
    pdf.add_page()
    pdf.set_font("NotoSans", "B", 16)
    pdf.multi_cell(0, 9, p.get("name") or "Transcript", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NotoSans", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 6, f"Language: {p.get('language') or '-'}   Engine: {p.get('engine') or '-'}   "
                         f"Duration: {clock(p.get('duration') or 0)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    colours = {}
    for s, sp, text in _rows(p, text_mode):
        head = ""
        if timestamps:
            head += f"[{clock(s['start'])}] "
        pdf.set_text_color(130, 130, 130)
        pdf.set_font("NotoSans", "", 9)
        if head:
            pdf.write(6, head)
        if speakers and sp:
            col = colours.setdefault(sp, SPEAKER_COLOURS[len(colours) % len(SPEAKER_COLOURS)])
            pdf.set_text_color(int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16))
            pdf.set_font("NotoSans", "B", 11)
            pdf.write(6, sp + ": ")
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("NotoSans", "", 11)
        pdf.write(6, text)
        pdf.ln(8)
    pdf.set_font("NotoSans", "", 7)
    pdf.set_text_color(140, 140, 140)
    pdf.ln(4)
    pdf.write(5, f"Created with {APP_NAME} — {AUTHOR}")
    pdf.output(str(dst))
    return dst


def to_html(p, text_mode="original", speakers=True, media_name="audio.m4a", media_b64=None) -> str:
    """Read-only transcript page with an embedded player; click a line to play from it."""
    import html as H
    rows = []
    for s, sp, text in _rows(p, text_mode):
        rows.append(f'<p data-t="{s["start"]:.2f}"><span class="t">{clock(s["start"])}</span>'
                    + (f'<b>{H.escape(sp)}:</b> ' if speakers and sp else "") + H.escape(text).replace("\n", "<br>") + "</p>")
    src = f"data:audio/mp4;base64,{media_b64}" if media_b64 else media_name
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(p.get('name') or 'Transcript')}</title><style>
body{{font-family:'Nirmala UI','Noto Sans',system-ui,sans-serif;max-width:860px;margin:0 auto;padding:16px;line-height:1.6;background:#fafafa;color:#1b1b1b}}
audio{{width:100%;position:sticky;top:0}} p{{cursor:pointer;padding:4px 8px;border-radius:6px;margin:2px 0}}
p:hover{{background:#e8f0fb}} p.on{{background:#d4e4fa}} .t{{color:#888;font-size:12px;margin-right:8px}}
footer{{color:#888;font-size:12px;margin-top:24px}}</style></head><body>
<h1>{H.escape(p.get('name') or 'Transcript')}</h1><audio id="a" controls src="{src}"></audio>
<div id="x">{''.join(rows)}</div><footer>Created with {APP_NAME} — {AUTHOR}</footer>
<script>const a=document.getElementById('a'),ps=[...document.querySelectorAll('#x p')];
ps.forEach(p=>p.onclick=()=>{{a.currentTime=+p.dataset.t;a.play()}});
a.ontimeupdate=()=>{{let c=null;for(const p of ps){{if(+p.dataset.t<=a.currentTime)c=p}}ps.forEach(p=>p.classList.toggle('on',p===c))}};</script>
</body></html>"""
