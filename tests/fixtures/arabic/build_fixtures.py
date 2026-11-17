"""Builds the synthetic Arabic / bilingual procurement fixtures used by
tests/test_arabic_support.py. Fictional buyer and content.

Run once (dev only; needs arabic-reshaper, python-bidi and an Arabic-capable
TTF such as Windows Arial): python tests/fixtures/arabic/build_fixtures.py

The generated files are committed, so the tests do not need these tools.
Two PDF producer styles are covered on purpose:
* visual order + presentation-form glyphs (reportlab + reshaper + bidi), the
  way many generators write Arabic -- PyMuPDF extracts these with reversed
  Arabic-Indic digit runs unless the extractor rebuilds the line order;
* logically shaped text (PyMuPDF HTML box with HarfBuzz shaping).
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = os.environ.get("ARABIC_TTF", r"C:\Windows\Fonts\arial.ttf")

RFP_PAGES = [
    [
        "وزارة التنمية الريفية",
        "طلب عروض رقم ٢٠٢٦/٤٥",
        "تقديم خدمات التدريب على ريادة الأعمال للشباب",
        "١. مقدمة",
        "تدعو وزارة التنمية الريفية الشركات المؤهلة إلى تقديم عروضها لتنفيذ برنامج تدريبي.",
        "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦ الساعة ١٢:٠٠ ظهراً.",
        "٢. نطاق العمل",
        "تنفيذ ست جلسات تدريبية للشباب من عمر ١٨ إلى ٢٨ سنة.",
        "إعداد المواد التدريبية باللغة العربية.",
        "تقديم تقرير ختامي خلال ١٥ يوماً من انتهاء التدريب.",
    ],
    [
        "٣. شروط الأهلية",
        "يجب أن يكون لدى المتنافس سجل تجاري ساري المفعول.",
        "يجب ألا تقل خبرة المدرب الرئيسي عن خمس سنوات.",
        "٤. معايير التقييم",
        "العرض الفني ٧٠٪",
        "الخبرة السابقة ٣٠٪",
        "المنهجية ٢٥٪",
        "فريق العمل ١٥٪",
        "العرض المالي ٣٠٪",
        "٥. العرض المالي",
        "يجب أن تكون الأسعار شاملة لجميع الضرائب والرسوم.",
        "٦. شروط الدفع",
        "يتم الدفع على دفعتين: ٥٠٪ بعد التدريب و٥٠٪ بعد قبول التقرير الختامي.",
        "٧. تقديم العروض",
        "ترسل العروض عبر البريد الإلكتروني إلى tenders@rural-dev.example.org",
    ],
]

ADDENDUM_LINES = [
    "ملحق تعديل رقم (١)",
    "طلب عروض رقم ٢٠٢٦/٤٥",
    "تم تمديد آخر موعد لتقديم العروض ليصبح ١٥ كانون الأول ٢٠٢٦.",
    "يجب إرفاق شهادة عدم محكومية للمدرب الرئيسي.",
]


def _visual_pdf(pages: list[list[str]]) -> bytes:
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("ArFixture", FONT))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842), invariant=1)
    for lines in pages:
        c.setFont("ArFixture", 12)
        y = 780
        for ln in lines:
            c.drawRightString(550, y, get_display(arabic_reshaper.reshape(ln)))
            y -= 26
        c.showPage()
    c.save()
    return buf.getvalue()


def _logical_pdf(pages: list[list[str]]) -> bytes:
    import pymupdf as fitz
    doc = fitz.open()
    arch = fitz.Archive(str(Path(FONT).parent))
    css = f"@font-face {{font-family: ar; src: url({Path(FONT).name});}} p {{font-family: ar; font-size: 12px;}}"
    for lines in pages:
        page = doc.new_page(width=595, height=842)
        html = "".join(f'<p dir="rtl">{ln}</p>' for ln in lines)
        page.insert_htmlbox(fitz.Rect(40, 40, 555, 800), html, css=css, archive=arch)
    doc.subset_fonts()
    return doc.tobytes(garbage=4, deflate=True)


def _scanned_pdf(pdf_bytes: bytes) -> bytes:
    import pymupdf as fitz
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=pix.tobytes("jpeg", jpg_quality=70))
    return out.tobytes(garbage=4, deflate=True)


def _rtl(paragraph) -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    ppr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    ppr.append(bidi)


def _arabic_docx() -> bytes:
    import docx
    d = docx.Document()
    _rtl(d.add_heading("كراسة الشروط والمواصفات", level=1))
    _rtl(d.add_paragraph("تدعو وزارة التنمية الريفية الشركات المؤهلة إلى تقديم عروضها."))
    _rtl(d.add_heading("نطاق العمل", level=1))
    _rtl(d.add_paragraph("تنفيذ ست جلسات تدريبية للشباب من عمر ١٨ إلى ٢٨ سنة."))
    _rtl(d.add_paragraph("إعداد المواد التدريبية وتقديم تقرير ختامي."))
    _rtl(d.add_heading("معايير التقييم", level=1))
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "المعيار", "الوزن النسبي"
    for name, w in [("الخبرة السابقة", "٣٠٪"), ("المنهجية", "٢٥٪"), ("فريق العمل", "١٥٪"), ("العرض المالي", "٣٠٪")]:
        row = t.add_row()
        row.cells[0].text, row.cells[1].text = name, w
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _bilingual_docx() -> bytes:
    import docx
    d = docx.Document()
    d.add_heading("Scope of Work / نطاق العمل", level=1)
    d.add_paragraph("The consultant shall deliver six training sessions.")
    _rtl(d.add_paragraph("يلتزم الاستشاري بتنفيذ ست جلسات تدريبية."))
    d.add_heading("Submission / تقديم العروض", level=1)
    d.add_paragraph("Proposals must be submitted by e-mail to tenders@rural-dev.example.org.")
    _rtl(d.add_paragraph("في حال وجود تعارض بين النصين العربي والإنجليزي يعتمد النص العربي."))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _bilingual_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "جدول الكميات"
    ws.append(["البند / Item", "الكمية / Quantity", "سعر الوحدة / Unit price", "المجموع / Total"])
    ws.append(["جلسة تدريبية / Training session", 6, None, "=B2*C2"])
    ws.append(["تقرير ختامي / Final report", 1, None, "=B3*C3"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _legacy_zip(entries: dict[str, bytes]) -> bytes:
    """A ZIP whose Arabic names are raw UTF-8 bytes WITHOUT the UTF-8 flag
    (what macOS Archive Utility and many Windows tools write)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 0, 0, 0))  # stored as UTF-8 bytes
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    raw = bytearray(buf.getvalue())
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):  # clear general-purpose flag bit 11
        pos = 0
        while (pos := raw.find(sig, pos)) >= 0:
            off = pos + (6 if sig == b"PK\x03\x04" else 8)
            raw[off] &= 0xFF
            raw[off + 1] &= 0xF7
            pos += 4
    return bytes(raw)


def main() -> None:
    out = {
        "arabic_rfp_visual.pdf": _visual_pdf(RFP_PAGES),
        "arabic_rfp_logical.pdf": _logical_pdf(RFP_PAGES),
        "arabic_addendum.pdf": _visual_pdf([ADDENDUM_LINES]),
        "arabic_tor.docx": _arabic_docx(),
        "bilingual_tor.docx": _bilingual_docx(),
        "bilingual_pricing.xlsx": _bilingual_xlsx(),
    }
    out["arabic_rfp_scanned.pdf"] = _scanned_pdf(out["arabic_rfp_visual.pdf"])
    out["arabic_package.zip"] = _legacy_zip({
        "كراسة الشروط.pdf": out["arabic_rfp_visual.pdf"],
        "ملحق تعديل رقم 1.pdf": out["arabic_addendum.pdf"],
        "جدول الكميات.xlsx": out["bilingual_pricing.xlsx"],
    })
    for name, data in out.items():
        (HERE / name).write_bytes(data)
        print(f"{name}: {len(data)} bytes")


if __name__ == "__main__":
    sys.exit(main())
