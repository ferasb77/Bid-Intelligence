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

# ── Bids ──────────────────────────────────────────────────────────────────────
def get_all_bids():
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*,
               COUNT(DISTINCT r.id) as req_count,
               SUM(CASE WHEN r.status='Complete' THEN 1 ELSE 0 END) as req_done,
               COUNT(DISTINCT t.id) as task_count,
               SUM(CASE WHEN t.status='Complete' THEN 1 ELSE 0 END) as task_done
        FROM bids b
        LEFT JOIN requirements r ON r.bid_id = b.id
        LEFT JOIN tasks t ON t.bid_id = b.id
        GROUP BY b.id
        ORDER BY b.submission_deadline ASC NULLS LAST
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_bid(bid_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM bids WHERE id=?", (bid_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_bid(data):
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO bids (title,client,file_number,stage,sensitivity,owner,
                          value_cad,submission_deadline,clarification_deadline,notes)
        VALUES (:title,:client,:file_number,:stage,:sensitivity,:owner,
                :value_cad,:submission_deadline,:clarification_deadline,:notes)
    """, data)
    bid_id = c.lastrowid
    conn.commit(); conn.close()
    return bid_id

def update_bid(bid_id, data):
    data['id'] = bid_id
    data['updated_at'] = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
        UPDATE bids SET title=:title,client=:client,file_number=:file_number,
        stage=:stage,sensitivity=:sensitivity,owner=:owner,value_cad=:value_cad,
        submission_deadline=:submission_deadline,
        clarification_deadline=:clarification_deadline,
        notes=:notes,updated_at=:updated_at WHERE id=:id
    """, data)
    conn.commit(); conn.close()

def delete_bid(bid_id):
    conn = get_conn()
    conn.execute("DELETE FROM bids WHERE id=?", (bid_id,))
    conn.commit(); conn.close()

# ── Requirements ──────────────────────────────────────────────────────────────
def get_requirements(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM requirements WHERE bid_id=? ORDER BY category,req_id",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_requirement(data):
    keys = ["req_id","category","description","rfso_ref","weight",
            "evidence","owner","deadline","status","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE requirements SET req_id=:req_id,category=:category,
            description=:description,rfso_ref=:rfso_ref,weight=:weight,
            evidence=:evidence,owner=:owner,deadline=:deadline,
            status=:status,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        conn.execute("""
            INSERT INTO requirements
            (bid_id,req_id,category,description,rfso_ref,weight,evidence,owner,deadline,status,notes)
            VALUES (:bid_id,:req_id,:category,:description,:rfso_ref,:weight,
                    :evidence,:owner,:deadline,:status,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_requirement(req_id):
    conn = get_conn()
    conn.execute("DELETE FROM requirements WHERE id=?", (req_id,))
    conn.commit(); conn.close()

# ── Tasks ─────────────────────────────────────────────────────────────────────
def get_tasks(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE bid_id=? ORDER BY due_date,priority",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_task(data):
    keys = ["title","description","owner","due_date","priority","status"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE tasks SET title=:title,description=:description,owner=:owner,
            due_date=:due_date,priority=:priority,status=:status WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        conn.execute("""
            INSERT INTO tasks (bid_id,title,description,owner,due_date,priority,status)
            VALUES (:bid_id,:title,:description,:owner,:due_date,:priority,:status)
        """, clean)
    conn.commit(); conn.close()

def delete_task(task_id):
    conn = get_conn()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit(); conn.close()

# ── Documents ─────────────────────────────────────────────────────────────────
def get_documents(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM documents WHERE bid_id=? ORDER BY doc_type,name",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_document(data):
    keys = ["name","doc_type","owner","due_date","status","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE documents SET name=:name,doc_type=:doc_type,owner=:owner,
            due_date=:due_date,status=:status,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id","file_path"] + keys}
        conn.execute("""
            INSERT INTO documents (bid_id,name,doc_type,file_path,owner,due_date,status,notes)
            VALUES (:bid_id,:name,:doc_type,:file_path,:owner,:due_date,:status,:notes)
        """, clean)
    conn.commit(); conn.close()

def save_upload(bid_id, filename, file_bytes):
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads", str(bid_id))
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    with open(path, "wb") as f:
        f.write(file_bytes)
    conn = get_conn()
    conn.execute("""
        INSERT INTO documents (bid_id,name,doc_type,file_path,status)
        VALUES (?,?,?,?,'Complete')
    """, (bid_id, filename, "RFP / Source", path))
    conn.commit(); conn.close()
    return path

def delete_document(doc_id):
    conn = get_conn()
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit(); conn.close()

# ── Outline ───────────────────────────────────────────────────────────────────
def get_outline(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM outline_sections WHERE bid_id=? ORDER BY sort_order",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_section(data):
    keys = ["sort_order","section_num","title","owner","word_limit","status","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE outline_sections SET sort_order=:sort_order,section_num=:section_num,
            title=:title,owner=:owner,word_limit=:word_limit,
            status=:status,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        conn.execute("""
            INSERT INTO outline_sections
            (bid_id,sort_order,section_num,title,owner,word_limit,status,notes)
            VALUES (:bid_id,:sort_order,:section_num,:title,:owner,:word_limit,:status,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_section(sec_id):
    conn = get_conn()
    conn.execute("DELETE FROM outline_sections WHERE id=?", (sec_id,))
    conn.commit(); conn.close()

# ── Readiness ─────────────────────────────────────────────────────────────────
def get_readiness(bid_id):
    conn = get_conn()
    r = conn.execute("""
        SELECT
          (SELECT COUNT(*) FROM requirements WHERE bid_id=? AND category='Mandatory') as m_total,
          (SELECT COUNT(*) FROM requirements WHERE bid_id=? AND category='Mandatory' AND status='Complete') as m_done,
          (SELECT COUNT(*) FROM requirements WHERE bid_id=? AND category!='Mandatory') as r_total,
          (SELECT COUNT(*) FROM requirements WHERE bid_id=? AND category!='Mandatory' AND status='Complete') as r_done,
          (SELECT COUNT(*) FROM tasks WHERE bid_id=?) as t_total,
          (SELECT COUNT(*) FROM tasks WHERE bid_id=? AND status='Complete') as t_done,
          (SELECT COUNT(*) FROM documents WHERE bid_id=? AND doc_type='Submission') as d_total,
          (SELECT COUNT(*) FROM documents WHERE bid_id=? AND doc_type='Submission' AND status='Complete') as d_done
    """, (bid_id,)*8).fetchone()
    conn.close()
    return dict(r)

# ── Deliverables ──────────────────────────────────────────────────────────────
def get_deliverables(bid_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM deliverables WHERE bid_id=? ORDER BY sort_order, category",
        (bid_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_deliverable(data):
    keys = ["sort_order","service_id","title","description","category",
            "duration","volume","unit","price_ai","price_non_ai",
            "optional","linked_req_ids","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE deliverables SET sort_order=:sort_order,service_id=:service_id,
            title=:title,description=:description,category=:category,
            duration=:duration,volume=:volume,unit=:unit,
            price_ai=:price_ai,price_non_ai=:price_non_ai,
            optional=:optional,linked_req_ids=:linked_req_ids,notes=:notes
            WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        conn.execute("""
            INSERT INTO deliverables
            (bid_id,sort_order,service_id,title,description,category,
             duration,volume,unit,price_ai,price_non_ai,optional,linked_req_ids,notes)
            VALUES (:bid_id,:sort_order,:service_id,:title,:description,:category,
                    :duration,:volume,:unit,:price_ai,:price_non_ai,
                    :optional,:linked_req_ids,:notes)
        """, clean)
    conn.commit(); conn.close()

def delete_deliverable(del_id):
    conn = get_conn()
    conn.execute("DELETE FROM deliverables WHERE id=?", (del_id,))
    conn.commit(); conn.close()

# ── Content Library ───────────────────────────────────────────────────────────
def get_library_items(bid_id=None, category=None):
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
    keys = ["title","category","content","source","bid_id","tags","approved","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE content_library SET title=:title,category=:category,
            content=:content,source=:source,bid_id=:bid_id,
            tags=:tags,approved=:approved,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in keys}
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
    keys = ["name","credentials","icf_level","sectors","languages","location",
            "availability","email","phone","cv_summary","reference_contact","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE coaches SET name=:name,credentials=:credentials,
            icf_level=:icf_level,sectors=:sectors,languages=:languages,
            location=:location,availability=:availability,
            email=:email,phone=:phone,cv_summary=:cv_summary,
            reference_contact=:reference_contact,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in keys}
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
    keys = ["question_id","question","rationale","priority","linked_req_ids",
            "submitted_date","answer","answer_date","changes_matrix","status","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE clarifications SET question_id=:question_id,question=:question,
            rationale=:rationale,priority=:priority,linked_req_ids=:linked_req_ids,
            submitted_date=:submitted_date,answer=:answer,answer_date=:answer_date,
            changes_matrix=:changes_matrix,status=:status,notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
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
    keys = ["outcome","score_technical","score_financial","score_total",
            "rank","competitors","evaluator_feedback","win_factors",
            "loss_factors","lessons","notes"]
    conn = get_conn()
    if data.get("id"):
        clean = {k: data.get(k) for k in ["id"] + keys}
        conn.execute("""
            UPDATE debriefs SET outcome=:outcome,score_technical=:score_technical,
            score_financial=:score_financial,score_total=:score_total,
            rank=:rank,competitors=:competitors,evaluator_feedback=:evaluator_feedback,
            win_factors=:win_factors,loss_factors=:loss_factors,lessons=:lessons,
            notes=:notes WHERE id=:id
        """, clean)
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        conn.execute("""
            INSERT INTO debriefs
            (bid_id,outcome,score_technical,score_financial,score_total,
             rank,competitors,evaluator_feedback,win_factors,loss_factors,lessons,notes)
            VALUES (:bid_id,:outcome,:score_technical,:score_financial,:score_total,
                    :rank,:competitors,:evaluator_feedback,:win_factors,:loss_factors,
                    :lessons,:notes)
        """, clean)
    conn.commit(); conn.close()
