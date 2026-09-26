"""
Deterministic, in-memory builders for the CHECK-1 Calgary 26-1603
acceptance package (bidder side).

HONESTY NOTE: the actual submitted Phoenix artifacts (Appendix C, the
completed Appendix D Price Form, Appendix E, the B2 Multi-Party
Confirmation Form) are NOT available in this repository or in the live
database -- the live bid (bid_id=1) holds only one combined "Technical &
Commercial Proposal" PDF. These builders therefore generate SYNTHETIC
artifacts that reproduce the STRUCTURE the task describes (four separate
files; a narrative with no pricing values; a spreadsheet Price Form with
yellow lump-sum input cells for Items 1-3 weighted 55/35/10, as recorded
in the live Addendum Five-derived requirements; a declarations form; a
two-party multi-party form). Office/PDF writers embed timestamps, so
every builder is memoized: one test session sees ONE set of bytes. Numbers and prose are illustrative, not the
bidder's real figures.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from functools import lru_cache

FIXTURE_JSON = os.path.join(os.path.dirname(__file__), "fixtures", "calgary_26_1603_live_requirements.json")

TECH_NAME = "Appendix C - Technical Proposal - Phoenix Consulting.pdf"
PRICE_NAME = "Appendix D - Price Form - Completed.xlsx"
SUBMISSION_NAME = "Appendix E - Submission Form - Signed.docx"
MULTI_PARTY_NAME = "B2 Multi-Party Confirmation Form - Phoenix Consulting Canada + Inquisitive Talent.docx"

YELLOW = "FFFFFF00"


def load_fixture() -> dict:
    with open(FIXTURE_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def live_requirements() -> list[dict]:
    return [dict(r) for r in load_fixture()["requirements"]]


def synthetic_requirements() -> list[dict]:
    return [dict(r) for r in load_fixture()["supplemental_synthetic"]["requirements"]]


def evaluation_criteria() -> list[dict]:
    return [dict(c) for c in load_fixture()["supplemental_synthetic"]["evaluation_criteria"]]


def known_bad_findings() -> list[dict]:
    return [dict(f) for f in load_fixture()["known_bad_baseline_findings"]["findings"]]


def make_pdf(pages: list[list[str]]) -> bytes:
    import fitz
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 60
        for line in lines:
            if line == "":
                y += 22
                continue
            page.insert_text((56, y), line, fontsize=10)
            y += 14
    out = doc.tobytes()
    doc.close()
    return out


TECH_PAGES = [
    ["RFP No. 26-1603", "Design and Delivery Services for Leadership Learning and Development",
     "Appendix C - Technical Proposal", "Prepared by Phoenix Consulting Canada"],
    ["Contents",
     "PART 1 - CORPORATE PROFILE ............................................ 3",
     "3.2 Six-Stage Programme Delivery Methodology .......................... 4",
     "",
     "PART 1 - CORPORATE PROFILE",
     "Phoenix Consulting is a boutique human capital consultancy with an office in Canada.",
     "",
     "PART 2 - CONSORTIUM",
     "This proposal is submitted jointly by Phoenix Consulting Canada (lead proponent)",
     "and Inquisitive Talent (member firm), an authorized Hogan Assessments provider."],
    ["PART 3 - TEAM EXPERIENCE AND QUALIFICATIONS",
     "Our facilitators hold ICF credentials and have delivered leadership programmes",
     "for municipal and energy-sector clients. A dedicated Account Manager oversees delivery."],
    ["PART 4 - SCOPE OF SERVICES",
     "Our methodology aligns each cohort to the City's leadership competency framework.",
     "",
     "3.2 Six-Stage Programme Delivery Methodology",
     "Stage 1 Prepare, Stage 2 Learn, Stage 3 Apply, Stage 4 Coach, Stage 5 Reflect, Stage 6 Evaluate.",
     "Goals and objectives are tied to success measures reviewed with the City.",
     "Blended delivery combines in-person facilitation and virtual components."],
    ["3.5 Programme Governance, Quality Assurance, and Evaluation",
     "Facilitator calibration and quality assurance protocols apply to every cohort.",
     "Four-level evaluation reporting measures learning outcomes and behaviour change.",
     "Post-facilitation support of three hours per participant is provided within each cohort."],
]


@lru_cache(maxsize=None)
def make_technical_proposal_pdf() -> bytes:
    return make_pdf(TECH_PAGES)


@lru_cache(maxsize=None)
def make_price_form_xlsx(*, leave_item3_blank: bool = False) -> bytes:
    import openpyxl
    from openpyxl.styles import PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Price Form"
    ws["A1"] = "Appendix D - Pricing Form"
    ws["A2"] = "Enter a lump sum (LS) price in each yellow cell. Travel costs must be included under Item 3."
    headers = ["Item", "Description", "Sample Scenario", "UOM", "Cost", "Weight", "Weighted Cost"]
    for i, h in enumerate(headers, 1):
        ws.cell(row=4, column=i, value=h)
    rows = [
        (1, "Cohort Program Development & Design and Program Delivery", "Personal Leadership cohort of 25", "LS", 12000, 0.55),
        (2, "Cohort Program Development & Design and Program Delivery", "Senior Leader cohort of 25", "LS", 9500, 0.35),
        (3, "Travel Expenses (if applicable)", "Round-trip airfare, 3 nights accommodation", "Fixed fee / 1 person", 2122.5, 0.10),
    ]
    yellow = PatternFill(fill_type="solid", fgColor=YELLOW)
    for r_off, (item, desc, scen, uom, cost, weight) in enumerate(rows):
        r = 5 + r_off
        ws.cell(row=r, column=1, value=item)
        ws.cell(row=r, column=2, value=desc)
        ws.cell(row=r, column=3, value=scen)
        ws.cell(row=r, column=4, value=uom)
        c = ws.cell(row=r, column=5, value=None if (leave_item3_blank and item == 3) else cost)
        c.fill = yellow
        ws.cell(row=r, column=6, value=weight)
        ws.cell(row=r, column=7, value=f"=E{r}*F{r}")
    ws["B9"] = "Total weighted cost to be used in the pricing formula"
    ws["G9"] = "=SUM(G5:G7)"
    notes = wb.create_sheet("Instructions")
    notes["A1"] = "Pricing shall be based on three (3) hours of post-facilitation support per participant."
    notes["A2"] = "Total weighted cost = (0.55 x Item 1) + (0.35 x Item 2) + (0.10 x Item 3)."
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@lru_cache(maxsize=None)
def make_submission_form_docx(*, blank_signatory: bool = False) -> bytes:
    import docx
    d = docx.Document()
    d.add_heading("Appendix E - Submission Form", level=1)
    d.add_paragraph("RFP 26-1603 Design and Delivery Services for Leadership Learning and Development")
    t = d.add_table(rows=4, cols=2)
    fields = [("Legal Name of Proponent", "Phoenix Consulting Canada"),
              ("Authorized Signatory", "" if blank_signatory else "Z. Mimassi, Managing Partner"),
              ("Address", "Calgary, Alberta"),
              ("Date", "July 16, 2026")]
    for i, (k, v) in enumerate(fields):
        t.cell(i, 0).text = k
        t.cell(i, 1).text = v
    d.add_heading("Declarations", level=2)
    d.add_paragraph("☒ The Proponent acknowledges receipt of Addenda 1 to 5.")
    d.add_paragraph("☒ Conflict of Interest: the Proponent declares that it has no actual or potential conflict of interest.")
    d.add_paragraph("☐ The Proponent requests that pages be treated as confidential.")
    d.add_paragraph("The Proponent is authorized to bind the organization and this proposal is a binding offer.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@lru_cache(maxsize=None)
def make_multi_party_form_docx() -> bytes:
    import docx
    d = docx.Document()
    d.add_heading("B2 - Multi-Party Confirmation Form", level=1)
    d.add_paragraph("Complete this form where a proposal is submitted jointly by more than one party.")
    t = d.add_table(rows=3, cols=4)
    for i, h in enumerate(["Party", "Legal Name", "Role", "Signature"]):
        t.cell(0, i).text = h
    for r, row in enumerate([("Lead Proponent", "Phoenix Consulting Canada", "Lead", "Signed"),
                             ("Member", "Inquisitive Talent", "Member firm", "Signed")], 1):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    d.add_paragraph("The parties confirm they are jointly and severally liable for the proposal.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def calgary_submission_files(**kw) -> list[tuple[str, bytes]]:
    return [
        (TECH_NAME, make_technical_proposal_pdf()),
        (PRICE_NAME, make_price_form_xlsx(leave_item3_blank=kw.get("leave_item3_blank", False))),
        (SUBMISSION_NAME, make_submission_form_docx(blank_signatory=kw.get("blank_signatory", False))),
        (MULTI_PARTY_NAME, make_multi_party_form_docx()),
    ]


@lru_cache(maxsize=None)
def calgary_submission_zip() -> list[tuple[str, bytes]]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in calgary_submission_files():
            z.writestr(f"Phoenix Submission/{name}", data)
    return [("Phoenix_26-1603_Submission.zip", buf.getvalue())]
