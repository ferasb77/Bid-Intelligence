# Bid Intelligence — Decision & Proposal Platform

An endorsed Enable My Growth application developed by Feras Banna.

Bid Intelligence provides a structured environment for examining bid
decisions, evidence, compliance, and proposal readiness before committing
resources. Human commercial judgment remains accountable at every stage.

## Setup (one time)

```bash
pip install streamlit openpyxl
```

## Run

```bash
cd bid_platform
streamlit run app.py
```

Opens at http://localhost:8501

## Structure

```
bid_platform/
├── app.py                  # Entry point + routing
├── brand.py                # Enable My Growth product identity
├── database.py             # Supabase data access
├── assets/                 # Approved mark and brand fonts
├── components/
│   └── ui.py               # CSS, badges, helpers
└── pages/
    ├── bid_overview.py     # Bid summary, readiness, RFP upload
    ├── compliance.py       # Compliance matrix
    ├── tasks.py            # Task board
    ├── documents.py        # Document checklist
    └── outline.py          # Proposal outline with templates
```

## What each page does

| Page | Purpose |
|---|---|
| Dashboard | Pipeline overview, KPIs, urgent deadlines |
| All Bids | Full bid list with stage and readiness |
| New Bid | Create a bid record |
| Bid Overview | Readiness gauges, key dates, RFP upload, edit |
| Compliance Matrix | M/R/F requirements, owners, status tracking |
| Documents | Submission checklist + uploaded files |
| Tasks | Task board grouped by priority |
| Proposal Outline | Section list with template quick-start |

## Brand

See `BRAND-INTEGRATION.md` for product positioning, identity tokens, and the
distinction between the Enable My Growth product brand and client-specific
operating context.
