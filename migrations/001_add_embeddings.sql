-- Migration 001: Add embedding column to content_library
-- Run this in the Supabase SQL Editor.
--
-- We store embeddings as TEXT (JSON array) rather than a native vector
-- type to avoid requiring the pgvector extension. Similarity is computed
-- in Python. If you have pgvector available, you can alter this later:
--   ALTER TABLE content_library ALTER COLUMN embedding TYPE vector(512)
--   USING embedding::vector;

ALTER TABLE content_library
    ADD COLUMN IF NOT EXISTS embedding TEXT;

-- Optional: index for future pgvector upgrade
-- CREATE INDEX IF NOT EXISTS content_library_embedding_idx
--     ON content_library USING ivfflat (embedding vector_cosine_ops);

-- Also add VOYAGE_API_KEY reminder comment
-- Add to Streamlit secrets:
--   VOYAGE_API_KEY = "pa-..."
-- Get your key at: https://dash.voyageai.com/
