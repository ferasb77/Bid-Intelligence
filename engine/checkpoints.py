"""Stage checkpoints: every successful model answer of a run is kept, so a run
that fails, is stopped by its budget or is re-run resumes from what was
already paid for instead of starting again.

A checkpoint is content-addressed: its key is the SHA-256 of the exact model
configuration (provider, model, effort), system prompt, user prompt, output
schema and output limit. A changed document, prompt, schema or model therefore
never reuses an old answer -- and every stage downstream of a change sees a
different prompt, so it is re-run too. Answers are stored verbatim; nothing is
repaired or merged, and every reused answer goes through the same source
verification as a fresh one.

Checkpoints live in the bid's own storage prefix
({bid_id}/engine/{run_id}/stages/), next to the run's result.json and PDFs,
and are only ever read for runs of the SAME bid (constraint C1). No database
table or column is added."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading

from engine.providers import Analyst, UsageLedger, _flat


class CheckpointStore:
    """get(key) -> dict | None; put(key, value). Implementations never raise:
    a store that cannot be read or written is a cache miss, not a failure."""

    def get(self, key: str) -> dict | None:  # pragma: no cover - interface
        return None

    def put(self, key: str, value: dict) -> None:  # pragma: no cover - interface
        return None


class MemoryStore(CheckpointStore):
    def __init__(self, data: dict | None = None):
        self.data = data if data is not None else {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            v = self.data.get(key)
        return copy.deepcopy(v) if v is not None else None

    def put(self, key, value):
        with self._lock:
            self.data[key] = copy.deepcopy(value)


class StorageStore(CheckpointStore):
    """Checkpoints of one engine run in the bid-documents bucket, reading also
    the checkpoints of earlier runs of the same bid (resume / FAST -> FULL
    reuse). Writes: {bid}/engine/{run}/stages/<key>.json plus a manifest of
    the keys, so earlier runs can be searched without listing the bucket."""

    def __init__(self, bid_id: int, run_id: int, earlier_run_ids: list[int] | None = None, db=None):
        self.bid_id, self.run_id = int(bid_id), int(run_id)
        self.earlier = [int(r) for r in earlier_run_ids or [] if int(r) != int(run_id)]
        self._db = db
        self._lock = threading.Lock()
        self._own: set[str] = set()
        self._index: dict[str, int] | None = None     # key -> run id that holds it
        self.reused_from: set[int] = set()

    def db(self):
        if self._db is None:
            import database
            self._db = database
        return self._db

    def _prefix(self, run_id: int) -> str:
        return f"{self.bid_id}/engine/{int(run_id)}/stages"

    def _load_index(self) -> dict[str, int]:
        if self._index is None:
            idx: dict[str, int] = {}
            for rid in self.earlier:                    # newest first: the first holder wins
                try:
                    raw = self.db().download_file(f"{self._prefix(rid)}/manifest.json")
                    keys = json.loads(raw.decode("utf-8")).get("keys") if raw else []
                except Exception:
                    keys = []
                for k in keys or []:
                    idx.setdefault(k, rid)
            self._index = idx
        return self._index

    def get(self, key):
        with self._lock:
            rid = self.run_id if key in self._own else self._load_index().get(key)
        if rid is None:
            return None
        try:
            raw = self.db().download_file(f"{self._prefix(rid)}/{key}.json")
            value = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            return None
        if value is not None and rid != self.run_id:
            self.reused_from.add(rid)
        return value

    def put(self, key, value):
        try:
            self.db().upload_json_object(f"{self._prefix(self.run_id)}/{key}.json", value)
            with self._lock:
                self._own.add(key)
                keys = sorted(self._own)
            self.db().upload_json_object(f"{self._prefix(self.run_id)}/manifest.json", {"keys": keys})
        except Exception:
            pass


class DirStore(CheckpointStore):
    """Checkpoints as JSON files in a local directory (scripts/engine_run.py)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(path, exist_ok=True)

    def get(self, key):
        try:
            with open(os.path.join(self.path, f"{key}.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def put(self, key, value):
        try:
            tmp = os.path.join(self.path, f"{key}.json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(value, fh, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.path, f"{key}.json"))
        except Exception:
            pass


def checkpoint_key(analyst: Analyst, system: str, user, schema: dict, max_tokens: int) -> str:
    blob = json.dumps({"analyst": {k: v for k, v in analyst.describe().items() if k != "name"},
                       "system": system, "user": _flat(user), "schema": schema, "max_tokens": max_tokens},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CachingAnalyst(Analyst):
    """Wraps an analyst: an answer already checkpointed for exactly this
    request is returned at $0 (counted in the ledger's by_stage
    `from_checkpoint`); otherwise the request goes to the wrapped analyst and
    its successful answer is checkpointed. Synthetic analysts are never
    cached, so a synthetic answer can never be served to a real run."""

    def __init__(self, inner: Analyst, store: CheckpointStore):
        super().__init__(name=inner.name, provider=inner.provider, model=inner.model, synthetic=inner.synthetic,
                         config=inner.config)
        self.inner, self.store = inner, store

    def describe(self) -> dict:
        return self.inner.describe()

    def check_allowed(self, data_class: str) -> None:
        self.inner.check_allowed(data_class)

    def _target(self, purpose: str) -> Analyst:
        route = getattr(self.inner, "route", None)
        return route(purpose) if route else self.inner

    def call_json(self, system, user, schema, *, purpose, ledger: UsageLedger, data_class, max_tokens=32000):
        if self.inner.synthetic:
            return self.inner.call_json(system, user, schema, purpose=purpose, ledger=ledger, data_class=data_class,
                                        max_tokens=max_tokens)
        self.check_allowed(data_class)
        key = checkpoint_key(self._target(purpose), system, user, schema, max_tokens)
        hit = self.store.get(key)
        if hit is not None and isinstance(hit.get("data"), dict):
            ledger.add_cached(purpose)
            return hit["data"]
        data = self.inner.call_json(system, user, schema, purpose=purpose, ledger=ledger, data_class=data_class,
                                    max_tokens=max_tokens)
        self.store.put(key, {"purpose": purpose, "data": data})
        return data


def with_checkpoints(analyst: Analyst | None, store: CheckpointStore | None) -> Analyst | None:
    if analyst is None or store is None or isinstance(analyst, CachingAnalyst):
        return analyst
    return CachingAnalyst(analyst, store)
