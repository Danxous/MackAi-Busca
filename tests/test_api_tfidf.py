"""Contrato /v1/* sem GEMINI_API_KEY: TF-IDF em memória, sem banco."""

from .conftest import CHAVE_FALSA, PROJETO, escrever


def test_health(cliente_tfidf):
    assert cliente_tfidf.get("/health").json() == {"status": "ok"}


def test_sem_chave_usa_tfidf(cliente_tfidf):
    cliente_tfidf.post("/v1/reindex")
    corpo = cliente_tfidf.post("/v1/search", json={"query": "Como funciona o serviço de pagamento?"}).json()
    assert corpo["strategy"] == "tfidf"
    assert corpo["scope"] == "global"
    primeiro = corpo["results"][0]
    assert primeiro["source"] == "modulo-7" and primeiro["path"] == "pagamento.md"
    assert set(primeiro) == {"source", "path", "start_line", "end_line", "similarity", "text"}


def test_reindex_e_stats(cliente_tfidf):
    assert cliente_tfidf.get("/v1/stats").json()["documents"] == 0
    primeira = cliente_tfidf.post("/v1/reindex").json()
    assert primeira == {"documents": 3, "embedded_chunks": 0, "skipped_documents": 0, "removed_documents": 0,
                        "failed_documents": 0}
    assert cliente_tfidf.post("/v1/reindex").json()["skipped_documents"] == 3
    stats = cliente_tfidf.get("/v1/stats").json()
    assert stats["strategy"] == "tfidf" and stats["documents"] == 3 and stats["chunks"] == 3
    assert stats["sources"] == ["modulo-7"] and stats["indexed_at"] and stats["indexing"] is False


def test_arquivo_apagado_sai_do_indice(cliente_tfidf, base):
    cliente_tfidf.post("/v1/reindex")
    (base / "cache.md").unlink()
    assert cliente_tfidf.post("/v1/reindex").json()["removed_documents"] == 1
    assert cliente_tfidf.get("/v1/stats").json()["documents"] == 2


def test_arquivo_com_segredo_nao_entra(cliente_tfidf, base):
    escrever(base, "vazou.txt", CHAVE_FALSA)
    escrever(base, ".env", "GEMINI_API_KEY=x")
    assert cliente_tfidf.post("/v1/reindex").json()["documents"] == 3


def test_resultados_abaixo_do_limiar_nao_voltam(cliente_tfidf):
    cliente_tfidf.post("/v1/reindex")
    corpo = cliente_tfidf.post("/v1/search", json={"query": "Explique redes de Bravais"}).json()
    assert corpo["results"] == []


def test_documento_avulso(cliente_tfidf):
    resposta = cliente_tfidf.post("/v1/documents", json={
        "source": "testes", "path": "docs/novo.md", "content": "O índice vetorial usa pgvector no PostgreSQL."})
    assert resposta.status_code == 200 and resposta.json() == {"chunks": 1}
    corpo = cliente_tfidf.post("/v1/search", json={"query": "pgvector PostgreSQL"}).json()
    assert corpo["results"][0]["path"] == "docs/novo.md"
    # Reindexar as fontes não apaga documentos avulsos de outra fonte.
    cliente_tfidf.post("/v1/reindex")
    assert cliente_tfidf.get("/v1/stats").json()["documents"] == 4


def test_documento_com_segredo_e_recusado(cliente_tfidf):
    resposta = cliente_tfidf.post("/v1/documents", json={"source": "testes", "path": "a.txt", "content": CHAVE_FALSA})
    assert resposta.status_code == 422 and resposta.json()["code"] == "ARQUIVO_NAO_PERMITIDO"
    resposta = cliente_tfidf.post("/v1/documents", json={"source": "testes", "path": ".env", "content": "x"})
    assert resposta.json()["code"] == "ARQUIVO_NAO_PERMITIDO"


def test_filtro_por_projeto(cliente_tfidf):
    cliente_tfidf.post("/v1/reindex")
    cliente_tfidf.post("/v1/documents", json={"source": "modulo-3", "path": "pedidos.md", "project_id": PROJETO,
                                              "content": "O serviço de pedidos depende do banco de pedidos."})
    no_projeto = cliente_tfidf.post("/v1/search", json={"query": "serviço de pagamento pedidos",
                                                        "project_id": PROJETO}).json()
    assert no_projeto["scope"] == "project"
    assert [r["path"] for r in no_projeto["results"]] == ["pedidos.md"]
    geral = cliente_tfidf.post("/v1/search", json={"query": "serviço de pagamento pedidos"}).json()
    assert geral["scope"] == "global" and "pedidos.md" not in [r["path"] for r in geral["results"]]
    assert cliente_tfidf.get("/v1/stats", params={"project_id": PROJETO}).json()["documents"] == 1


def test_projeto_sem_documentos_usa_base_comum(cliente_tfidf):
    cliente_tfidf.post("/v1/reindex")
    corpo = cliente_tfidf.post("/v1/search", json={"query": "serviço de pagamento", "project_id": PROJETO}).json()
    assert corpo["scope"] == "global" and corpo["results"]


def test_validacao(cliente_tfidf):
    assert cliente_tfidf.post("/v1/search", json={"query": ""}).status_code == 422
    assert cliente_tfidf.post("/v1/search", json={"query": "a" * 4001}).status_code == 422
    assert cliente_tfidf.post("/v1/search", json={"query": "oi", "top_k": 11}).status_code == 422
    assert cliente_tfidf.post("/v1/search", json={"query": "oi", "project_id": "nao-e-uuid"}).status_code == 422
    for caminho in ["../fora.md", "/etc/passwd", "a\\b.md", "a//b.md"]:
        resposta = cliente_tfidf.post("/v1/documents", json={"source": "testes", "path": caminho, "content": "x"})
        assert resposta.status_code == 422, caminho


def test_campos_extras_sao_aceitos(cliente_tfidf):
    resposta = cliente_tfidf.post("/v1/search", json={"query": "pagamento", "history": [], "outro": 1})
    assert resposta.status_code == 200


def test_request_id_volta_na_resposta(cliente_tfidf):
    resposta = cliente_tfidf.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resposta.headers["X-Request-ID"] == "abc-123"
