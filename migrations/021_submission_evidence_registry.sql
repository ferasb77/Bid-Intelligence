-- ═══════════════════════════════════════════════════════════════════════════
-- 021_submission_evidence_registry.sql -- CHECK-1: Package-Aware Proposal
-- Assurance Foundation (bidder-side canonical submission package + the ONE
-- shared bidder-evidence registry future CHECK stages reference).
--
-- STATUS: amended in place BEFORE first application by CHECK-1.1 (real
-- Calgary 26-1603 commissioning) and then applied/commissioned by that
-- same task. The CHECK-1.1 amendment adds logical-artifact /
-- representation columns to submission_documents (a real bidder package
-- carries the same logical item as DOCX + PDF, re-saved workbook copies,
-- byte-identical copies inside a nested archive and earlier drafts --
-- these must be LINKED, never double-counted) plus duplicate_of /
-- unusable_reason, which the Python payload always carried but this file
-- had no column for.
--
-- Purely additive: creates two tables and one RPC. Does not alter, backfill
-- or re-grant anything existing. Does not touch requirements (buyer-side
-- canonical procurement truth), proposal_intelligence_* result tables, or
-- the historical section_drafts table.
--
-- ── Reuse before new tables ─────────────────────────────────────────────
-- * PACKAGE IDENTITY is reused, not duplicated: proposal_package_snapshots
--   (migration 015) already stores one immutable row per exact submitted
--   package (package_digest = proposal_intelligence.compute_package_digest
--   over extractor.build_report_manifest -- the SAME digest
--   submission_package.build_submission_package computes). Both new tables
--   hang off that row via a COMPOSITE (id, bid_id) foreign key, so a
--   document/evidence row can never point at another bid's package.
-- * proposal_package_snapshots.manifest cannot hold this: it is the slim
--   report-safe per-file projection, deliberately free of content; the
--   evidence registry is per-item content + exact location + structured
--   value, potentially hundreds of rows per package.
-- * proposal_intelligence_findings / proposal_requirement_assessments are
--   immutable OUTPUTS of one analysis run (advisory intelligence). Bidder
--   evidence is INPUT observed in submitted files, not analysis -- storing
--   it there would blur evidence and intelligence (a constitutional
--   separation in this repo).
--
-- ── Tenancy ──────────────────────────────────────────────────────────────
-- bid_id-direct RLS via can_access_bid (same as every bid-owned table since
-- migration 008), authenticated SELECT only, no authenticated/anon write
-- policy -- only service_role, in practice only through
-- create_submission_evidence_bundle() below. evidence_id is unique per
-- (bid_id, package snapshot) AND already folds bid_id into its own sha256 derivation
-- (submission_package.derive_evidence_id), so an id can never be replayed
-- under another bid.
--
-- ── Write-once ───────────────────────────────────────────────────────────
-- Rows are immutable observations of exact bytes (content_hash). There is
-- no UPDATE path; a re-submission is a new package snapshot with new rows.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists submission_documents (
    id                          bigserial primary key,
    bid_id                      bigint not null references bids(id) on delete cascade,
    package_snapshot_id         bigint not null,
    submission_document_id      text not null,          -- extractor file_id
    content_hash                text not null,
    filename                    text not null,
    package_path                text not null,
    file_type                   text not null,
    lifecycle_status            text not null
                                 check (lifecycle_status in ('extracted', 'failed', 'unsupported', 'rejected', 'duplicate')),
    included                    boolean not null,
    document_role               text not null
                                 check (document_role in (
                                     'TECHNICAL_PROPOSAL', 'PRICING_FORM', 'SUBMISSION_FORM', 'MULTI_PARTY_FORM',
                                     'SOCIAL_PROCUREMENT_RESPONSE', 'CERTIFICATE', 'EVIDENCE_ATTACHMENT', 'RESUME',
                                     'ORGANIZATION_CHART', 'SUPPORTING_DOCUMENT', 'UNKNOWN')),
    role_confidence             text not null check (role_confidence in ('HIGH', 'MEDIUM', 'LOW')),
    role_basis                  text not null,
    secondary_roles             jsonb not null default '[]'::jsonb,
    parse_status                text not null
                                 check (parse_status in ('PARSED', 'FAILED', 'UNSUPPORTED', 'REJECTED', 'DUPLICATE')),
    page_count                  integer,
    sheets                      jsonb not null default '[]'::jsonb,
    sections                    jsonb not null default '[]'::jsonb,
    evidence_count              integer not null default 0,
    duplicate_of                text,                   -- extractor byte-identical duplicate source
    unusable_reason             text,
    logical_artifact_id         text not null,          -- one logical submitted item
    representation_relationship text not null default 'AUTHORITATIVE'
                                 check (representation_relationship in (
                                     'AUTHORITATIVE', 'ALTERNATE_REPRESENTATION', 'SUPERSEDED_OR_DRAFT_VARIANT',
                                     'TEMPLATE_VARIANT', 'BYTE_IDENTICAL_DUPLICATE')),
    representation_of           text,                   -- the AUTHORITATIVE member's submission_document_id
    representation_basis        text,
    contract_version            text not null,
    created_at                  timestamptz not null default now(),
    -- exactly the AUTHORITATIVE member has no representation_of
    check ((representation_relationship = 'AUTHORITATIVE') = (representation_of is null)),
    unique (package_snapshot_id, submission_document_id),
    unique (id, bid_id),
    unique (bid_id, package_snapshot_id, submission_document_id),
    foreign key (package_snapshot_id, bid_id)
        references proposal_package_snapshots (id, bid_id) on delete cascade
);

create index if not exists idx_submission_documents_bid_snapshot
    on submission_documents (bid_id, package_snapshot_id);

-- A representation / duplicate link can only point at a document of the
-- SAME bid and the SAME package snapshot (deferred: one bundle inserts in
-- any order inside its single transaction).
alter table submission_documents
    add constraint submission_documents_representation_of_fkey
    foreign key (bid_id, package_snapshot_id, representation_of)
    references submission_documents (bid_id, package_snapshot_id, submission_document_id)
    deferrable initially deferred;
alter table submission_documents
    add constraint submission_documents_duplicate_of_fkey
    foreign key (bid_id, package_snapshot_id, duplicate_of)
    references submission_documents (bid_id, package_snapshot_id, submission_document_id)
    deferrable initially deferred;

-- One authoritative member per logical artifact per package snapshot.
create unique index if not exists uq_submission_documents_authoritative_artifact
    on submission_documents (package_snapshot_id, logical_artifact_id)
    where representation_relationship = 'AUTHORITATIVE';

create table if not exists submission_evidence_items (
    id                          bigserial primary key,
    bid_id                      bigint not null references bids(id) on delete cascade,
    package_snapshot_id         bigint not null,
    submission_document_id      text not null,
    evidence_id                 text not null,
    document_role               text not null,
    kind                        text not null
                                 check (kind in ('SECTION_TEXT', 'TABLE_ROW', 'FORM_FIELD', 'CHECKBOX',
                                                 'SHEET_ROW', 'SHEET_CELL')),
    location                    jsonb not null default '{}'::jsonb,
    content                     text not null,
    structured_value            jsonb,
    provenance                  jsonb not null,
    created_at                  timestamptz not null default now(),
    -- evidence_id is deterministic over (bid, document occurrence, kind,
    -- locator), so an unchanged file re-submitted in a LATER package
    -- snapshot of the same bid legitimately yields the same id: uniqueness
    -- is per snapshot (CHECK-1.1; a bare (bid_id, evidence_id) key would
    -- make every re-submission that keeps one file fail to persist).
    unique (bid_id, package_snapshot_id, evidence_id),
    -- An evidence row must belong to a document of the SAME bid and the
    -- SAME package snapshot -- enforced by the database, not by convention.
    foreign key (bid_id, package_snapshot_id, submission_document_id)
        references submission_documents (bid_id, package_snapshot_id, submission_document_id) on delete cascade,
    foreign key (package_snapshot_id, bid_id)
        references proposal_package_snapshots (id, bid_id) on delete cascade
);

create index if not exists idx_submission_evidence_items_doc
    on submission_evidence_items (bid_id, package_snapshot_id, submission_document_id);
create index if not exists idx_submission_evidence_items_role
    on submission_evidence_items (bid_id, package_snapshot_id, document_role);

alter table submission_documents enable row level security;
alter table submission_evidence_items enable row level security;

create policy submission_documents_select_bid_access
    on public.submission_documents for select to authenticated
    using (public.can_access_bid(bid_id));

create policy submission_evidence_items_select_bid_access
    on public.submission_evidence_items for select to authenticated
    using (public.can_access_bid(bid_id));

-- Deliberately no INSERT/UPDATE/DELETE policy for authenticated/anon.

-- ═══════════════════════════════════════════════════════════════════════════
-- create_submission_evidence_bundle -- atomic, idempotent persistence of one
-- package's documents + evidence registry (payload shape:
-- submission_package.build_persistence_payload()).
-- ═══════════════════════════════════════════════════════════════════════════
-- bid_id is trusted ONLY from p_bid_id: every inserted row is forced to it,
-- and the snapshot must belong to that bid. Idempotent: if this snapshot
-- already has documents, the existing rows are returned untouched (write-
-- once; never an UPDATE). One PL/pgSQL call = one transaction, so a failure
-- part-way leaves nothing behind.
create or replace function public.create_submission_evidence_bundle(
    p_bid_id bigint,
    p_package_snapshot_id bigint,
    p_contract_version text,
    p_documents jsonb,
    p_evidence_items jsonb
) returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    v_existing integer;
    v_doc jsonb;
    v_item jsonb;
    v_count integer := 0;
begin
    if p_bid_id is null or p_package_snapshot_id is null or p_contract_version is null then
        raise exception 'create_submission_evidence_bundle: bid_id, package_snapshot_id and contract_version are required';
    end if;
    if jsonb_typeof(coalesce(p_documents, 'null'::jsonb)) <> 'array'
       or jsonb_typeof(coalesce(p_evidence_items, 'null'::jsonb)) <> 'array' then
        raise exception 'create_submission_evidence_bundle: documents and evidence_items must be json arrays';
    end if;
    if not exists (select 1 from public.proposal_package_snapshots
                   where id = p_package_snapshot_id and bid_id = p_bid_id) then
        raise exception 'create_submission_evidence_bundle: snapshot % does not belong to bid %', p_package_snapshot_id, p_bid_id;
    end if;

    perform pg_advisory_xact_lock(hashtext('submission_evidence_bundle:' || p_bid_id::text || ':' || p_package_snapshot_id::text));

    select count(*) into v_existing from public.submission_documents
    where bid_id = p_bid_id and package_snapshot_id = p_package_snapshot_id;
    if v_existing > 0 then
        return 0;
    end if;

    for v_doc in select * from jsonb_array_elements(p_documents) loop
        insert into public.submission_documents (
            bid_id, package_snapshot_id, submission_document_id, content_hash, filename, package_path,
            file_type, lifecycle_status, included, document_role, role_confidence, role_basis,
            secondary_roles, parse_status, page_count, sheets, sections, evidence_count,
            duplicate_of, unusable_reason, logical_artifact_id, representation_relationship,
            representation_of, representation_basis, contract_version
        ) values (
            p_bid_id, p_package_snapshot_id, v_doc->>'submission_document_id', v_doc->>'content_hash',
            v_doc->>'filename', v_doc->>'package_path', v_doc->>'file_type', v_doc->>'lifecycle_status',
            coalesce((v_doc->>'included')::boolean, false), v_doc->>'document_role', v_doc->>'role_confidence',
            v_doc->>'role_basis', coalesce(v_doc->'secondary_roles', '[]'::jsonb), v_doc->>'parse_status',
            nullif(v_doc->>'page_count', '')::integer, coalesce(v_doc->'sheets', '[]'::jsonb),
            coalesce(v_doc->'sections', '[]'::jsonb), coalesce((v_doc->>'evidence_count')::integer, 0),
            v_doc->>'duplicate_of', v_doc->>'unusable_reason',
            coalesce(v_doc->>'logical_artifact_id', v_doc->>'submission_document_id'),
            coalesce(v_doc->>'representation_relationship', 'AUTHORITATIVE'),
            v_doc->>'representation_of', v_doc->>'representation_basis',
            p_contract_version
        );
    end loop;

    for v_item in select * from jsonb_array_elements(p_evidence_items) loop
        insert into public.submission_evidence_items (
            bid_id, package_snapshot_id, submission_document_id, evidence_id, document_role, kind,
            location, content, structured_value, provenance
        ) values (
            p_bid_id, p_package_snapshot_id, v_item->>'submission_document_id', v_item->>'evidence_id',
            v_item->>'document_role', v_item->>'kind', coalesce(v_item->'location', '{}'::jsonb),
            coalesce(v_item->>'content', ''), v_item->'structured_value', v_item->'provenance'
        );
        v_count := v_count + 1;
    end loop;

    return v_count;
end;
$$;

revoke all on function public.create_submission_evidence_bundle(bigint, bigint, text, jsonb, jsonb) from public;
revoke all on function public.create_submission_evidence_bundle(bigint, bigint, text, jsonb, jsonb) from anon, authenticated;
grant execute on function public.create_submission_evidence_bundle(bigint, bigint, text, jsonb, jsonb) to service_role;
