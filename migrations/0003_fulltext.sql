-- 0003_fulltext.sql — full-text column + index for hybrid retrieval (ADR-0003).
--
-- Pure vector search (0002) matches on meaning but blurs exact tokens — service
-- names, error codes, config keys, log signatures — which incident queries are full
-- of. Postgres full-text search covers that blind spot; the retrieval layer fuses
-- the two rankings with Reciprocal Rank Fusion.
--
-- `chunk_tsv` is a GENERATED column: Postgres recomputes it from `chunk_text` on
-- every insert/update, so ingest needs no extra code and no trigger. The trade-off
-- is a fixed text-search config ('english', baked in here) and some extra storage.
-- A GIN index is the standard access method for the `@@` match operator.

alter table documents
    add column chunk_tsv tsvector
    generated always as (to_tsvector('english', chunk_text)) stored;

create index documents_tsv_idx on documents using gin (chunk_tsv);
