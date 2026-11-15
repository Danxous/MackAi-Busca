-- busca_db. Rodado na inicialização. {EMBEDDING_DIMENSIONS} é trocado pelo valor da configuração.
-- No Azure, a extensão precisa estar liberada em azure.extensions (VECTOR) no servidor.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id            SERIAL PRIMARY KEY,
  project_id    UUID,                     -- projeto do Módulo 1; nulo = base comum do Módulo 7
  source        TEXT NOT NULL,            -- fonte, por exemplo "modulo-7"
  path          TEXT NOT NULL,            -- relativo à raiz da fonte
  content_hash  TEXT NOT NULL,            -- SHA-256: arquivo sem mudança não gera embeddings de novo
  indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Um documento por (projeto, fonte, caminho). NULLS NOT DISTINCT: dois project_id nulos contam como iguais.
CREATE UNIQUE INDEX IF NOT EXISTS documents_chave_idx
  ON documents (project_id, source, path) NULLS NOT DISTINCT;

CREATE TABLE IF NOT EXISTS chunks (
  id           SERIAL PRIMARY KEY,
  document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  start_line   INT NOT NULL,
  end_line     INT NOT NULL,
  text         TEXT NOT NULL,
  embedding    vector({EMBEDDING_DIMENSIONS}) NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id);

-- Uma linha só: modelo de embedding usado no índice e horário da última indexação.
CREATE TABLE IF NOT EXISTS index_state (
  id                    BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
  embedding_model       TEXT,
  embedding_dimensions  INT,
  indexed_at            TIMESTAMPTZ
);
INSERT INTO index_state (id) VALUES (true) ON CONFLICT (id) DO NOTHING;
