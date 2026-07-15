-- ============================================================
-- Bid Intelligence Platform — Supabase Schema
-- Run this in Supabase SQL Editor (Project → SQL Editor → New query)
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

create table if not exists bids (
    id                      bigserial primary key,
    title                   text not null,
    client                  text not null,
    file_number             text,
    stage                   text default 'Identified',
    sensitivity             text default 'Standard',
    owner                   text,
    value_cad               numeric,
    submission_deadline     text,
    clarification_deadline  text,
    notes                   text,
    created_at              timestamptz default now(),
    updated_at              timestamptz default now()
);

create table if not exists requirements (
    id          bigserial primary key,
    bid_id      bigint not null references bids(id) on delete cascade,
    req_id      text,
    category    text default 'Mandatory',
    description text not null,
    rfso_ref    text,
    weight      numeric,
    evidence    text,
    owner       text,
    deadline    text,
    status      text default 'Not Started',
    notes       text,
    created_at  timestamptz default now()
);

create table if not exists tasks (
    id          bigserial primary key,
    bid_id      bigint not null references bids(id) on delete cascade,
    title       text not null,
    description text,
    owner       text,
    due_date    text,
    priority    text default 'Medium',
    status      text default 'Not Started',
    created_at  timestamptz default now()
);

create table if not exists documents (
    id              bigserial primary key,
    bid_id          bigint not null references bids(id) on delete cascade,
    name            text not null,
    doc_type        text default 'Submission',
    file_path       text,
    file_size       bigint,
    storage_path    text,
    version         int default 1,
    owner           text,
    due_date        text,
    status          text default 'Expected',
    linked_req_ids  text,
    mandatory       int default 0,
    notes           text,
    created_at      timestamptz default now()
);

create table if not exists document_versions (
    id          bigserial primary key,
    document_id bigint not null references documents(id) on delete cascade,
    version     int default 1,
    file_path   text,
    storage_path text,
    file_size   bigint,
    uploaded_by text,
    notes       text,
    is_current  int default 1,
    created_at  timestamptz default now()
);

create table if not exists outline_sections (
    id          bigserial primary key,
    bid_id      bigint not null references bids(id) on delete cascade,
    sort_order  int default 0,
    section_num text,
    title       text not null,
    owner       text,
    word_limit  int,
    status      text default 'Not Started',
    notes       text
);

create table if not exists content_library (
    id          bigserial primary key,
    title       text not null,
    category    text default 'Methodology',
    content     text not null,
    source      text,
    bid_id      bigint references bids(id) on delete set null,
    tags        text,
    approved    int default 0,
    notes       text,
    created_at  timestamptz default now()
);

create table if not exists coaches (
    id                  bigserial primary key,
    name                text not null,
    credentials         text,
    icf_level           text,
    sectors             text,
    languages           text,
    location            text,
    availability        text default 'Available',
    email               text,
    phone               text,
    cv_summary          text,
    reference_contact   text,
    notes               text,
    created_at          timestamptz default now()
);

create table if not exists clarifications (
    id              bigserial primary key,
    bid_id          bigint not null references bids(id) on delete cascade,
    question_id     text,
    question        text not null,
    rationale       text,
    priority        text default 'Medium',
    linked_req_ids  text,
    submitted_date  text,
    answer          text,
    answer_date     text,
    changes_matrix  int default 0,
    status          text default 'Draft',
    notes           text,
    created_at      timestamptz default now()
);

create table if not exists debriefs (
    id                  bigserial primary key,
    bid_id              bigint not null references bids(id) on delete cascade,
    outcome             text default 'Pending',
    score_technical     numeric,
    score_financial     numeric,
    score_total         numeric,
    rank                int,
    competitors         text,
    evaluator_feedback  text,
    win_factors         text,
    loss_factors        text,
    lessons             text,
    notes               text,
    created_at          timestamptz default now()
);

create table if not exists deliverables (
    id              bigserial primary key,
    bid_id          bigint not null references bids(id) on delete cascade,
    sort_order      int default 0,
    service_id      text,
    title           text not null,
    description     text,
    category        text default 'Core Service',
    duration        text,
    volume          text,
    unit            text,
    price_ai        numeric,
    price_non_ai    numeric,
    optional        int default 0,
    linked_req_ids  text,
    notes           text,
    created_at      timestamptz default now()
);

-- Storage bucket for bid documents
insert into storage.buckets (id, name, public)
values ('bid-documents', 'bid-documents', false)
on conflict (id) do nothing;

-- RLS: disable for now (single-tenant app with API key auth)
alter table bids               disable row level security;
alter table requirements       disable row level security;
alter table tasks              disable row level security;
alter table documents          disable row level security;
alter table document_versions  disable row level security;
alter table outline_sections   disable row level security;
alter table content_library    disable row level security;
alter table coaches            disable row level security;
alter table clarifications     disable row level security;
alter table debriefs           disable row level security;
alter table deliverables       disable row level security;
