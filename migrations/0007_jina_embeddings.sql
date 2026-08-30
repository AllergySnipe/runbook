-- 0007_jina_embeddings.sql — switch embedding model: local bge-small (384-dim)
-- → hosted jina-embeddings-v5-text-small (1024-dim). ADR-0013.
--
-- Vectors from different models live in different spaces — the stored 384-dim
-- embeddings are not convertible and must be recomputed. This migration drops
-- the ANN index, nulls every embedding, and widens the column; `runbook embed
-- --all` then backfills from the new model, and the index refills as it goes.
--
-- Between this migration and the re-embed, the vector leg of hybrid retrieval
-- returns nothing — full-text search carries queries until the backfill lands.

drop index if exists documents_embedding_idx;

update documents set embedding = null;

alter table documents
    alter column embedding type vector(1024);

create index documents_embedding_idx
    on documents using hnsw (embedding vector_cosine_ops);
