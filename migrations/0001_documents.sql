-- 0001_documents.sql — corpus store for RAG (see SPEC "Data sources" + "Architecture").
--
-- One retrievable chunk per row: runbook sections, synthetic paymentsvc runbooks,
-- and postmortem passages, chunked at ingest time. `embedding` is populated in the
-- embed slice; the ANN index and full-text column for hybrid search land with the
-- retrieval slice, once rows exist and the embedding model (hence dimension) is fixed.

create extension if not exists vector;

create table documents (
    id          bigint generated always as identity primary key,
    source      text not null,           -- corpus bucket: 'runbook' | 'synthetic-runbook' | 'postmortem'
    origin      text not null,           -- provenance: repo slug or URL host
    title       text not null,
    url         text,
    chunk_index integer not null default 0,  -- position of this chunk within its source document
    chunk_text  text not null,
    embedding   vector,                  -- dimensionless until the embedding model is chosen; no ANN index yet
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index documents_source_idx on documents (source);
create index documents_metadata_idx on documents using gin (metadata);
