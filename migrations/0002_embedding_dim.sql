-- 0002_embedding_dim.sql — lock the embedding dimension and add the ANN index.
--
-- ADR-0002: local BAAI/bge-small-en-v1.5, 384-dim, cosine distance. All existing
-- `embedding` values are NULL (the embed slice backfills them), so the type change
-- is free. HNSW over an empty column is fine — it fills as rows are embedded.

alter table documents
    alter column embedding type vector(384);

create index documents_embedding_idx
    on documents using hnsw (embedding vector_cosine_ops);
