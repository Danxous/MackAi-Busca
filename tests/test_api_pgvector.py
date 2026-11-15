"""Integração com PostgreSQL + pgvector de verdade e o embedder falso (US 45). Precisa de TEST_DATABASE_URL."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from busca_semantica.main import criar_app

from .conftest import PROJETO


def test_busca_com_embeddings(cliente_pg):
    assert cliente_pg.post("/v1/reindex").json()["documents"] == 3
    corpo = cliente_pg.post("/v1/search", json={"query": "Onde fica a chave do Gemini?"}).json()
    assert corpo["strategy"] == "embedding" and corpo["scope"] == "global"
    assert corpo["results"][0]["path"] == "orquestrador/config.py"
    similaridades = [r["similarity"] for r in corpo["results"]]
    assert similaridades == sorted(similaridades, reverse=True)


def test_documento_inserido_vem_em_primeiro(cliente_pg):
    texto = "O teste de integração do endpoint de busca confere o vetor retornado pelo pgvector."
    assert cliente_pg.post("/v1/documents", json={"source": "testes", "path": "integ.md", "content": texto}).json() == {"chunks": 1}
    corpo = cliente_pg.post("/v1/search", json={"query": texto}).json()
    assert corpo["results"][0]["path"] == "integ.md"
    assert corpo["results"][0]["similarity"] == pytest.approx(1.0, abs=1e-3)


def test_segunda_ingestao_sem_mudanca_nao_chama_o_embedder(cliente_pg, embedder):
    primeira = cliente_pg.post("/v1/reindex").json()
    assert primeira["embedded_chunks"] == 3
    chamadas = embedder.chamadas
    segunda = cliente_pg.post("/v1/reindex").json()
    assert segunda["skipped_documents"] == 3 and segunda["embedded_chunks"] == 0
    assert embedder.chamadas == chamadas


def test_arquivo_alterado_e_apagado(cliente_pg, base):
    cliente_pg.post("/v1/reindex")
    (base / "cache.md").write_text("Agora o cache usa Memcached.", encoding="utf-8")
    (base / "pagamento.md").unlink()
    resultado = cliente_pg.post("/v1/reindex").json()
    assert resultado["embedded_chunks"] == 1 and resultado["removed_documents"] == 1
    stats = cliente_pg.get("/v1/stats").json()
    assert stats["strategy"] == "embedding" and stats["documents"] == 2 and stats["chunks"] == 2
    assert stats["sources"] == ["modulo-7"] and stats["indexed_at"]


def test_resultados_abaixo_do_limiar_nao_voltam(cliente_pg):
    cliente_pg.post("/v1/reindex")
    assert cliente_pg.post("/v1/search", json={"query": "Explique redes de Bravais"}).json()["results"] == []


def test_filtro_por_projeto(cliente_pg):
    cliente_pg.post("/v1/reindex")
    cliente_pg.post("/v1/documents", json={"source": "modulo-3", "path": "pedidos.md", "project_id": PROJETO,
                                           "content": "O serviço de pedidos depende do banco de pedidos."})
    corpo = cliente_pg.post("/v1/search", json={"query": "serviço de pedidos", "project_id": PROJETO}).json()
    assert corpo["scope"] == "project" and [r["path"] for r in corpo["results"]] == ["pedidos.md"]
    geral = cliente_pg.post("/v1/search", json={"query": "serviço de pedidos"}).json()
    assert geral["scope"] == "global" and "pedidos.md" not in [r["path"] for r in geral["results"]]
    assert cliente_pg.get("/v1/stats", params={"project_id": PROJETO}).json()["documents"] == 1


def test_mesmo_caminho_em_projetos_diferentes(cliente_pg):
    for projeto in (None, PROJETO):
        corpo = {"source": "testes", "path": "README.md", "content": f"leia-me {projeto}", "project_id": projeto}
        assert cliente_pg.post("/v1/documents", json=corpo).status_code == 200
    assert cliente_pg.get("/v1/stats").json()["documents"] == 2


def test_banco_fora_do_ar_devolve_503(cfg, embedder):
    cfg_ruim = dataclasses.replace(cfg, database_url="postgresql://mackai:mackai@127.0.0.1:1/nada")
    with TestClient(criar_app(cfg_ruim, embedder=embedder)) as cliente:
        assert cliente.get("/health").status_code == 200
        resposta = cliente.post("/v1/search", json={"query": "oi"})
        assert resposta.status_code == 503 and resposta.json()["code"] == "INDICE_INDISPONIVEL"
