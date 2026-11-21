"""Synthetic procurement package and scripted analysts for engine tests.

Entirely invented: the buyer, programme and every provision are fictitious.
This module lives under tests/ and must never be imported by production code
(enforced by tests/test_engine_constraints.py)."""
from __future__ import annotations

import json
import re

RFP = """[[SOURCE: Synthetic_RFP.pdf | PAGE: 1]]
NORTHWIND RIVER AUTHORITY
Request for Proposals NRA-SYN-001: Community Water Monitoring Training
1. Purpose
The Authority seeks a provider to deliver water-quality monitoring training to volunteer groups in the Lower Valley.
[[SOURCE: Synthetic_RFP.pdf | PAGE: 2]]
2. Eligibility
Bidders must be registered non-profit organisations with at least three years of experience in environmental education.
Consortia may bid provided that the lead member is a registered non-profit organisation.
3. Submission
Proposals must be submitted by e-mail to tenders@northwind.example no later than 15 March 2027 at 12:00.
Late proposals will not be considered.
A bid security of 2% of the proposal value must accompany the proposal.
[[SOURCE: Synthetic_RFP.pdf | PAGE: 3]]
4. Evaluation
Technical quality 70% and price 30%.
The Authority will hold a briefing session for shortlisted bidders.
5. Order of precedence
Addenda issued by the Authority prevail over this Request for Proposals to the extent of any inconsistency.
"""

ADDENDUM = """[[SOURCE: Synthetic_Addendum_1.pdf | PAGE: 1]]
Addendum No. 1
The submission deadline in Section 3 is amended to 22 March 2027 at 12:00.
"""


def documents() -> list[dict]:
    return [{"name": "Synthetic_RFP.pdf", "text": RFP, "meta": {"page_count": 3}},
            {"name": "Synthetic_Addendum_1.pdf", "text": ADDENDUM, "meta": {"page_count": 1}}]


def _f(cat, statement, quote, doc, page, modality, *, values=(), conditions=(), materiality="CRITICAL",
       party="bidder", action=""):
    return {"category": cat, "statement": statement, "quote": quote, "document": doc, "page": str(page),
            "section": "", "party": party, "action": action or statement, "modality": modality,
            "conditions": list(conditions), "exceptions": [], "values": [{"kind": k, "text": t, "normalized": n}
                                                                        for k, t, n in values],
            "consequence": "", "materiality": materiality, "relations": [], "uncertainty": ""}


R, A = "Synthetic_RFP.pdf", "Synthetic_Addendum_1.pdf"
BASE = [
    _f("ELIGIBILITY", "Bidders must be registered non-profit organisations.",
       "Bidders must be registered non-profit organisations", R, 2, "MUST"),
    _f("QUALIFICATION", "Bidders must have at least three years of experience in environmental education.",
       "with at least three years of experience in environmental education", R, 2, "MUST"),
    _f("ELIGIBILITY", "Consortia may bid provided that the lead member is a registered non-profit organisation.",
       "Consortia may bid provided that the lead member is a registered non-profit organisation", R, 2, "MAY",
       conditions=["the lead member is a registered non-profit organisation"]),
    _f("SUBMISSION_METHOD", "Proposals must be submitted by e-mail to tenders@northwind.example.",
       "Proposals must be submitted by e-mail to tenders@northwind.example", R, 2, "MUST",
       values=[("EMAIL", "tenders@northwind.example", "tenders@northwind.example")]),
    _f("DEADLINE", "Proposals must be submitted no later than 15 March 2027 at 12:00.",
       "no later than 15 March 2027 at 12:00", R, 2, "MUST",
       values=[("DATE", "15 March 2027", "2027-03-15"), ("TIME", "12:00", "12:00")], action="submit proposals"),
    _f("DISQUALIFICATION", "Late proposals will not be considered.", "Late proposals will not be considered", R, 2,
       "WILL"),
    _f("EVALUATION", "Technical quality is weighted 70% and price 30%.", "Technical quality 70% and price 30%", R, 3,
       "IS", values=[("PERCENT", "70%", "70"), ("PERCENT", "30%", "30")]),
    _f("DOCUMENT_AUTHORITY", "Addenda prevail over the RFP to the extent of any inconsistency.",
       "Addenda issued by the Authority prevail over this Request for Proposals to the extent of any inconsistency",
       R, 3, "IS", materiality="MATERIAL"),
    _f("DEADLINE", "The submission deadline is amended to 22 March 2027 at 12:00.",
       "The submission deadline in Section 3 is amended to 22 March 2027 at 12:00", A, 1, "IS",
       values=[("DATE", "22 March 2027", "2027-03-22"), ("TIME", "12:00", "12:00")], action="submit proposals"),
    _f("SCOPE", "The Authority seeks a provider to deliver water-quality monitoring training to volunteer groups.",
       "The Authority seeks a provider to deliver water-quality monitoring training to volunteer groups in the Lower "
       "Valley", R, 1, "IS", materiality="MATERIAL", party="Authority"),
    _f("IDENTITY", "Request for Proposals NRA-SYN-001: Community Water Monitoring Training.",
       "Request for Proposals NRA-SYN-001: Community Water Monitoring Training", R, 1, "IS",
       materiality="INFORMATIONAL", values=[("REFERENCE", "NRA-SYN-001", "NRA-SYN-001")]),
]
#: analyst B: misses the bid security like A, reads the briefing as an obligation (dispute), finds the security
B_EXTRA = [_f("GUARANTEE", "A bid security of 2% of the proposal value must accompany the proposal.",
              "A bid security of 2% of the proposal value must accompany the proposal", R, 2, "MUST",
              values=[("PERCENT", "2%", "2")])]
BRIEFING_A = _f("OTHER", "The Authority will hold a briefing session for shortlisted bidders.",
                "The Authority will hold a briefing session for shortlisted bidders", R, 3, "WILL",
                materiality="MATERIAL", party="Authority")
BRIEFING_B = dict(BRIEFING_A, statement="Shortlisted bidders must attend a briefing session.", modality="MUST")


def _ids(user: str) -> list[str]:
    m = re.search(r"Account for each SECTION_ID: ([^\n]+)", user)
    return [x.strip() for x in m.group(1).split(",")] if m else []


def responder(tag: str):
    """A scripted analyst: returns the findings whose quote is in the unit text."""
    pool = BASE + ([BRIEFING_A] if tag == "A" else [BRIEFING_B] + B_EXTRA)

    def respond(purpose, system, user, schema):
        if purpose.startswith("extract:"):
            fs = [f for f in pool if f["quote"] in user and f"SOURCE: {f['document']}" in user]
            return {"findings": fs, "sections": [{"section_id": i, "status": "HAS_FINDINGS", "note": ""}
                                                 for i in _ids(user)]}
        if purpose == "package_review":
            ids = re.findall(r"^(\w-U\d+\w*-\d+) \| [^|]+\| DEADLINE", user, re.M)
            rel = [{"type": "EXPRESS_AMENDMENT", "finding_ids": ids, "explanation": "addendum amends deadline",
                    "authority_quote": "The submission deadline in Section 3 is amended to 22 March 2027 at 12:00",
                    "authority_document": A, "clarification_question": "", "implication": ""}] if len(ids) > 1 else []
            return {"documents": [], "relationships": rel, "missed": []}
        raise AssertionError(f"unexpected purpose {purpose}")
    return respond


def adjudicator():
    def respond(purpose, system, user, schema):
        if purpose == "adjudicate":
            decisions = []
            for eid in re.findall(r"^ENTRY (E\d+)", user, re.M):
                block = user[user.index(f"ENTRY {eid}"):].split("\n\nENTRY ")[0]
                if "briefing" in block:
                    decisions.append({"entry_id": eid, "decision": "CONFIRMED", "preferred": "A", "statement": "",
                                      "modality": "WILL", "quote": "", "duplicate_of": "",
                                      "reason": "the text states what the Authority will do; no obligation"})
                else:
                    decisions.append({"entry_id": eid, "decision": "CONFIRMED", "preferred": "BOTH", "statement": "",
                                      "modality": "IS", "quote": "", "duplicate_of": "", "reason": "faithful"})
            return {"decisions": decisions}
        if purpose == "conflicts":
            cands = re.findall(r"^(C\d+) \(noted", user, re.M)
            out = []
            for c in cands:
                block = user[user.index(c + " (noted"):]
                ids = re.findall(r"^(E\d+) \|", block.split("\n\nC")[0], re.M)
                old = [i for i in ids if "15 March" in block.split(i + " |")[1].split("\n")[0]]
                new = [i for i in ids if "22 March" in block.split(i + " |")[1].split("\n")[0]]
                if old and new:
                    out.append({"candidate_id": c, "type": "EXPRESS_AMENDMENT", "prevailing_entry": new[0],
                                "superseded_entries": old,
                                "authority_quote": "The submission deadline in Section 3 is amended to 22 March 2027",
                                "authority_document": A, "issue": "deadline amended", "clarification_question": "",
                                "implication": ""})
            return {"relationships": out}
        if purpose == "analysis":
            ids = dict(re.findall(r"^(E\d+) \| (\w+)", user, re.M))
            ident = next((i for i, c in ids.items() if c == "IDENTITY"), "")
            scope = next((i for i, c in ids.items() if c == "SCOPE"), "")
            return {"title": {"text": "Community Water Monitoring Training", "entry_ids": [ident]},
                    "buyer": {"text": "", "entry_ids": []},
                    "reference": {"text": "NRA-SYN-001", "entry_ids": [ident]},
                    "summary": [{"text": "The Authority seeks water-quality monitoring training for volunteer groups.",
                                 "entry_ids": [scope]},
                                {"text": "Bids are due on 1 April 2027.", "entry_ids": [scope]}],
                    "points": []}
        if purpose == "final_review":
            return {"issues": []}
        raise AssertionError(purpose)
    return respond


def dumps(x) -> str:
    return json.dumps(x, indent=1, default=str)
