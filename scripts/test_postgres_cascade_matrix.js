/**
 * scripts/test_postgres_cascade_matrix.js
 *
 * Deterministic proof of PostgreSQL cascade ordering and immutability trigger behavior
 * for Migration 024 and Migration 025. Runs against real PostgreSQL (via PGlite WebAssembly engine).
 *
 * Matrix covers:
 * A. Full Analysis event direct DELETE (parent bid exists) -> FAIL
 * B. Full Analysis event UPDATE -> FAIL
 * C. Deleting parent bid with Full Analysis events -> PASS (all event rows cascade away)
 * D. CHECK event direct DELETE -> FAIL
 * E. Deleting parent bid with CHECK events -> PASS
 * F. Applied procurement_change direct DELETE -> FAIL
 * G. Deleting governed parent bid with applied changes -> PASS
 * H. Applied procurement review direct DELETE -> FAIL
 * I. Applied review documents:
 *    I.1. Direct DELETE review_document from applied review with live bid -> FAIL
 *    I.2. UPDATE review_document on applied review -> FAIL
 *    I.3. Direct DELETE source document referenced by applied review with live bid -> FAIL
 *    I.4. Deleting governed parent bid with applied review/documents -> PASS (all cascaded away)
 * J. Resolved procurement conflict direct DELETE -> FAIL
 * K. Deleting governed parent bid with resolved conflict -> PASS
 * L. Deleting governed parent bid with procurement_changes.source_document_id populated -> PASS
 * M. Deleting governed parent bid with procurement_conflicts.target_requirement_id populated -> PASS
 * N. Deleting governed parent bid with procurement_changes.target_requirement_id populated -> PASS
 * O. Bid 1522-equivalent governed graph -> whole parent deletion succeeds in isolated fixture -> PASS
 */

let PGlite;
try {
    PGlite = require('@electric-sql/pglite').PGlite;
} catch (e) {
    try {
        const scratchPath = 'C:/Users/feras/.gemini/antigravity/brain/4bd068fe-671b-4636-8f78-8930bb1b57ca/scratch/node_modules/@electric-sql/pglite';
        PGlite = require(scratchPath).PGlite;
    } catch (e2) {
        console.error('Could not load @electric-sql/pglite. Ensure it is installed in node_modules.');
        process.exit(1);
    }
}

async function testFullMatrix() {
    const db = new PGlite();
    console.log('--- Initializing Complete Schema with Migration 024 & 025 in Real PostgreSQL ---');

    // 1. Setup base schema
    await db.exec(`
        create table public.organizations (
            id uuid primary key default gen_random_uuid(),
            name text not null
        );

        create table public.bids (
            id bigserial primary key,
            organization_id uuid not null references public.organizations(id),
            title text,
            procurement_truth_status text not null default 'ungoverned'
        );

        create table public.documents (
            id bigserial primary key,
            bid_id bigint not null references public.bids(id) on delete cascade
        );

        create table public.requirements (
            id bigserial primary key,
            bid_id bigint not null references public.bids(id) on delete cascade,
            description text
        );

        create table public.analysis_runs (
            id bigserial primary key,
            bid_id bigint not null references public.bids(id) on delete cascade,
            analysis_mode text not null,
            status text not null default 'COMPLETE',
            unique (id, bid_id)
        );

        create table public.full_analysis_events (
            id bigserial primary key,
            run_id bigint not null,
            bid_id bigint not null references public.bids(id) on delete cascade,
            event_type text not null,
            foreign key (run_id, bid_id) references public.analysis_runs (id, bid_id) on delete cascade
        );

        create table public.check_run_events (
            id bigserial primary key,
            run_id bigint not null,
            bid_id bigint not null references public.bids(id) on delete cascade,
            event_type text not null,
            foreign key (run_id, bid_id) references public.analysis_runs (id, bid_id) on delete cascade
        );

        create table public.procurement_conflicts (
            id bigserial primary key,
            bid_id bigint not null references public.bids(id) on delete cascade,
            organization_id uuid not null references public.organizations(id),
            target_requirement_id bigint references public.requirements(id) on delete set null,
            status text not null default 'unresolved'
        );

        create table public.procurement_update_reviews (
            id bigserial primary key,
            bid_id bigint not null references public.bids(id) on delete cascade,
            organization_id uuid not null references public.organizations(id),
            status text not null default 'pending',
            review_kind text not null default 'baseline'
        );

        create table public.procurement_update_review_documents (
            review_id bigint not null references public.procurement_update_reviews(id) on delete cascade,
            document_id bigint not null references public.documents(id) on delete cascade,
            organization_id uuid not null references public.organizations(id),
            role text not null default 'primary',
            primary key (review_id, document_id)
        );

        create table public.procurement_changes (
            id bigserial primary key,
            review_id bigint not null references public.procurement_update_reviews(id) on delete cascade,
            bid_id bigint not null references public.bids(id) on delete cascade,
            organization_id uuid not null references public.organizations(id),
            source_document_id bigint references public.documents(id) on delete cascade,
            target_requirement_id bigint references public.requirements(id) on delete set null,
            applied_at timestamptz
        );
    `);

    // 2. Install Migration 024 & Migration 025 trigger functions and triggers
    await db.exec(`
        -- 1. Full Analysis Events
        create or replace function public.full_analysis_reject_mutation()
        returns trigger language plpgsql set search_path = public as $$
        begin
            if tg_op = 'DELETE' then
                if exists (
                    select 1
                    from public.bids
                    where id = old.bid_id
                ) then
                    raise exception '% rows are append-only', tg_table_name;
                end if;
                return old;
            end if;

            raise exception '% rows are append-only', tg_table_name;
        end;
        $$;

        drop trigger if exists trg_full_analysis_events_append_only on public.full_analysis_events;
        create trigger trg_full_analysis_events_append_only
            before update or delete on public.full_analysis_events
            for each row execute function public.full_analysis_reject_mutation();

        -- 2. Check Run Events
        create or replace function public.check_run_reject_mutation()
        returns trigger language plpgsql set search_path = public as $$
        begin
            if tg_op = 'DELETE' then
                if exists (
                    select 1
                    from public.bids
                    where id = old.bid_id
                ) then
                    raise exception '% rows are immutable', tg_table_name;
                end if;
                return old;
            end if;

            raise exception '% rows are immutable', tg_table_name;
        end;
        $$;

        drop trigger if exists trg_check_run_events_append_only on public.check_run_events;
        create trigger trg_check_run_events_append_only
            before update or delete on public.check_run_events
            for each row execute function public.check_run_reject_mutation();

        -- 3. Applied Procurement Changes
        create or replace function public.prevent_applied_change_mutation() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        begin
            if old.applied_at is not null then
                if tg_op = 'DELETE' then
                    if exists (
                        select 1
                        from public.bids
                        where id = old.bid_id
                    ) then
                        raise exception 'applied_change_immutable';
                    end if;
                    return old;
                end if;
                raise exception 'applied_change_immutable';
            end if;

            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end;
        $$;

        drop trigger if exists guard_applied_change_immutability on public.procurement_changes;
        create trigger guard_applied_change_immutability
            before update or delete on public.procurement_changes
            for each row execute function public.prevent_applied_change_mutation();

        -- 4. Applied Procurement Reviews
        create or replace function public.prevent_applied_review_mutation() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        begin
            if old.status = 'applied' then
                if tg_op = 'DELETE' then
                    if exists (
                        select 1
                        from public.bids
                        where id = old.bid_id
                    ) then
                        raise exception 'applied_review_immutable';
                    end if;
                    return old;
                end if;
                raise exception 'applied_review_immutable';
            end if;

            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end;
        $$;

        drop trigger if exists guard_applied_review_immutability on public.procurement_update_reviews;
        create trigger guard_applied_review_immutability
            before update or delete on public.procurement_update_reviews
            for each row execute function public.prevent_applied_review_mutation();

        -- 5. Applied Review Documents (Migration 025 cascade-aware)
        create or replace function public.prevent_applied_review_document_mutation() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        declare
            v_status text;
            v_bid_id bigint;
        begin
            select status, bid_id into v_status, v_bid_id
            from public.procurement_update_reviews
            where id = old.review_id;

            if v_status = 'applied' then
                if tg_op = 'UPDATE' then
                    raise exception 'applied_review_document_immutable';
                end if;

                if tg_op = 'DELETE' then
                    if v_bid_id is not null and exists (
                        select 1 from public.bids where id = v_bid_id
                    ) then
                        raise exception 'applied_review_document_immutable';
                    end if;
                    return old;
                end if;
            end if;

            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end;
        $$;

        drop trigger if exists guard_applied_review_document_immutability on public.procurement_update_review_documents;
        create trigger guard_applied_review_document_immutability
            before update or delete on public.procurement_update_review_documents
            for each row execute function public.prevent_applied_review_document_mutation();

        -- 6. Resolved Procurement Conflicts
        create or replace function public.prevent_resolved_conflict_mutation() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        begin
            if old.status = 'resolved' then
                if tg_op = 'DELETE' then
                    if exists (
                        select 1
                        from public.bids
                        where id = old.bid_id
                    ) then
                        raise exception 'resolved_conflict_immutable';
                    end if;
                    return old;
                end if;
                raise exception 'resolved_conflict_immutable';
            end if;

            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end;
        $$;

        drop trigger if exists guard_resolved_conflict_immutability on public.procurement_conflicts;
        create trigger guard_resolved_conflict_immutability
            before update or delete on public.procurement_conflicts
            for each row execute function public.prevent_resolved_conflict_mutation();
    `);

    console.log('Schema & Triggers installed. Running Tests A through O...\n');

    // Setup an organization
    const orgRes = await db.query(`insert into public.organizations (name) values ('Test Org') returning id;`);
    const orgId = orgRes.rows[0].id;

    // --- TEST A: Full Analysis event direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title) values (100, '${orgId}', 'Bid 100');
        insert into public.analysis_runs (id, bid_id, analysis_mode) values (100, 100, 'FULL');
        insert into public.full_analysis_events (id, run_id, bid_id, event_type) values (100, 100, 100, 'SPECIALIST_COMPLETED');
    `);
    try {
        await db.exec(`delete from public.full_analysis_events where id = 100;`);
        throw new Error('Test A failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('append-only')) throw e;
        console.log('PASS Test A: Full Analysis event direct DELETE with live bid -> FAIL (rejected as append-only)');
    }

    // --- TEST B: Full Analysis event UPDATE -> FAIL ---
    try {
        await db.exec(`update public.full_analysis_events set event_type = 'MUTATED' where id = 100;`);
        throw new Error('Test B failed: direct update should have thrown!');
    } catch (e) {
        if (!e.message.includes('append-only')) throw e;
        console.log('PASS Test B: Full Analysis event UPDATE -> FAIL (rejected as append-only)');
    }

    // --- TEST C: Deleting parent bid with Full Analysis events -> PASS ---
    await db.exec(`delete from public.bids where id = 100;`);
    const cEvents = await db.query(`select count(*) as c from public.full_analysis_events where bid_id = 100;`);
    const cRuns = await db.query(`select count(*) as c from public.analysis_runs where bid_id = 100;`);
    const cBids = await db.query(`select count(*) as c from public.bids where id = 100;`);
    if (cEvents.rows[0].c !== 0 || cRuns.rows[0].c !== 0 || cBids.rows[0].c !== 0) throw new Error('Test C failed: rows remain');
    console.log('PASS Test C: Deleting parent bid with Full Analysis events -> PASS (all event rows cascade away)');

    // --- TEST D: CHECK event direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title) values (102, '${orgId}', 'Bid 102');
        insert into public.analysis_runs (id, bid_id, analysis_mode) values (102, 102, 'FAST');
        insert into public.check_run_events (id, run_id, bid_id, event_type) values (102, 102, 102, 'CHECK_STARTED');
    `);
    try {
        await db.exec(`delete from public.check_run_events where id = 102;`);
        throw new Error('Test D failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('immutable')) throw e;
        console.log('PASS Test D: CHECK event direct DELETE with live bid -> FAIL (rejected as immutable)');
    }

    // --- TEST E: Deleting parent bid with CHECK events -> PASS ---
    await db.exec(`delete from public.bids where id = 102;`);
    const eEvents = await db.query(`select count(*) as c from public.check_run_events where bid_id = 102;`);
    const eBids = await db.query(`select count(*) as c from public.bids where id = 102;`);
    if (eEvents.rows[0].c !== 0 || eBids.rows[0].c !== 0) throw new Error('Test E failed: rows remain');
    console.log('PASS Test E: Deleting parent bid with CHECK events -> PASS (all event rows cascade away)');

    // --- TEST F: Applied procurement_change direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (103, '${orgId}', 'Bid 103', 'governed');
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (103, 103, '${orgId}', 'applied');
        insert into public.procurement_changes (id, review_id, bid_id, organization_id, applied_at)
            values (103, 103, 103, '${orgId}', now());
    `);
    try {
        await db.exec(`delete from public.procurement_changes where id = 103;`);
        throw new Error('Test F failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_change_immutable')) throw e;
        console.log('PASS Test F: Applied procurement_change direct DELETE with live bid -> FAIL (rejected)');
    }

    // --- TEST G: Deleting governed parent bid with applied changes -> PASS ---
    await db.exec(`delete from public.bids where id = 103;`);
    const gChanges = await db.query(`select count(*) as c from public.procurement_changes where bid_id = 103;`);
    const gBids = await db.query(`select count(*) as c from public.bids where id = 103;`);
    if (gChanges.rows[0].c !== 0 || gBids.rows[0].c !== 0) throw new Error('Test G failed: rows remain');
    console.log('PASS Test G: Deleting governed parent bid with applied changes -> PASS (all cascaded cleanly)');

    // --- TEST H: Applied procurement review direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (104, '${orgId}', 'Bid 104', 'governed');
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (104, 104, '${orgId}', 'applied');
    `);
    try {
        await db.exec(`delete from public.procurement_update_reviews where id = 104;`);
        throw new Error('Test H failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_review_immutable')) throw e;
        console.log('PASS Test H: Applied procurement review direct DELETE with live bid -> FAIL (rejected)');
    }

    // --- TEST I: Applied Review Documents Immutability & Cascade Matrix ---
    await db.exec(`
        insert into public.documents (id, bid_id) values (104, 104);
        insert into public.procurement_update_review_documents (review_id, document_id, organization_id)
            values (104, 104, '${orgId}');
    `);
    // I.1 Direct delete of applied review document must fail
    try {
        await db.exec(`delete from public.procurement_update_review_documents where review_id = 104 and document_id = 104;`);
        throw new Error('Test I.1 failed: direct delete of applied review document should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_review_document_immutable')) throw e;
        console.log('PASS Test I.1: Direct DELETE review_document from applied review with live bid -> FAIL (rejected)');
    }

    // I.2 Direct update of applied review document must fail
    try {
        await db.exec(`update public.procurement_update_review_documents set role = 'supporting' where review_id = 104 and document_id = 104;`);
        throw new Error('Test I.2 failed: update of applied review document should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_review_document_immutable')) throw e;
        console.log('PASS Test I.2: UPDATE review_document on applied review -> FAIL (rejected)');
    }

    // I.3 Direct delete of source document with applied review must fail via membership cascade trigger
    try {
        await db.exec(`delete from public.documents where id = 104;`);
        throw new Error('Test I.3 failed: direct delete of source document should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_review_document_immutable')) throw e;
        console.log('PASS Test I.3: Direct DELETE source document referenced by applied review with live bid -> FAIL (rejected)');
    }

    // I.4 Delete parent bid -> PASS (all cascaded away)
    await db.exec(`delete from public.bids where id = 104;`);
    const iDocs = await db.query(`select count(*) as c from public.procurement_update_review_documents where review_id = 104;`);
    const iReviews = await db.query(`select count(*) as c from public.procurement_update_reviews where bid_id = 104;`);
    const iBids = await db.query(`select count(*) as c from public.bids where id = 104;`);
    if (iDocs.rows[0].c !== 0 || iReviews.rows[0].c !== 0 || iBids.rows[0].c !== 0) throw new Error('Test I.4 failed: rows remain');
    console.log('PASS Test I.4: Deleting governed parent bid with applied review/documents -> PASS (all cascaded away)');

    // --- TEST J: Resolved procurement conflict direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (105, '${orgId}', 'Bid 105', 'governed');
        insert into public.procurement_conflicts (id, bid_id, organization_id, status) values (105, 105, '${orgId}', 'resolved');
    `);
    try {
        await db.exec(`delete from public.procurement_conflicts where id = 105;`);
        throw new Error('Test J failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('resolved_conflict_immutable')) throw e;
        console.log('PASS Test J: Resolved procurement conflict direct DELETE with live bid -> FAIL (rejected)');
    }

    // --- TEST K: Deleting governed parent bid with resolved conflict -> PASS ---
    await db.exec(`delete from public.bids where id = 105;`);
    const kConflicts = await db.query(`select count(*) as c from public.procurement_conflicts where bid_id = 105;`);
    const kBids = await db.query(`select count(*) as c from public.bids where id = 105;`);
    if (kConflicts.rows[0].c !== 0 || kBids.rows[0].c !== 0) throw new Error('Test K failed: rows remain');
    console.log('PASS Test K: Deleting governed parent bid with resolved conflict -> PASS (all cascaded away)');

    // --- TEST L: Parent bid delete with procurement_changes.source_document_id populated -> PASS ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (106, '${orgId}', 'Bid 106', 'governed');
        insert into public.documents (id, bid_id) values (106, 106);
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (106, 106, '${orgId}', 'applied');
        insert into public.procurement_changes (id, review_id, bid_id, organization_id, source_document_id, applied_at)
            values (106, 106, 106, '${orgId}', 106, now());
    `);
    await db.exec(`delete from public.bids where id = 106;`);
    const lChanges = await db.query(`select count(*) as c from public.procurement_changes where bid_id = 106;`);
    const lDocs = await db.query(`select count(*) as c from public.documents where bid_id = 106;`);
    const lBids = await db.query(`select count(*) as c from public.bids where id = 106;`);
    if (lChanges.rows[0].c !== 0 || lDocs.rows[0].c !== 0 || lBids.rows[0].c !== 0) throw new Error('Test L failed: rows remain');
    console.log('PASS Test L: Deleting governed parent bid with procurement_changes.source_document_id -> PASS');

    // --- TEST M: Parent bid delete with procurement_conflicts.target_requirement_id populated -> PASS ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (107, '${orgId}', 'Bid 107', 'governed');
        insert into public.requirements (id, bid_id, description) values (107, 107, 'Requirement 107');
        insert into public.procurement_conflicts (id, bid_id, organization_id, target_requirement_id, status)
            values (107, 107, '${orgId}', 107, 'resolved');
    `);
    await db.exec(`delete from public.bids where id = 107;`);
    const mConflicts = await db.query(`select count(*) as c from public.procurement_conflicts where bid_id = 107;`);
    const mReqs = await db.query(`select count(*) as c from public.requirements where bid_id = 107;`);
    const mBids = await db.query(`select count(*) as c from public.bids where id = 107;`);
    if (mConflicts.rows[0].c !== 0 || mReqs.rows[0].c !== 0 || mBids.rows[0].c !== 0) throw new Error('Test M failed: rows remain');
    console.log('PASS Test M: Deleting governed parent bid with procurement_conflicts.target_requirement_id -> PASS');

    // --- TEST N: Parent bid delete with procurement_changes.target_requirement_id populated -> PASS ---
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (108, '${orgId}', 'Bid 108', 'governed');
        insert into public.requirements (id, bid_id, description) values (108, 108, 'Requirement 108');
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (108, 108, '${orgId}', 'applied');
        insert into public.procurement_changes (id, review_id, bid_id, organization_id, target_requirement_id, applied_at)
            values (108, 108, 108, '${orgId}', 108, now());
    `);
    await db.exec(`delete from public.bids where id = 108;`);
    const nChanges = await db.query(`select count(*) as c from public.procurement_changes where bid_id = 108;`);
    const nReqs = await db.query(`select count(*) as c from public.requirements where bid_id = 108;`);
    const nBids = await db.query(`select count(*) as c from public.bids where id = 108;`);
    if (nChanges.rows[0].c !== 0 || nReqs.rows[0].c !== 0 || nBids.rows[0].c !== 0) throw new Error('Test N failed: rows remain');
    console.log('PASS Test N: Deleting governed parent bid with procurement_changes.target_requirement_id -> PASS');

    // --- TEST O: Complete Bid 1522-equivalent governed graph deletion in isolated fixture -> PASS ---
    // Bid 1522 has: documents, requirements, analysis_runs, analysis_results, full_analysis_events,
    // reviews (failed + applied), review_documents, changes (with source_document_id & target_requirement_id)
    await db.exec(`
        insert into public.bids (id, organization_id, title, procurement_truth_status) values (1522, '${orgId}', 'York University Benchmark Fixture', 'governed');
        insert into public.documents (id, bid_id) values (225, 1522);
        insert into public.requirements (id, bid_id, description) values (2473, 1522, 'Req 1');
        insert into public.requirements (id, bid_id, description) values (2474, 1522, 'Req 2');
        insert into public.analysis_runs (id, bid_id, analysis_mode, status) values (55, 1522, 'FAST', 'COMPLETE');
        insert into public.analysis_runs (id, bid_id, analysis_mode, status) values (56, 1522, 'FULL', 'PARTIAL');
        insert into public.analysis_runs (id, bid_id, analysis_mode, status) values (57, 1522, 'FULL', 'COMPLETE');
        insert into public.full_analysis_events (id, run_id, bid_id, event_type) values (5701, 57, 1522, 'SPECIALIST_COMPLETED');
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (4, 1522, '${orgId}', 'failed');
        insert into public.procurement_update_reviews (id, bid_id, organization_id, status) values (5, 1522, '${orgId}', 'applied');
        insert into public.procurement_update_review_documents (review_id, document_id, organization_id) values (4, 225, '${orgId}');
        insert into public.procurement_update_review_documents (review_id, document_id, organization_id) values (5, 225, '${orgId}');
        insert into public.procurement_changes (id, review_id, bid_id, organization_id, source_document_id, target_requirement_id, applied_at)
            values (501, 5, 1522, '${orgId}', 225, 2473, now());
        insert into public.procurement_changes (id, review_id, bid_id, organization_id, source_document_id, target_requirement_id, applied_at)
            values (502, 5, 1522, '${orgId}', 225, 2474, now());
    `);

    // Verify fixture is fully populated
    const preCount = await db.query(`select count(*) as c from public.procurement_update_review_documents where review_id in (4, 5);`);
    if (preCount.rows[0].c !== 2) throw new Error('Test O setup failed: review docs count');

    // Execute whole-bid deletion on Bid 1522 fixture
    await db.exec(`delete from public.bids where id = 1522;`);

    // Verify every child table is 0
    const oBids = await db.query(`select count(*) as c from public.bids where id = 1522;`);
    const oDocs = await db.query(`select count(*) as c from public.documents where bid_id = 1522;`);
    const oReqs = await db.query(`select count(*) as c from public.requirements where bid_id = 1522;`);
    const oRuns = await db.query(`select count(*) as c from public.analysis_runs where bid_id = 1522;`);
    const oEvents = await db.query(`select count(*) as c from public.full_analysis_events where bid_id = 1522;`);
    const oReviews = await db.query(`select count(*) as c from public.procurement_update_reviews where bid_id = 1522;`);
    const oReviewDocs = await db.query(`select count(*) as c from public.procurement_update_review_documents where organization_id = '${orgId}' and document_id = 225;`);
    const oChanges = await db.query(`select count(*) as c from public.procurement_changes where bid_id = 1522;`);

    if (
        oBids.rows[0].c !== 0 ||
        oDocs.rows[0].c !== 0 ||
        oReqs.rows[0].c !== 0 ||
        oRuns.rows[0].c !== 0 ||
        oEvents.rows[0].c !== 0 ||
        oReviews.rows[0].c !== 0 ||
        oReviewDocs.rows[0].c !== 0 ||
        oChanges.rows[0].c !== 0
    ) {
        throw new Error('Test O failed: residual rows detected after Bid 1522 fixture purge');
    }
    console.log('PASS Test O: Bid 1522-equivalent governed graph whole-bid purge -> PASS (100% cleanly cascaded)');

    console.log('\n============================================================');
    console.log('ALL 15 TESTS (A THROUGH O) PASSED ON REAL POSTGRESQL ENGINE!');
    console.log('============================================================');
}

testFullMatrix().catch(err => {
    console.error('TEST MATRIX ERROR:', err);
    process.exit(1);
});
