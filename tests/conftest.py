"""Fixtures comuns.

- Testes de TF-IDF, filtro e chunking rodam sempre, sem banco.
- Testes com pgvector precisam de um PostgreSQL descartável com a extensão vector (as tabelas são apagadas):

    TEST_DATABASE_URL=postgresql://mackai:mackai@localhost:5432/busca_test pytest

  Sem TEST_DATABASE_URL, eles são pulados. No CI, a variável é definida e eles rodam.
"""

import dataclasses
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from busca_semantica.config import Configuracao
from busca_semantica.embeddings import EmbedderFalso
from busca_semantica.main import criar_app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Montados em partes para que este arquivo não seja barrado pelo próprio filtro de segredos ao ser indexado.
CHAVE_FALSA = "GEMINI_API_" + "KEY=" + "AIzaSyFalsaFalsaFalsaFalsa123"
CHAVE_PRIVADA_FALSA = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
PROJETO = "7a1d0f4e-2b6c-4c1e-9f3a-5d8e7c6b4a01"


def escrever(raiz: Path, caminho: str, conteudo: str) -> None:
    arquivo = raiz / caminho
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(conteudo, encoding="utf-8")


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """Uma fonte `modulo-7` com documentos de exemplo e um fontes.json apontando para ela."""
    raiz = tmp_path / "conhecimento" / "modulo-7"
    escrever(raiz, "pagamento.md", "O serviço de pagamento publica o evento payment.created na fila.")
    escrever(raiz, "cache.md", "Bibliotecas de cache recomendadas para a stack: Redis e cachetools.")
    escrever(raiz, "orquestrador/config.py",
             "# A chave do Gemini fica na variável de ambiente GEMINI_API_KEY, nunca no repositório.\n"
             "import os\nGEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')\n")
    (tmp_path / "fontes.json").write_text(json.dumps([{"source": "modulo-7", "path": "conhecimento/modulo-7"}]))
    return raiz


@pytest.fixture
def cfg(tmp_path: Path, base: Path) -> Configuracao:
    return dataclasses.replace(Configuracao(), gemini_api_key="", fontes_file=tmp_path / "fontes.json",
                               reindex_on_startup=False, database_url=TEST_DATABASE_URL or "")


@pytest.fixture
def cliente_tfidf(cfg):
    with TestClient(criar_app(cfg)) as cliente:
        yield cliente


@pytest.fixture
def embedder():
    return EmbedderFalso()


@pytest.fixture
def cliente_pg(cfg, embedder):
    if not TEST_DATABASE_URL:
        pytest.skip("defina TEST_DATABASE_URL para rodar os testes com pgvector")
    import asyncio

    import asyncpg

    async def limpar():
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        await conn.execute("DROP TABLE IF EXISTS chunks, documents, index_state CASCADE")
        await conn.close()

    asyncio.run(limpar())
    # Limiar mais baixo: o embedder falso compara palavras, então a similaridade é menor que a do Gemini.
    with TestClient(criar_app(dataclasses.replace(cfg, min_similarity_embedding=0.2), embedder=embedder)) as cliente:
        yield cliente
