"""Organization Owner/Admin bid deletion (migration 026, tenancy.delete_bid_for_organization)."""
import pathlib
import re
from unittest import mock

import pytest

import tenancy

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = (ROOT / "migrations" / "026_admin_bid_deletion.sql").read_text(encoding="utf-8")
ORG, USER, OTHER = "org-1", "user-1", "user-2"


class FakeStorage:
    def __init__(self, fail=()):
        self.removed, self.fail = [], set(fail)

    def from_(self, bucket):
        return self

    def remove(self, names):
        if set(names) & self.fail:
            raise RuntimeError("storage unavailable")
        self.removed.extend(names)


class FakeQuery:
    def __init__(self, sb, table):
        self.sb, self.table, self.op, self.filters, self.payload = sb, table, "select", {}, None

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def in_(self, k, v):
        self.filters[k] = set(v)
        return self

    def order(self, *_ , **__):
        return self

    def delete(self):
        self.op = "delete"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def _match(self, row):
        for k, v in self.filters.items():
            if isinstance(v, set):
                if row.get(k) not in v:
                    return False
            elif row.get(k) != v:
                return False
        return True

    def execute(self):
        rows = self.sb.tables.setdefault(self.table, [])
        hit = [r for r in rows if self._match(r)]
        if self.op == "delete":
            self.sb.tables[self.table] = [r for r in rows if r not in hit]
        elif self.op == "update":
            for r in hit:
                r.update(self.payload)
        return mock.Mock(data=[dict(r) for r in hit])


class FakeService:
    def __init__(self, rpc_result=None, rpc_error=None, fail=()):
        self.storage = FakeStorage(fail)
        self.tables = {"analysis_runs": [], "bid_storage_cleanup": []}
        self.rpc_calls = []
        self.rpc_result, self.rpc_error = rpc_result, rpc_error

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        if self.rpc_error:
            raise self.rpc_error
        return mock.Mock(execute=lambda: mock.Mock(data=self.rpc_result))


@pytest.fixture
def session():
    ctx = tenancy.AuthContext(user_id=USER, email="a@example.com", organization_id=ORG,
                              organization_name="Org", role="admin")
    tenancy.set_session_principal_provider(lambda: ctx)
    with mock.patch.object(tenancy, "revalidate_session_access",
                           return_value=tenancy.SessionAccessCheck(ok=True, role="admin")):
        yield ctx
    tenancy.set_session_principal_provider(None)


def _queued(sb, *names):
    for i, n in enumerate(names, 1):
        sb.tables["bid_storage_cleanup"].append({"id": i, "organization_id": ORG, "bid_id": 7,
                                                 "bucket_id": "bid-documents", "object_name": n, "attempts": 0})
    return list(range(1, len(names) + 1))


def test_only_owner_and_admin_roles_may_delete():
    assert tenancy.can_delete_bids("owner") and tenancy.can_delete_bids("admin")
    assert not tenancy.can_delete_bids("member")
    assert not tenancy.can_delete_bids(None)
    assert set(tenancy.BID_DELETION_ROLES) <= set(tenancy.VALID_ROLES)


def test_authorized_deletion_removes_the_bids_storage_objects(session):
    sb = FakeService()
    ids = _queued(sb, "7/a.pdf", "7/analysis_reports/3.pdf")
    sb.rpc_result = {"ok": True, "title": "T", "reference": "R-1", "cleanup_ids": ids,
                     "storage_objects": ["7/a.pdf", "7/analysis_reports/3.pdf"]}
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb), \
            mock.patch.object(tenancy.db, "get_client", return_value=sb):
        out = tenancy.delete_bid_for_organization(7, ORG, USER)
    assert sb.rpc_calls == [("delete_bid_as_organization_admin",
                             {"p_bid_id": 7, "p_organization_id": ORG, "p_actor_user_id": USER})]
    assert sorted(sb.storage.removed) == ["7/a.pdf", "7/analysis_reports/3.pdf"]
    assert sb.tables["bid_storage_cleanup"] == []
    assert out == {"bid_id": 7, "title": "T", "reference": "R-1", "storage_removed": 2, "storage_pending": 0}


def test_storage_failure_is_recorded_and_reported_not_hidden(session):
    sb = FakeService(fail={"7/b.pdf"})
    ids = _queued(sb, "7/a.pdf", "7/b.pdf")
    sb.rpc_result = {"ok": True, "title": "T", "reference": None, "cleanup_ids": ids, "storage_objects": []}
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb), \
            mock.patch.object(tenancy.db, "get_client", return_value=sb):
        out = tenancy.delete_bid_for_organization(7, ORG, USER)
    assert out["storage_removed"] == 1 and out["storage_pending"] == 1
    left = sb.tables["bid_storage_cleanup"]
    assert [r["object_name"] for r in left] == ["7/b.pdf"]
    assert left[0]["attempts"] >= 1 and "storage unavailable" in left[0]["last_error"]
    # a later attempt (e.g. the next deletion) removes it once Storage works
    sb.storage.fail = set()
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb):
        assert tenancy.process_bid_storage_cleanup(ORG) == {"removed": 1, "pending": 0}
    assert sb.tables["bid_storage_cleanup"] == []


@pytest.mark.parametrize("reason", ["not_authorized", "not_found", "analysis_in_progress",
                                    "used_by_organizational_memory"])
def test_refusals_change_nothing(session, reason):
    sb = FakeService(rpc_result={"ok": False, "reason": reason})
    _queued(sb, "9/keep.pdf")
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb), \
            mock.patch.object(tenancy.db, "get_client", return_value=sb):
        with pytest.raises(tenancy.BidDeletionError) as err:
            tenancy.delete_bid_for_organization(7, ORG, USER)
    assert err.value.reason == reason and str(err.value)
    assert sb.storage.removed == [] and len(sb.tables["bid_storage_cleanup"]) == 1


def test_database_failure_is_a_clean_error(session):
    sb = FakeService(rpc_error=RuntimeError("connection reset"))
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb), \
            mock.patch.object(tenancy.db, "get_client", return_value=sb):
        with pytest.raises(tenancy.BidDeletionError) as err:
            tenancy.delete_bid_for_organization(7, ORG, USER)
    assert err.value.reason == "failed" and "Nothing was changed" in str(err.value)
    assert sb.storage.removed == []


def test_actor_must_be_the_signed_in_user(session):
    sb = FakeService(rpc_result={"ok": True})
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb):
        with pytest.raises(tenancy.SessionAccessRevokedError):
            tenancy.delete_bid_for_organization(7, ORG, OTHER)
    assert sb.rpc_calls == []


def test_session_for_another_organization_is_denied(session):
    sb = FakeService(rpc_result={"ok": True})
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb):
        with pytest.raises(tenancy.SessionAccessRevokedError):
            tenancy.delete_bid_for_organization(7, "org-2", USER)
    assert sb.rpc_calls == []


def test_running_buyer_research_blocks_deletion(session):
    sb = FakeService(rpc_result={"ok": True})
    sb.tables["analysis_runs"] = [{"id": 5, "bid_id": 7, "analysis_mode": "FULL"}]
    import buyer_research
    with mock.patch.object(tenancy.db, "get_service_client", return_value=sb), \
            mock.patch.object(tenancy.db, "get_client", return_value=sb), \
            mock.patch.object(buyer_research, "load", return_value={"status": "RUNNING"}):
        with pytest.raises(tenancy.BidDeletionError) as err:
            tenancy.delete_bid_for_organization(7, ORG, USER)
    assert err.value.reason == "research_in_progress" and sb.rpc_calls == []


# ── migration 026: the database enforces the same rules ─────────────────

def _fn(name):
    m = re.search(rf"create or replace function public\.{name}\(.*?\n\$\$;", MIGRATION, re.S)
    assert m, name
    return m.group(0)


def test_deletion_rpc_is_service_role_only_and_checks_role_org_and_state():
    body = _fn("delete_bid_as_organization_admin")
    assert "security definer" in body
    assert "user_account_is_active(p_actor_user_id)" in body
    assert "v_role not in ('owner', 'admin')" in body
    assert "b.organization_id = p_organization_id" in body and "for update" in body
    assert "status not in ('COMPLETE', 'PARTIAL', 'FAILED')" in body
    assert "organizational_memory_items" in body
    assert re.search(r"revoke all on function public\.delete_bid_as_organization_admin\(bigint, uuid, uuid\) "
                     r"from public, anon, authenticated;", MIGRATION)
    assert re.search(r"grant execute on function public\.delete_bid_as_organization_admin\(bigint, uuid, uuid\) "
                     r"to service_role;", MIGRATION)


def test_history_guards_only_yield_to_whole_bid_deletion():
    for name in ("full_analysis_reject_mutation", "check_run_reject_mutation",
                 "prevent_applied_change_mutation", "prevent_applied_review_mutation",
                 "prevent_resolved_conflict_mutation", "prevent_applied_review_document_mutation"):
        body = _fn(name)
        assert "if tg_op = 'DELETE' and public.bid_deletion_permits(" in body, name
        assert "raise exception" in body, name
    assert "set_config('bid_intelligence.deleting_bid_id', p_bid_id::text, true)" in _fn(
        "delete_bid_as_organization_admin")


def test_cleanup_queue_is_not_reachable_by_api_roles():
    assert "alter table public.bid_storage_cleanup enable row level security" in MIGRATION
    assert "revoke all on table public.bid_storage_cleanup from public, anon, authenticated" in MIGRATION


def test_directory_shows_delete_only_to_owner_and_admin_and_requires_typed_confirmation():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    page = src[src.index("def _render_bid_delete_confirmation"):src.index("# PAGE: NEW BID")]
    assert "can_delete = _tenancy.can_delete_bids(_ctx.role)" in page
    assert 'if can_delete and c5.button("🗑 Delete"' in page
    assert 'disabled=typed.strip() != "DELETE"' in page
    assert "_tenancy.delete_bid_for_organization(int(target[\"id\"]), _ctx.organization_id, _ctx.user_id)" in page
    assert "delete_bid(" not in src.replace("delete_bid_for_organization(", "")
