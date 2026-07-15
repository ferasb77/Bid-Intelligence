import sqlite3, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bids.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS bids (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        client      TEXT NOT NULL,
        file_number TEXT,
        stage       TEXT DEFAULT 'Identified',
        sensitivity TEXT DEFAULT 'Standard',
        owner       TEXT,
        value_cad   REAL,
        submission_deadline TEXT,
        clarification_deadline TEXT,
        notes       TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS requirements (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id      INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        req_id      TEXT,
        category    TEXT DEFAULT 'Mandatory',
        description TEXT NOT NULL,
        rfso_ref    TEXT,
        weight      REAL,
        evidence    TEXT,
        owner       TEXT,
        deadline    TEXT,
        status      TEXT DEFAULT 'Not Started',
        notes       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id      INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        title       TEXT NOT NULL,
        description TEXT,
        owner       TEXT,
        due_date    TEXT,
        priority    TEXT DEFAULT 'Medium',
        status      TEXT DEFAULT 'Not Started',
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS documents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id      INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        doc_type    TEXT DEFAULT 'Submission',
        file_path   TEXT,
        owner       TEXT,
        due_date    TEXT,
        status      TEXT DEFAULT 'Not Started',
        notes       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS deliverables (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id         INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        sort_order     INTEGER DEFAULT 0,
        service_id     TEXT,
        title          TEXT NOT NULL,
        description    TEXT,
        category       TEXT DEFAULT 'Core Service',
        duration       TEXT,
        volume         TEXT,
        unit           TEXT,
        price_ai       REAL,
        price_non_ai   REAL,
        optional       INTEGER DEFAULT 0,
        linked_req_ids TEXT,
        notes          TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS content_library (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        category    TEXT DEFAULT 'Methodology',
        content     TEXT NOT NULL,
        source      TEXT,
        bid_id      INTEGER REFERENCES bids(id) ON DELETE SET NULL,
        tags        TEXT,
        approved    INTEGER DEFAULT 0,
        notes       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS coaches (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        name               TEXT NOT NULL,
        credentials        TEXT,
        icf_level          TEXT,
        sectors            TEXT,
        languages          TEXT,
        location           TEXT,
        availability       TEXT DEFAULT 'Available',
        email              TEXT,
        phone              TEXT,
        cv_summary         TEXT,
        reference_contact  TEXT,
        notes              TEXT,
        created_at         TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS clarifications (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id          INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        question_id     TEXT,
        question        TEXT NOT NULL,
        rationale       TEXT,
        priority        TEXT DEFAULT 'Medium',
        linked_req_ids  TEXT,
        submitted_date  TEXT,
        answer          TEXT,
        answer_date     TEXT,
        changes_matrix  INTEGER DEFAULT 0,
        status          TEXT DEFAULT 'Draft',
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS debriefs (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id             INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        outcome            TEXT DEFAULT 'Pending',
        score_technical    REAL,
        score_financial    REAL,
        score_total        REAL,
        rank               INTEGER,
        competitors        TEXT,
        evaluator_feedback TEXT,
        win_factors        TEXT,
        loss_factors       TEXT,
        lessons            TEXT,
        notes              TEXT,
        created_at         TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS outline_sections (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id      INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        sort_order  INTEGER DEFAULT 0,
        section_num TEXT,
        title       TEXT NOT NULL,
        owner       TEXT,
        word_limit  INTEGER,
        status      TEXT DEFAULT 'Not Started',
        notes       TEXT
    );

    CREATE TABLE IF NOT EXISTS content_library (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        category    TEXT DEFAULT 'Methodology',
        content     TEXT NOT NULL,
        source      TEXT,
        bid_id      INTEGER REFERENCES bids(id) ON DELETE SET NULL,
        tags        TEXT,
        approved    INTEGER DEFAULT 0,
        notes       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS coaches (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        name               TEXT NOT NULL,
        credentials        TEXT,
        icf_level          TEXT,
        sectors            TEXT,
        languages          TEXT,
        location           TEXT,
        availability       TEXT DEFAULT 'Available',
        email              TEXT,
        phone              TEXT,
        cv_summary         TEXT,
        reference_contact  TEXT,
        notes              TEXT,
        created_at         TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS clarifications (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id          INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        question_id     TEXT,
        question        TEXT NOT NULL,
        rationale       TEXT,
        priority        TEXT DEFAULT 'Medium',
        linked_req_ids  TEXT,
        submitted_date  TEXT,
        answer          TEXT,
        answer_date     TEXT,
        changes_matrix  INTEGER DEFAULT 0,
        status          TEXT DEFAULT 'Draft',
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS debriefs (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id             INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        outcome            TEXT DEFAULT 'Pending',
        score_technical    REAL,
        score_financial    REAL,
        score_total        REAL,
        rank               INTEGER,
        competitors        TEXT,
        evaluator_feedback TEXT,
        win_factors        TEXT,
        loss_factors       TEXT,
        lessons            TEXT,
        notes              TEXT,
        created_at         TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS deliverables (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        bid_id         INTEGER NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
        sort_order     INTEGER DEFAULT 0,
        service_id     TEXT,
        title          TEXT NOT NULL,
        description    TEXT,
        category       TEXT DEFAULT 'Core Service',
        duration       TEXT,
        volume         TEXT,
        unit           TEXT,
        price_ai       REAL,
        price_non_ai   REAL,
        optional       INTEGER DEFAULT 0,
        linked_req_ids TEXT,
        notes          TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

# ── Content Library ───────────────────────────────────────────────────────────
def get_library_items(bid_id=None, category=None):
    """Global library (bid_id=None) or bid-scoped items."""
    conn = get_conn()
    q = "SELECT * FROM content_library WHERE 1=1"
    params = []
    if bid_id:
        q += " AND (bid_id=? OR bid_id IS NULL)"
        params.append(bid_id)
    if category:
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY category, title"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_library_item(data):
    conn = get_conn()
    # Extract only the keys the SQL expects — ignore any extra fields
    if data.get("id"):
        clean = {k: data.get(k) for k in
                 ["id","title","category","content","source","bid_id","tags","approved","notes"]}
        conn.execute("""
            UPDATE content_library SET title=:title,category=:category,
            content=:content,source=:source,bid_id=:bid_id,
            tags=:tags,approved=:approved,notes=:notes
            WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in
                 ["title","category","content","source","bid_id","tags","approved","notes"]}
        conn.execute("""
            INSERT INTO content_library
            (title,category,content,source,bid_id,tags,approved,notes)
            VALUES (:title,:category,:content,:source,:bid_id,:tags,:approved,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_library_item(item_id):
    conn = get_conn()
    conn.execute("DELETE FROM content_library WHERE id=?", (item_id,))
    conn.commit(); conn.close()

# ── Coach Roster ──────────────────────────────────────────────────────────────
def get_coaches():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coaches ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_coach(data):
    coach_keys = ["name","credentials","icf_level","sectors","languages",
                  "location","availability","email","phone","cv_summary",
                  "reference_contact","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + coach_keys}
        conn.execute("""
            UPDATE coaches SET name=:name,credentials=:credentials,
            icf_level=:icf_level,sectors=:sectors,languages=:languages,
            location=:location,availability=:availability,
            email=:email,phone=:phone,cv_summary=:cv_summary,
            reference_contact=:reference_contact,notes=:notes
            WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in coach_keys}
        conn.execute("""
            INSERT INTO coaches
            (name,credentials,icf_level,sectors,languages,location,
             availability,email,phone,cv_summary,reference_contact,notes)
            VALUES (:name,:credentials,:icf_level,:sectors,:languages,:location,
                    :availability,:email,:phone,:cv_summary,:reference_contact,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_coach(coach_id):
    conn = get_conn()
    conn.execute("DELETE FROM coaches WHERE id=?", (coach_id,))
    conn.commit(); conn.close()

# ── Clarification Tracker ─────────────────────────────────────────────────────
def get_clarifications(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM clarifications WHERE bid_id=? ORDER BY priority DESC, id",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_clarification(data):
    clar_keys = ["question_id","question","rationale","priority","linked_req_ids",
                 "submitted_date","answer","answer_date","changes_matrix","status","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + clar_keys}
        conn.execute("""
            UPDATE clarifications SET question_id=:question_id,question=:question,
            rationale=:rationale,priority=:priority,linked_req_ids=:linked_req_ids,
            submitted_date=:submitted_date,answer=:answer,answer_date=:answer_date,
            changes_matrix=:changes_matrix,status=:status,notes=:notes
            WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + clar_keys}
        conn.execute("""
            INSERT INTO clarifications
            (bid_id,question_id,question,rationale,priority,linked_req_ids,
             submitted_date,answer,answer_date,changes_matrix,status,notes)
            VALUES (:bid_id,:question_id,:question,:rationale,:priority,
                    :linked_req_ids,:submitted_date,:answer,:answer_date,
                    :changes_matrix,:status,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_clarification(clar_id):
    conn = get_conn()
    conn.execute("DELETE FROM clarifications WHERE id=?", (clar_id,))
    conn.commit(); conn.close()

# ── Win/Loss Debrief ──────────────────────────────────────────────────────────
def get_debriefs(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM debriefs WHERE bid_id=? ORDER BY id",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_debrief(data):
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE debriefs SET outcome=:outcome,score_technical=:score_technical,
            score_financial=:score_financial,score_total=:score_total,
            rank=:rank,competitors=:competitors,evaluator_feedback=:evaluator_feedback,
            win_factors=:win_factors,loss_factors=:loss_factors,lessons=:lessons,
            notes=:notes WHERE id=:id
        """, data)
    else:
        conn.execute("""
            INSERT INTO debriefs
            (bid_id,outcome,score_technical,score_financial,score_total,
             rank,competitors,evaluator_feedback,win_factors,loss_factors,lessons,notes)
            VALUES (:bid_id,:outcome,:score_technical,:score_financial,:score_total,
                    :rank,:competitors,:evaluator_feedback,:win_factors,:loss_factors,
                    :lessons,:notes)
        """, data)
    conn.commit(); conn.close()

