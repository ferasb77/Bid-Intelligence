/**
 * scripts/test_postgres_cascade_matrix.js
 *
 * Deterministic proof of PostgreSQL cascade ordering and immutability trigger behavior
 * for Migration 024. Runs against real PostgreSQL (via PGlite WebAssembly engine).
 *
 * Tests all 11 requirements (A through K) from BID-DELETION-HOTFIX:
 * A. Full Analysis event direct DELETE (parent bid exists) -> FAIL
 * B. Full Analysis event UPDATE -> FAIL
 * C. Deleting parent bid with Full Analysis events -> PASS (all event rows cascade away)
 * D. CHECK event direct DELETE -> FAIL
 * E. Deleting parent bid with CHECK events -> PASS
 * F. Applied procurement_change direct DELETE -> FAIL
 * G. Deleting governed parent bid with applied changes -> PASS
 * H. Applied procurement review direct DELETE -> FAIL
 * I. Deleting governed parent bid with applied review/documents -> PASS
 * J. Resolved procurement conflict direct DELETE -> FAIL
 * K. Deleting governed parent bid with resolved conflict -> PASS
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
    console.log('--- Initializing Complete Schema with Migration 024 Functions in Real PostgreSQL ---');

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
            applied_at timestamptz
        );
    `);

    // 2. Install Migration 024 trigger functions and triggers
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

        -- 5. Applied Review Documents
        create or replace function public.prevent_applied_review_document_mutation() returns trigger
        language plpgsql security definer set search_path = public, pg_temp as $$
        declare
            v_status text;
        begin
            select status into v_status from public.procurement_update_reviews where id = old.review_id;
            if v_status = 'applied' then
                raise exception 'applied_review_document_immutable';
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

    console.log('Schema & Triggers installed. Running Tests A through K...\n');

    // Setup organization
    const orgRes = await db.query(`insert into public.organizations (name) values ('Test Org') returning id;`);
    const orgId = orgRes.rows[0].id;

    // --- TEST A: Full Analysis event direct DELETE (parent bid exists) -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title) values (101, '${orgId}', 'Bid 101');
        insert into public.analysis_runs (id, bid_id, analysis_mode) values (101, 101, 'FULL');
        insert into public.full_analysis_events (id, run_id, bid_id, event_type) values (101, 101, 101, 'EVT_1');
    `);
    try {
        await db.exec(`delete from public.full_analysis_events where id = 101;`);
        throw new Error('Test A failed: direct delete should have thrown!');
    } catch (e) {
        if (!e.message.includes('append-only')) throw e;
        console.log('PASS Test A: Full Analysis event direct DELETE with live bid -> FAIL (rejected as append-only)');
    }

    // --- TEST B: Full Analysis event UPDATE -> FAIL ---
    try {
        await db.exec(`update public.full_analysis_events set event_type = 'MOD' where id = 101;`);
        throw new Error('Test B failed: update should have thrown!');
    } catch (e) {
        if (!e.message.includes('append-only')) throw e;
        console.log('PASS Test B: Full Analysis event UPDATE -> FAIL (rejected as append-only)');
    }

    // --- TEST C: Deleting parent bid with Full Analysis events -> PASS ---
    await db.exec(`delete from public.bids where id = 101;`);
    const cEvents = await db.query(`select count(*) as c from public.full_analysis_events where bid_id = 101;`);
    const cBids = await db.query(`select count(*) as c from public.bids where id = 101;`);
    if (cEvents.rows[0].c !== 0 || cBids.rows[0].c !== 0) throw new Error('Test C failed: rows remain');
    console.log('PASS Test C: Deleting parent bid with Full Analysis events -> PASS (all event rows cascade away)');

    // --- TEST D: CHECK event direct DELETE -> FAIL ---
    await db.exec(`
        insert into public.bids (id, organization_id, title) values (102, '${orgId}', 'Bid 102');
        insert into public.analysis_runs (id, bid_id, analysis_mode) values (102, 102, 'CHECK');
        insert into public.check_run_events (id, run_id, bid_id, event_type) values (102, 102, 102, 'CHK_1');
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

    // --- TEST I: Deleting governed parent bid with applied review/documents -> PASS ---
    await db.exec(`
        insert into public.documents (id, bid_id) values (104, 104);
        insert into public.procurement_update_review_documents (review_id, document_id, organization_id)
            values (104, 104, '${orgId}');
    `);
    // Direct delete of applied review document must fail
    try {
        await db.exec(`delete from public.procurement_update_review_documents where review_id = 104;`);
        throw new Error('Test I pre-check failed: direct delete of applied review document should have thrown!');
    } catch (e) {
        if (!e.message.includes('applied_review_document_immutable')) throw e;
        console.log('PASS Test I.1: Direct DELETE of applied review document with live review -> FAIL (rejected)');
    }
    // Delete parent bid -> PASS
    await db.exec(`delete from public.bids where id = 104;`);
    const iDocs = await db.query(`select count(*) as c from public.procurement_update_review_documents where review_id = 104;`);
    const iReviews = await db.query(`select count(*) as c from public.procurement_update_reviews where bid_id = 104;`);
    const iBids = await db.query(`select count(*) as c from public.bids where id = 104;`);
    if (iDocs.rows[0].c !== 0 || iReviews.rows[0].c !== 0 || iBids.rows[0].c !== 0) throw new Error('Test I failed: rows remain');
    console.log('PASS Test I.2: Deleting governed parent bid with applied review/documents -> PASS (all cascaded away)');

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

    console.log('\n============================================================');
    console.log('ALL 11 TESTS (A THROUGH K) PASSED ON REAL POSTGRESQL ENGINE!');
    console.log('============================================================');
}

testFullMatrix().catch(err => {
    console.error('TEST MATRIX ERROR:', err);
    process.exit(1);
});
