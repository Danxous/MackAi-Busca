"""Índice com embeddings no busca_db (PostgreSQL + pgvector). SQL puro com asyncpg, sem ORM.

A conexão é aberta na primeira vez que alguém precisa dela: se o banco estiver fora do ar na inicialização,
/health continua respondendo e as rotas devolvem 503 INDICE_INDISPONIVEL até o banco voltar.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector

from .chunking import Chave, Chunk, Documento
from .config import Configuracao
from .embeddings import Embedder
from .erros import indice_indisponivel

log = logging.getLogger("mackai.busca")

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

ERROS_DE_CONEXAO = (OSError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError, asyncpg.InterfaceError)

_FILTRO_CHAVE = "project_id IS NOT DISTINCT FROM $1::uuid AND source = $2 AND path = $3"


class IndicePgvector:
    estrategia = "embedding"

    def __init__(self, cfg: Configuracao, embedder: Embedder):
        self.cfg = cfg
        self.embedder = embedder
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    # ---------- conexão ----------

    async def abrir(self) -> asyncpg.Pool:
        if self._pool:
            return self._pool
        async with self._lock:
            if self._pool:
                return self._pool
            try:
                conn = await asyncpg.connect(self.cfg.database_url, timeout=10)
                try:
                    await self._preparar_schema(conn)
                finally:
                    await conn.close()
                self._pool = await asyncpg.create_pool(self.cfg.database_url, min_size=1, max_size=5,
                                                       init=register_vector, timeout=10, command_timeout=30)
            except ERROS_DE_CONEXAO as erro:
                log.warning("busca_db indisponível: %r", erro)
                raise indice_indisponivel() from erro
            log.info("busca_db conectado (modelo %s, %s dimensões)", self.embedder.modelo, self.embedder.dimensoes)
            return self._pool

    async def fechar(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def _conexao(self):
        pool = await self.abrir()
        try:
            async with pool.acquire(timeout=10) as conn:
                yield conn
        except ERROS_DE_CONEXAO as erro:
            log.warning("busca_db falhou: %r", erro)
            raise indice_indisponivel() from erro

    async def _preparar_schema(self, conn: asyncpg.Connection) -> None:
        dimensoes = self.embedder.dimensoes
        async with conn.transaction():
            await conn.execute(SCHEMA.replace("{EMBEDDING_DIMENSIONS}", str(dimensoes)))
            estado = await conn.fetchrow("SELECT embedding_model, embedding_dimensions FROM index_state")
            if (estado["embedding_model"], estado["embedding_dimensions"]) == (self.embedder.modelo, dimensoes):
                return
            # Vetores de modelos ou tamanhos diferentes não se comparam: reindexação completa.
            if estado["embedding_model"] is not None:
                log.warning("modelo de embedding mudou (%s/%s -> %s/%s): índice apagado para reindexar",
                            estado["embedding_model"], estado["embedding_dimensions"], self.embedder.modelo, dimensoes)
            await conn.execute("TRUNCATE chunks, documents")
            atual = await conn.fetchval(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'")
            if atual != dimensoes:
                await conn.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({int(dimensoes)})")
            await conn.execute("UPDATE index_state SET embedding_model = $1, embedding_dimensions = $2, indexed_at = NULL",
                               self.embedder.modelo, dimensoes)

    # ---------- escrita ----------

    async def hashes(self, chaves: list[Chave]) -> dict[Chave, str]:
        async with self._conexao() as conn:
            encontrados = {}
            for chave in chaves:
                valor = await conn.fetchval(f"SELECT content_hash FROM documents WHERE {_FILTRO_CHAVE}", *chave)
                if valor is not None:
                    encontrados[chave] = valor
            return encontrados

    async def hashes_por_escopo(self, escopos: set[tuple[UUID | None, str]]) -> dict[Chave, str]:
        async with self._conexao() as conn:
            encontrados = {}
            for projeto, source in escopos:
                linhas = await conn.fetch(
                    "SELECT path, content_hash FROM documents WHERE project_id IS NOT DISTINCT FROM $1::uuid AND source = $2",
                    projeto, source)
                encontrados.update({(projeto, source, l["path"]): l["content_hash"] for l in linhas})
            return encontrados

    async def gravar(self, doc: Documento, chunks: list[Chunk]) -> int:
        """Gera os embeddings fora da transação e troca os trechos do documento numa transação só."""
        vetores = await self.embedder.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT") if chunks else []
        async with self._conexao() as conn, conn.transaction():
            doc_id = await conn.fetchval(f"SELECT id FROM documents WHERE {_FILTRO_CHAVE} FOR UPDATE", *doc.chave)
            if doc_id is None:
                doc_id = await conn.fetchval(
                    "INSERT INTO documents (project_id, source, path, content_hash) VALUES ($1, $2, $3, $4) RETURNING id",
                    *doc.chave, doc.content_hash)
            else:
                await conn.execute("UPDATE documents SET content_hash = $2, indexed_at = now() WHERE id = $1",
                                   doc_id, doc.content_hash)
                await conn.execute("DELETE FROM chunks WHERE document_id = $1", doc_id)
            await conn.executemany(
                "INSERT INTO chunks (document_id, start_line, end_line, text, embedding) VALUES ($1, $2, $3, $4, $5)",
                [(doc_id, c.start_line, c.end_line, c.text, v) for c, v in zip(chunks, vetores)],
            )
        return len(vetores)

    async def contar_trechos(self, chave: Chave) -> int:
        async with self._conexao() as conn:
            return await conn.fetchval(
                """
                SELECT count(c.id) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                WHERE d.project_id IS NOT DISTINCT FROM $1::uuid AND d.source = $2 AND d.path = $3
                """, *chave)

    async def remover(self, chaves: list[Chave]) -> int:
        if not chaves:
            return 0
        async with self._conexao() as conn, conn.transaction():
            removidos = 0
            for chave in chaves:
                removidos += int((await conn.execute(f"DELETE FROM documents WHERE {_FILTRO_CHAVE}", *chave)).split()[-1])
            return removidos

    async def marcar_indexado(self, quando: datetime) -> None:
        async with self._conexao() as conn:
            await conn.execute("UPDATE index_state SET indexed_at = $1", quando)

    # ---------- leitura ----------

    async def buscar(self, query: str, top_k: int, project_id: UUID | None) -> tuple[str, list[tuple[Chunk, float]]]:
        """Com project_id e documentos daquele projeto no índice, busca só neles (escopo "project").
        Sem project_id, ou se o projeto ainda não tem documentos, busca na base comum (escopo "global")."""
        [vetor] = await self.embedder.embed([query], "RETRIEVAL_QUERY")
        async with self._conexao() as conn:
            escopo = None
            if project_id is not None and await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM documents WHERE project_id = $1)", project_id):
                escopo = project_id
            linhas = await conn.fetch(
                """
                SELECT d.project_id, d.source, d.path, c.start_line, c.end_line, c.text,
                       1 - (c.embedding <=> $1::vector) AS similarity
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.project_id IS NOT DISTINCT FROM $2::uuid
                ORDER BY c.embedding <=> $1::vector
                LIMIT $3
                """,
                vetor, escopo, top_k,
            )
        resultados = [
            (Chunk(l["source"], l["path"], l["start_line"], l["end_line"], l["text"], l["project_id"]), float(l["similarity"]))
            for l in linhas
        ]
        minimo = self.cfg.min_similarity_embedding
        return ("project" if escopo else "global"), [r for r in resultados if r[1] >= minimo]

    async def estatisticas(self, project_id: UUID | None = None) -> dict:
        async with self._conexao() as conn:
            filtro = "WHERE d.project_id = $1" if project_id else ""
            args = [project_id] if project_id else []
            linha = await conn.fetchrow(
                f"""
                SELECT (SELECT count(*) FROM documents d {filtro}) AS documents,
                       (SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id {filtro}) AS chunks,
                       (SELECT coalesce(array_agg(DISTINCT d.source ORDER BY d.source), '{{}}') FROM documents d {filtro}) AS sources,
                       (SELECT indexed_at FROM index_state) AS indexed_at
                """,
                *args,
            )
        return {"documents": linha["documents"], "chunks": linha["chunks"], "sources": list(linha["sources"]),
                "indexed_at": linha["indexed_at"]}
