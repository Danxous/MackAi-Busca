"""Ingestão: fontes (fontes.json), filtro de segredos (US 29), hash e orquestração da indexação."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import UUID

from .chunking import Chave, Documento, split_into_chunks
from .config import Configuracao
from .embeddings import FalhaEmbeddings

log = logging.getLogger("mackai.busca")

EXTENSOES = {".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".yml", ".yaml", ".sql"}
PASTAS_IGNORADAS = {"node_modules", ".git", "dist", ".venv", "venv", "__pycache__", ".pytest_cache",
                    "frontend_dist", "conhecimento"}
EXTENSOES_PROIBIDAS = {".pem", ".key", ".pfx", ".p12", ".publishsettings"}
ARQUIVOS_IGNORADOS = {"package-lock.json"}
ARQUIVOS_PERMITIDOS = {".env.example", "Dockerfile"}  # sem extensão da lista, mas úteis nas respostas

CHAVE_PRIVADA = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
SEGREDO = re.compile(r"(api[_-]?key|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.IGNORECASE)


@dataclass(frozen=True)
class Fonte:
    source: str
    raiz: Path
    project_id: UUID | None = None


def carregar_fontes(arquivo: Path) -> list[Fonte]:
    """Lê fontes.json. Caminhos são relativos à pasta do próprio arquivo. Chaves extras (como `repos`, usada
    por scripts/preparar_conhecimento.py) são ignoradas aqui."""
    if not arquivo.exists():
        log.warning("fontes: %s não existe; nada para indexar", arquivo)
        return []
    fontes = []
    for item in json.loads(arquivo.read_text(encoding="utf-8")):
        projeto = UUID(item["project_id"]) if item.get("project_id") else None
        fontes.append(Fonte(item["source"], (arquivo.parent / item["path"]).resolve(), projeto))
    return fontes


def motivo_bloqueio_caminho(caminho: str) -> str | None:
    """Motivo para não indexar o arquivo pelo nome ou pela pasta. None = permitido."""
    partes = PurePosixPath(caminho).parts
    nome = partes[-1] if partes else ""
    if any(p in PASTAS_IGNORADAS for p in partes[:-1]):
        return "pasta ignorada"
    if nome.startswith(".env") and nome != ".env.example":
        return "arquivo .env"
    sufixo = PurePosixPath(nome).suffix.lower()
    if sufixo in EXTENSOES_PROIBIDAS:
        return "arquivo de chave ou certificado"
    if nome in ARQUIVOS_IGNORADOS:
        return "arquivo gerado"
    if sufixo not in EXTENSOES and nome not in ARQUIVOS_PERMITIDOS:
        return "extensão não indexada"
    return None


def motivo_bloqueio_conteudo(conteudo: str) -> str | None:
    if "\x00" in conteudo:
        return "arquivo binário"
    if CHAVE_PRIVADA.search(conteudo):
        return "contém chave privada"
    if SEGREDO.search(conteudo):
        return "parece conter um segredo"
    return None


def coletar(fonte: Fonte, max_file_kb: int) -> list[Documento]:
    documentos = []
    for arquivo in sorted(p for p in fonte.raiz.rglob("*") if p.is_file()):
        caminho = arquivo.relative_to(fonte.raiz).as_posix()
        if motivo_bloqueio_caminho(caminho):
            continue
        if arquivo.stat().st_size > max_file_kb * 1024:
            log.info("ingestao: ignorado (acima de %s KB) %s/%s", max_file_kb, fonte.source, caminho)
            continue
        conteudo = arquivo.read_text(encoding="utf-8", errors="ignore")
        motivo = motivo_bloqueio_conteudo(conteudo)
        if motivo:
            # Só o caminho vai para o log, nunca o conteúdo.
            log.warning("ingestao: ignorado (%s) %s/%s", motivo, fonte.source, caminho)
            continue
        documentos.append(Documento(fonte.source, caminho, conteudo, fonte.project_id))
    return documentos


@dataclass
class ResultadoReindex:
    documents: int = 0
    embedded_chunks: int = 0
    skipped_documents: int = 0
    removed_documents: int = 0
    failed_documents: int = 0


@dataclass
class Indexador:
    """Coordena a indexação das fontes e dos documentos avulsos. Uma indexação por vez (lock)."""

    indice: object  # IndicePgvector ou IndiceTfidf
    cfg: Configuracao
    indexando: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def indexar_documento(self, doc: Documento, hashes: dict[Chave, str] | None = None) -> tuple[int, int] | None:
        """Grava o documento se o hash mudou. Devolve (trechos, trechos com embedding novo) ou None se pulou."""
        atual = (hashes if hashes is not None else await self.indice.hashes([doc.chave])).get(doc.chave)
        if atual == doc.content_hash:
            return None
        chunks = split_into_chunks(doc.source, doc.path, doc.content, self.cfg.chunk_lines, self.cfg.chunk_overlap,
                                   doc.project_id)
        embutidos = await self.indice.gravar(doc, chunks)
        return len(chunks), embutidos

    async def documento_avulso(self, doc: Documento) -> int:
        """POST /v1/documents. Devolve o número de trechos do documento."""
        async with self._lock:
            resultado = await self.indexar_documento(doc)
            if resultado is None:
                return await self.indice.contar_trechos(doc.chave)
            await self.indice.marcar_indexado(datetime.now(timezone.utc))
            return resultado[0]

    async def reindexar(self) -> ResultadoReindex:
        async with self._lock:
            self.indexando = True
            try:
                return await self._reindexar()
            finally:
                self.indexando = False

    async def _reindexar(self) -> ResultadoReindex:
        resultado = ResultadoReindex()
        fontes = [f for f in carregar_fontes(self.cfg.fontes_file) if self._fonte_existe(f)]
        documentos = []
        for fonte in fontes:
            documentos.extend(await asyncio.to_thread(coletar, fonte, self.cfg.max_file_kb))
        resultado.documents = len(documentos)

        escopos = {(f.project_id, f.source) for f in fontes}
        hashes = await self.indice.hashes_por_escopo(escopos)
        for doc in documentos:
            try:
                feito = await self.indexar_documento(doc, hashes)
            except FalhaEmbeddings as erro:  # um arquivo com problema não para a indexação inteira
                log.warning("ingestao: falha nos embeddings de %s/%s: %s", doc.source, doc.path, erro)
                resultado.failed_documents += 1
                continue
            if feito is None:
                resultado.skipped_documents += 1
            else:
                resultado.embedded_chunks += feito[1]

        # Só remove documentos das fontes configuradas que existem; documentos avulsos de outras fontes ficam.
        presentes = {d.chave for d in documentos}
        ausentes = [chave for chave in hashes if chave not in presentes]
        resultado.removed_documents = await self.indice.remover(ausentes)
        await self.indice.marcar_indexado(datetime.now(timezone.utc))
        log.info("ingestao: %s", resultado)
        return resultado

    @staticmethod
    def _fonte_existe(fonte: Fonte) -> bool:
        if fonte.raiz.is_dir():
            return True
        # Pasta ausente (conhecimento não preparado): não indexa nem apaga o que já está no banco.
        log.warning("fontes: pasta %s da fonte %s não existe; fonte ignorada", fonte.raiz, fonte.source)
        return False
