"""
In-memory stand-in for migration 022 (CHECK-2B durable CHECK runs).

Implements the SAME contract migrations/022_check_runs.sql enforces:
advisory-locked start outcomes (CREATED / ACTIVE_RUN_EXISTS /
REUSED_COMPLETE / EXISTING_FAILED / EXISTING_PARTIAL), bid-scoped
ownership checks on every RPC, gap-free event sequencing, terminal-run
refusal, COMPLETE-must-be-complete (result.run_integrity + every semantic
batch COMPLETE + batch count == plan), one adjudication per buyer object,
the check_adjudications row CHECK constraints, and the
check_adjudication_evidence FK into submission_evidence_items (same bid AND
same package snapshot) -- all-or-nothing per finalize call. Every jsonb
payload is JSON round-tripped exactly as Postgres jsonb would be.

`dump()` / `FakeCheckDB.load()` serialize the whole store so a persisted
run can be reopened in a genuinely fresh process (CHECK-2B section 15).
Used by tests/test_check2b_durable_runs.py and scripts/commission_check2b_
calgary.py. Never touches a real database.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta, timezone

TERMINAL = ("COMPLETE", "PARTIAL", "FAILED")
EXCLUDED = ("POST_AWARD_OBLIGATION", "BUYER_PROCESS", "INFORMATIONAL", "DEEMED_BY_SUBMISSION", "NOT_APPLICABLE")
CHECKABLE = ("SUBMISSION_RESPONSE_REQUIRED", "SUBMISSION_EVIDENCE_REQUIRED", "EVALUATION_RESPONSE")
STATUSES = ("ADDRESSED", "PARTIALLY_ADDRESSED", "NOT_ADDRESSED", "NOT_APPLICABLE", "NOT_VERIFIABLE_FROM_FILES",
            "HUMAN_REVIEW_REQUIRED")
SCOPES = CHECKABLE + ("PORTAL_NATIVE",) + EXCLUDED + ("HUMAN_REVIEW_REQUIRED",)
METHODS = ("SCOPE_GATE", "DETERMINISTIC", "MODEL", "DERIVED_FROM_LINKED_REQUIREMENTS")
EVENT_TYPES = ("RUN_CREATED", "RUN_STARTED", "BUYER_SCOPE_CLASSIFIED", "CANDIDATE_RETRIEVAL_COMPLETE",
               "DETERMINISTIC_ADJUDICATION_COMPLETE", "SEMANTIC_BATCH_STARTED", "SEMANTIC_BATCH_COMPLETED",
               "SEMANTIC_BATCH_FAILED", "EVIDENCE_ASSURANCE_COMPLETE", "RUN_COMPLETED", "RUN_PARTIAL",
               "RUN_FAILED")


def _jsonb(value):
    return None if value is None else json.loads(json.dumps(value, default=str))


class FakeCheckDB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
        self.runs: dict[int, dict] = {}
        self.results: dict[int, dict] = {}
        self.events: list[dict] = []
        self.batches: list[dict] = []
        self.adjudications: list[dict] = []
        self.evidence_links: list[dict] = []
        self.snapshots: dict[int, int] = {}              # snapshot id -> bid id
        self.evidence: dict[tuple, set] = {}             # (bid, snapshot) -> evidence ids
        self.usage_events: list[dict] = []
        self._next_run = 500
        self.start_calls = 0

    # -- persistence of the fake itself (fresh-process reopen) ------------
    def dump(self) -> dict:
        with self.lock:
            return {"runs": list(self.runs.values()), "results": list(self.results.values()),
                    "events": self.events, "batches": self.batches, "adjudications": self.adjudications,
                    "evidence_links": self.evidence_links,
                    "snapshots": {str(k): v for k, v in self.snapshots.items()},
                    "evidence": [{"bid_id": b, "snapshot_id": s, "ids": sorted(ids)}
                                 for (b, s), ids in self.evidence.items()]}

    @classmethod
    def load(cls, data: dict) -> "FakeCheckDB":
        f = cls()
        f.runs = {int(r["id"]): r for r in data["runs"]}
        f.results = {int(r["run_id"]): r for r in data["results"]}
        f.events, f.batches = data["events"], data["batches"]
        f.adjudications, f.evidence_links = data["adjudications"], data["evidence_links"]
        f.snapshots = {int(k): v for k, v in data["snapshots"].items()}
        f.evidence = {(e["bid_id"], e["snapshot_id"]): set(e["ids"]) for e in data["evidence"]}
        f._next_run = max(f.runs or [499]) + 1
        return f

    def now(self):
        return self.clock.isoformat()

    def tick(self, seconds=1):
        self.clock += timedelta(seconds=seconds)

    # -- seed data --------------------------------------------------------
    def add_fast_run(self, bid_id, run_id, status="COMPLETE"):
        self.runs[run_id] = {"id": run_id, "bid_id": bid_id, "analysis_mode": "FAST", "status": status,
                             "created_at": self.now(), "corpus_digest": f"corpus-{run_id}"}

    def add_snapshot(self, bid_id, snapshot_id, evidence_ids):
        self.snapshots[snapshot_id] = bid_id
        self.evidence[(bid_id, snapshot_id)] = set(evidence_ids)

    # -- reads -------------------------------------------------------------
    def get_analysis_run(self, run_id):
        r = self.runs.get(run_id)
        return copy.deepcopy(r) if r else None

    def get_check_runs(self, bid_id, *, limit=50):
        rows = [copy.deepcopy(r) for r in self.runs.values()
                if r["bid_id"] == bid_id and r["analysis_mode"] == "CHECK"]
        return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

    def get_check_run_events(self, run_id, *, after_sequence=0):
        return sorted((copy.deepcopy(e) for e in self.events
                       if e["run_id"] == run_id and e["sequence"] > after_sequence), key=lambda e: e["sequence"])

    def get_check_semantic_batches(self, run_id):
        return [copy.deepcopy(b) for b in self.batches if b["run_id"] == run_id]

    def get_check_adjudications(self, run_id):
        return sorted((copy.deepcopy(a) for a in self.adjudications if a["run_id"] == run_id),
                      key=lambda a: a["ordinal"])

    def get_analysis_result(self, run_id):
        r = self.results.get(run_id)
        return copy.deepcopy(r) if r else None

    def create_model_usage_event(self, event):
        self.usage_events.append(dict(event))
        return dict(event)

    # -- RPC: start_check_run ------------------------------------------------
    def start_check_run(self, bid_id, source_analysis_run_id, package_snapshot_id, input_fingerprint,
                        engine_version, *, created_by_user_id=None, retry=False, detail=None):
        with self.lock:
            self.start_calls += 1
            if None in (bid_id, source_analysis_run_id, package_snapshot_id, input_fingerprint, engine_version):
                raise RuntimeError("start_check_run: required argument missing")
            src = self.runs.get(source_analysis_run_id)
            if not src or src["bid_id"] != bid_id or src["analysis_mode"] != "FAST" or src["status"] != "COMPLETE":
                raise RuntimeError("start_check_run: source run is not a COMPLETE FAST run of bid")
            if self.snapshots.get(package_snapshot_id) != bid_id:
                raise RuntimeError("start_check_run: package snapshot does not belong to bid")
            if not self.evidence.get((bid_id, package_snapshot_id)):
                raise RuntimeError("start_check_run: package snapshot has no persisted submission evidence registry")
            mine = sorted((r for r in self.runs.values() if r["bid_id"] == bid_id and r["analysis_mode"] == "CHECK"),
                          key=lambda r: r["id"], reverse=True)
            active = [r for r in mine if r["status"] not in TERMINAL]
            if active:
                return {"outcome": "ACTIVE_RUN_EXISTS", "run": copy.deepcopy(active[0])}
            done = [r for r in mine if r["status"] == "COMPLETE" and r["input_fingerprint"] == input_fingerprint]
            if done:
                return {"outcome": "REUSED_COMPLETE", "run": copy.deepcopy(done[0])}
            if not retry:
                same = [r for r in mine if r["input_fingerprint"] == input_fingerprint]
                if same:
                    return {"outcome": "EXISTING_" + same[0]["status"], "run": copy.deepcopy(same[0])}
            run_id = self._next_run
            self._next_run += 1
            run = {"id": run_id, "bid_id": bid_id, "analysis_mode": "CHECK", "engine_version": engine_version,
                   "status": "QUEUED", "input_fingerprint": input_fingerprint,
                   "source_analysis_run_id": source_analysis_run_id, "source_package_snapshot_id": package_snapshot_id,
                   "corpus_digest": src.get("corpus_digest"), "created_by_user_id": created_by_user_id,
                   "created_at": self.now(), "started_at": None, "completed_at": None, "failed_at": None,
                   "failure_reason": None, "failure_detail": None, "telemetry": None, "last_progress_at": self.now()}
            self.runs[run_id] = run
            self.events.append({"run_id": run_id, "bid_id": bid_id, "sequence": 1, "event_type": "RUN_CREATED",
                                "batch_id": None, "status": "QUEUED", "duration_seconds": None,
                                "failure_summary": None, "detail": _jsonb(detail or {}), "occurred_at": self.now()})
            return {"outcome": "CREATED", "run": copy.deepcopy(run)}

    def _seq(self, run_id):
        return max((e["sequence"] for e in self.events if e["run_id"] == run_id), default=0) + 1

    def _check_run(self, run_id, bid_id, fn):
        run = self.runs.get(run_id)
        if not run or run["bid_id"] != bid_id or run["analysis_mode"] != "CHECK":
            raise RuntimeError(f"{fn}: run {run_id} is not a CHECK run of bid {bid_id}")
        return run

    # -- RPC: record_check_run_event -------------------------------------------
    def record_check_run_event(self, run_id, bid_id, event_type, *, batch_id=None, status=None,
                               duration_seconds=None, failure_summary=None, detail=None, batch_result=None):
        with self.lock:
            if event_type in ("RUN_CREATED", "RUN_COMPLETED", "RUN_PARTIAL", "RUN_FAILED"):
                raise RuntimeError(f"record_check_run_event: {event_type} is written only by start/finalize")
            if event_type not in EVENT_TYPES:
                raise RuntimeError("record_check_run_event: invalid event_type (check constraint)")
            run = self._check_run(run_id, bid_id, "record_check_run_event")
            if run["status"] in TERMINAL:
                raise RuntimeError(f"record_check_run_event: run {run_id} is terminal ({run['status']})")
            if len(json.dumps(detail or {}, default=str).encode()) > 4000:
                raise RuntimeError("check_run_events detail exceeds 4000 bytes (check constraint)")
            ev = {"run_id": run_id, "bid_id": bid_id, "sequence": self._seq(run_id), "event_type": event_type,
                  "batch_id": batch_id, "status": status, "duration_seconds": duration_seconds,
                  "failure_summary": (failure_summary or None) and failure_summary[:500],
                  "detail": _jsonb(detail or {}), "occurred_at": self.now()}
            if batch_result is not None:
                if event_type not in ("SEMANTIC_BATCH_COMPLETED", "SEMANTIC_BATCH_FAILED") or batch_id is None:
                    raise RuntimeError("record_check_run_event: batch result only with SEMANTIC_BATCH_*")
                eff = batch_result.get("effective_status")
                if eff not in TERMINAL:
                    raise RuntimeError("check_semantic_batches.effective_status check constraint")
                if (event_type == "SEMANTIC_BATCH_FAILED") != (eff == "FAILED"):
                    raise RuntimeError("record_check_run_event: event disagrees with effective batch status")
                allowed = self.evidence.get((bid_id, run["source_package_snapshot_id"]), set())
                ids = list(batch_result.get("candidate_evidence_ids") or []) + \
                    list((batch_result.get("alias_to_evidence") or {}).values())
                if any(e not in allowed for e in ids):
                    raise RuntimeError("record_check_run_event: batch references evidence outside bid snapshot")
                if any(b["run_id"] == run_id and b["batch_id"] == batch_id for b in self.batches):
                    raise RuntimeError("duplicate key (run_id, batch_id)")
                row = _jsonb(batch_result)
                row.update(run_id=run_id, bid_id=bid_id, package_snapshot_id=run["source_package_snapshot_id"],
                           batch_id=batch_id, created_at=self.now())
                self.batches.append(row)
            self.events.append(ev)
            run["status"] = "RUNNING"
            run["started_at"] = run["started_at"] or self.now()
            run["last_progress_at"] = self.now()
            return copy.deepcopy(ev)

    # -- RPC: finalize_check_run -------------------------------------------------
    def finalize_check_run(self, run_id, bid_id, status, *, result=None, adjudications=None, summary=None,
                           failure_reason=None, failure_detail=None, telemetry=None):
        with self.lock:
            if status not in TERMINAL:
                raise RuntimeError("finalize_check_run: invalid terminal status")
            if status in ("COMPLETE", "PARTIAL") and (result is None or not adjudications):
                raise RuntimeError(f"finalize_check_run: {status} requires a result and adjudications")
            if status == "COMPLETE" and (result or {}).get("run_integrity") != "COMPLETE":
                raise RuntimeError("finalize_check_run: result is not COMPLETE; refusing to mark run COMPLETE")
            if adjudications is not None and result is not None and \
                    len(adjudications) != int(((result.get("object_counts") or {}).get("total")) or -1):
                raise RuntimeError("finalize_check_run: adjudication count differs from buyer object count")
            run = self._check_run(run_id, bid_id, "finalize_check_run")
            if run["status"] in TERMINAL:
                raise RuntimeError(f"finalize_check_run: run {run_id} is already terminal ({run['status']})")
            mine = [b for b in self.batches if b["run_id"] == run_id]
            if status == "COMPLETE":
                if any(b["effective_status"] != "COMPLETE" for b in mine):
                    raise RuntimeError("finalize_check_run: a semantic batch is not COMPLETE; refusing COMPLETE")
                if len(mine) != int(result.get("planned_semantic_batches", -1)):
                    raise RuntimeError("finalize_check_run: persisted batches do not match the plan")
                if any(r is not run and r["analysis_mode"] == "CHECK" and r["status"] == "COMPLETE"
                       and r["bid_id"] == bid_id and r["input_fingerprint"] == run["input_fingerprint"]
                       for r in self.runs.values()):
                    raise RuntimeError("unique violation idx_analysis_runs_check_complete_fingerprint")
            snap = run["source_package_snapshot_id"]
            allowed = self.evidence.get((bid_id, snap), set())
            staged_adj, staged_links, seen = [], [], set()
            for ordinal, raw in enumerate(adjudications or [], 1):
                a = _jsonb(raw)
                oid = a.get("buyer_object_id")
                if not oid or oid in seen:
                    raise RuntimeError("duplicate key (run_id, buyer_object_id)")
                seen.add(oid)
                if a.get("status") not in STATUSES or a.get("assurance_scope") not in SCOPES \
                        or a.get("deterministic_or_model") not in METHODS \
                        or a.get("buyer_object_type") not in ("CANONICAL_REQUIREMENT", "SCOPED_EVALUATION_CRITERION") \
                        or a.get("buyer_expectation") is None:
                    raise RuntimeError(f"check_adjudications vocabulary / not-null violation for {oid}")
                if a["status"] in ("ADDRESSED", "PARTIALLY_ADDRESSED") and not a.get("evidence_ids"):
                    raise RuntimeError(f"check_adjudications: positive verdict without evidence ({oid})")
                if a["assurance_scope"] in EXCLUDED and a["status"] != "NOT_APPLICABLE":
                    raise RuntimeError(f"check_adjudications: excluded scope with a verdict ({oid})")
                if a["status"] == "NOT_ADDRESSED" and a["assurance_scope"] not in CHECKABLE:
                    raise RuntimeError(f"check_adjudications: NOT_ADDRESSED on non-response scope ({oid})")
                if a["deterministic_or_model"] == "MODEL" and not a.get("batch_id"):
                    raise RuntimeError(f"check_adjudications: model verdict without batch ({oid})")
                row = dict(a)
                row["adjudication_method"] = row.pop("deterministic_or_model")
                row.update(run_id=run_id, bid_id=bid_id, package_snapshot_id=snap, ordinal=ordinal,
                           created_at=self.now())
                staged_adj.append(row)
                kinds = [(e, "VERDICT") for e in a.get("evidence_ids") or []]
                for grp in ("addressed_elements", "missing_elements", "unverifiable_elements"):
                    for el in a.get(grp) or []:
                        kinds.extend((e, "ELEMENT") for e in (el.get("evidence_ids") or []))
                linked = set()
                for eid, kind in kinds:
                    if eid in linked:
                        continue
                    if eid not in allowed:   # FK (bid_id, package_snapshot_id, evidence_id)
                        raise RuntimeError(f"insert or update on table check_adjudication_evidence violates "
                                           f"foreign key constraint: evidence {eid!r} not in bid {bid_id} "
                                           f"snapshot {snap}")
                    linked.add(eid)
                    staged_links.append({"run_id": run_id, "bid_id": bid_id, "package_snapshot_id": snap,
                                         "buyer_object_id": oid, "evidence_id": eid, "reference_kind": kind})
            # -- commit (all or nothing) --
            if result is not None:
                self.results[run_id] = {"run_id": run_id, "bid_id": bid_id,
                                        "structured_intelligence": _jsonb(summary or {}), "fact_origins": {},
                                        "check_coverage_result": _jsonb(result)}
            self.adjudications.extend(staged_adj)
            self.evidence_links.extend(staged_links)
            self.events.append({"run_id": run_id, "bid_id": bid_id, "sequence": self._seq(run_id),
                                "event_type": {"COMPLETE": "RUN_COMPLETED", "PARTIAL": "RUN_PARTIAL"}.get(
                                    status, "RUN_FAILED"),
                                "batch_id": None, "status": status, "duration_seconds": None,
                                "failure_summary": failure_reason, "detail": _jsonb(summary or {}),
                                "occurred_at": self.now()})
            run.update(status=status, failure_reason=failure_reason or run["failure_reason"],
                       failure_detail=_jsonb(failure_detail) or run["failure_detail"],
                       telemetry=_jsonb(telemetry) or run["telemetry"], last_progress_at=self.now(),
                       started_at=run["started_at"] or self.now())
            run["failed_at" if status == "FAILED" else "completed_at"] = self.now()
            return copy.deepcopy(run)

    # -- wiring --------------------------------------------------------------
    DB_FUNCTIONS = ("get_analysis_run", "get_check_runs", "get_check_run_events", "get_check_semantic_batches",
                    "get_check_adjudications", "get_analysis_result", "start_check_run",
                    "record_check_run_event", "finalize_check_run", "create_model_usage_event")

    def install(self, setattr_fn):
        """setattr_fn(module, name, value) -- pytest monkeypatch.setattr or builtins setattr."""
        import database
        for name in self.DB_FUNCTIONS:
            setattr_fn(database, name, getattr(self, name))
