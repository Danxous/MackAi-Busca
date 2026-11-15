"""Chunking, cosseno e TF-IDF (testes do MVP adaptados) e o filtro de segredos."""

import asyncio

from busca_semantica.chunking import Chunk, split_into_chunks
from busca_semantica.embeddings import EmbedderFalso
from busca_semantica.ingestao import Fonte, coletar, motivo_bloqueio_caminho, motivo_bloqueio_conteudo
from busca_semantica.tfidf import ModeloTfidf, cosine_similarity

from .conftest import CHAVE_FALSA, CHAVE_PRIVADA_FALSA, escrever


def test_cosine_similarity():
    assert cosine_similarity({"a": 1.0}, {"a": 2.0}) == 1.0
    assert cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0


def test_chunking_with_overlap():
    content = "\n".join(f"linha {i}" for i in range(70))
    chunks = split_into_chunks("modulo-7", "doc.md", content)
    assert chunks[0].start_line == 1 and chunks[1].start_line == 26
    assert chunks[-1].end_line == 70
    assert all(c.source == "modulo-7" for c in chunks)


def test_tfidf_finds_relevant_file():
    chunks = [Chunk("m", "pagamento.md", 1, 1, "O serviço de pagamento publica o evento payment.created."),
              Chunk("m", "cache.md", 1, 1, "Bibliotecas de cache recomendadas: Redis.")]
    resultados = ModeloTfidf(chunks).search("Como funciona o serviço de pagamento?")
    assert resultados[0][0].path == "pagamento.md"


def test_filtro_por_caminho():
    assert motivo_bloqueio_caminho("docs/a.md") is None
    assert motivo_bloqueio_caminho(".env.example") is None
    for caminho in [".env", "app/.env.local", "certs/chave.pem", "id.key", "site.PublishSettings",
                    "frontend/package-lock.json", "node_modules/x/index.js", "imagem.png"]:
        assert motivo_bloqueio_caminho(caminho), caminho


def test_filtro_por_conteudo():
    assert motivo_bloqueio_conteudo("GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')") is None
    assert motivo_bloqueio_conteudo(CHAVE_FALSA)
    assert motivo_bloqueio_conteudo(CHAVE_PRIVADA_FALSA)
    assert motivo_bloqueio_conteudo("pass" + "word: 'SenhaMuitoForte12345'")


def test_coleta_ignora_segredos_e_arquivos_grandes(tmp_path):
    escrever(tmp_path, "ok.md", "documento normal")
    escrever(tmp_path, ".env", "qualquer coisa")
    escrever(tmp_path, "config.txt", CHAVE_FALSA)
    escrever(tmp_path, "certs/servidor.pem", "x")
    escrever(tmp_path, "deploy.md", CHAVE_PRIVADA_FALSA)
    escrever(tmp_path, "frontend/package-lock.json", "{}")
    escrever(tmp_path, "grande.md", "a" * 300 * 1024)
    documentos = coletar(Fonte("modulo-7", tmp_path), max_file_kb=200)
    assert [d.path for d in documentos] == ["ok.md"]


def test_embedder_falso_e_deterministico():
    embedder = EmbedderFalso(dimensoes=16)
    [a, b] = asyncio.run(embedder.embed(["chave do Gemini", "chave do Gemini"], "RETRIEVAL_DOCUMENT"))
    assert a == b and len(a) == 16
