"""Fallback sem GEMINI_API_KEY: vetores TF-IDF e similaridade de cosseno em memória (motor_de_busca.py do MVP).

Limitação: compara palavras, não significado. "Como esconder segredos da aplicação?" não encontra o trecho
sobre `GEMINI_API_KEY` porque as palavras não coincidem.
"""

import math
import re
import unicodedata
from collections import Counter
from datetime import datetime
from uuid import UUID

from .chunking import Chave, Chunk, Documento

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
    "um", "uma", "uns", "umas", "para", "por", "com", "que", "se", "ao", "aos", "eu", "como",
    "quero", "meu", "minha", "ou", "the", "and", "of", "to", "in", "is", "it", "for",
}


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9_]+", text) if len(t) > 1 and t not in STOPWORDS]


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(value * b.get(term, 0.0) for term, value in a.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class ModeloTfidf:
    """IDF calculado sobre todos os trechos. É reconstruído quando o conjunto de trechos muda."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        doc_freq: Counter[str] = Counter()
        for chunk in chunks:
            doc_freq.update(set(tokenize(chunk.text)))
        total = len(chunks) or 1
        self.idf = {term: math.log((1 + total) / (1 + freq)) + 1 for term, freq in doc_freq.items()}
        self.vectors = [self.embed(chunk.text) for chunk in chunks]

    def embed(self, text: str) -> dict[str, float]:
        counts = Counter(tokenize(text))
        return {term: count * self.idf.get(term, 0.0) for term, count in counts.items()}

    def search(self, query: str, top_k: int = 3, filtro=None) -> list[tuple[Chunk, float]]:
        """`filtro(chunk) -> bool` restringe os trechos considerados (por exemplo, ao projeto)."""
        query_vector = self.embed(query)
        scored = [
            (chunk, cosine_similarity(query_vector, vector))
            for chunk, vector in zip(self.chunks, self.vectors)
            if filtro is None or filtro(chunk)
        ]
        scored = [item for item in scored if item[1] > 0]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


class IndiceTfidf:
    """Mesma interface do IndicePgvector, em memória. Usado sem GEMINI_API_KEY (CI e desenvolvimento local):
    não precisa de banco nem gasta cota. O índice é refeito a cada inicialização."""

    estrategia = "tfidf"

    def __init__(self, min_similarity: float):
        self.min_similarity = min_similarity
        self._documentos: dict[Chave, tuple[str, list[Chunk]]] = {}
        self._modelo: ModeloTfidf | None = None
        self._indexed_at: datetime | None = None

    async def abrir(self) -> None:
        return None

    async def fechar(self) -> None:
        return None

    async def hashes(self, chaves: list[Chave]) -> dict[Chave, str]:
        return {c: self._documentos[c][0] for c in chaves if c in self._documentos}

    async def hashes_por_escopo(self, escopos: set[tuple[UUID | None, str]]) -> dict[Chave, str]:
        return {c: h for c, (h, _) in self._documentos.items() if (c[0], c[1]) in escopos}

    async def gravar(self, doc: Documento, chunks: list[Chunk]) -> int:
        self._documentos[doc.chave] = (doc.content_hash, chunks)
        self._modelo = None
        return 0  # nenhum embedding gerado

    async def contar_trechos(self, chave: Chave) -> int:
        return len(self._documentos.get(chave, ("", []))[1])

    async def remover(self, chaves: list[Chave]) -> int:
        removidos = sum(1 for c in chaves if self._documentos.pop(c, None) is not None)
        if removidos:
            self._modelo = None
        return removidos

    async def marcar_indexado(self, quando: datetime) -> None:
        self._indexed_at = quando

    def _modelo_atual(self) -> ModeloTfidf:
        if self._modelo is None:
            self._modelo = ModeloTfidf([c for _, chunks in self._documentos.values() for c in chunks])
        return self._modelo

    async def buscar(self, query: str, top_k: int, project_id: UUID | None) -> tuple[str, list[tuple[Chunk, float]]]:
        escopo = project_id if project_id is not None and any(c[0] == project_id for c in self._documentos) else None
        resultados = self._modelo_atual().search(query, top_k, filtro=lambda c: c.project_id == escopo)
        return ("project" if escopo else "global"), [r for r in resultados if r[1] >= self.min_similarity]

    async def estatisticas(self, project_id: UUID | None = None) -> dict:
        docs = {c: v for c, v in self._documentos.items() if project_id is None or c[0] == project_id}
        return {
            "documents": len(docs),
            "chunks": sum(len(chunks) for _, chunks in docs.values()),
            "sources": sorted({c[1] for c in docs}),
            "indexed_at": self._indexed_at,
        }
