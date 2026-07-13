# Bid Intelligence Platform — MVP

Phase 1 · Bid Control · Local SQLite · Streamlit

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
├── database.py             # SQLite schema + all data access
├── data/bids.db            # Created on first run (git-ignore this)
├── uploads/                # RFP files stored here
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

## Phase 2 (next)

AI extraction will read an uploaded RFP PDF and auto-populate
the compliance matrix — same data model, no schema changes needed.
