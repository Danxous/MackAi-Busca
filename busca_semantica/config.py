"""Configuração lida das variáveis de ambiente.

Os testes criam uma `Configuracao` própria com `dataclasses.replace` em vez de mexer no ambiente.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent


def _bool(valor: str) -> bool:
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


@dataclass(frozen=True)
class Configuracao:
    database_url: str = "postgresql://mackai:mackai@localhost:5432/busca_db"
    # Vazia = TF-IDF em memória (sem banco e sem cota). Preenchida = embeddings do Gemini + pgvector.
    gemini_api_key: str = ""
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 20
    min_similarity_embedding: float = 0.5
    min_similarity_tfidf: float = 0.1
    fontes_file: Path = RAIZ / "fontes.json"
    max_file_kb: int = 200
    reindex_on_startup: bool = True
    chunk_lines: int = 30
    chunk_overlap: int = 5
    max_query_chars: int = 4000

    @classmethod
    def do_ambiente(cls) -> "Configuracao":
        padrao = cls()
        return cls(
            database_url=os.getenv("DATABASE_URL", padrao.database_url),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            embedding_model=os.getenv("EMBEDDING_MODEL", padrao.embedding_model),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", padrao.embedding_dimensions)),
            embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", padrao.embedding_batch_size)),
            min_similarity_embedding=float(os.getenv("MIN_SIMILARITY_EMBEDDING", padrao.min_similarity_embedding)),
            min_similarity_tfidf=float(os.getenv("MIN_SIMILARITY_TFIDF", padrao.min_similarity_tfidf)),
            fontes_file=Path(os.getenv("FONTES_FILE", padrao.fontes_file)),
            max_file_kb=int(os.getenv("MAX_FILE_KB", padrao.max_file_kb)),
            reindex_on_startup=_bool(os.getenv("REINDEX_ON_STARTUP", "true")),
        )
