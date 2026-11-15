"""Gera a coleção e o ambiente local do Postman em postman/ (rode depois de mudar o contrato).

    python scripts/gerar_postman.py
    npx newman run postman/mackai-busca.postman_collection.json -e postman/mackai-local.postman_environment.json

No Azure, a Busca tem ingress interno: a coleção só roda localmente ou no docker-compose do grupo.
"""

import json
from pathlib import Path

POSTMAN = Path(__file__).resolve().parent.parent / "postman"


def req(nome, metodo, rota, corpo=None, testes=()):
    caminho = rota.split("?")[0]
    item = {
        "name": nome,
        "request": {
            "method": metodo,
            "header": [{"key": "Content-Type", "value": "application/json"}] if corpo is not None else [],
            "url": {"raw": "{{baseUrl}}" + rota, "host": ["{{baseUrl}}"], "path": [p for p in caminho.split("/") if p]},
        },
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": list(testes)}}],
    }
    if "?" in rota:
        item["request"]["url"]["query"] = [{"key": k, "value": v} for k, v in
                                           (p.split("=") for p in rota.split("?")[1].split("&"))]
    if corpo is not None:
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(corpo, ensure_ascii=False, indent=2),
                                   "options": {"raw": {"language": "json"}}}
    return item


def status(n):
    return [f'pm.test("status {n}", () => pm.response.to.have.status({n}));']


BUSCA_NO_CONTRATO = [
    "const b = pm.response.json();",
    'pm.test("busca no contrato", () => {',
    '  pm.expect(b).to.have.keys("strategy", "scope", "results");',
    '  pm.expect(["embedding", "tfidf"]).to.include(b.strategy);',
    '  b.results.forEach(r => pm.expect(r).to.have.keys("source", "path", "start_line", "end_line", "similarity", "text"));',
    "});",
]

COLECAO = {
    "info": {
        "_postman_id": "3c0a6f52-9d1e-4b7a-8e25-6a4f1d9c7b30",
        "name": "mackai-busca",
        "description": "API interna do mackai-busca (Módulo 7), chamada pelo mackai-orquestrador.",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        req("Sonda /health", "GET", "/health", testes=status(200) + [
            'pm.test("status ok", () => pm.expect(pm.response.json().status).to.eql("ok"));']),
        req("Reindexar fontes", "POST", "/v1/reindex", testes=status(200) + [
            'pm.test("campos", () => pm.expect(pm.response.json()).to.include.keys('
            '"documents", "embedded_chunks", "skipped_documents", "removed_documents"));']),
        req("Estatísticas", "GET", "/v1/stats", testes=status(200) + [
            "const s = pm.response.json();",
            'pm.test("campos", () => pm.expect(s).to.have.keys("strategy", "documents", "chunks", "sources", "indexed_at", "indexing"));',
            'pm.test("índice com documentos", () => pm.expect(s.documents).to.be.above(0));',
        ]),
        req("Documento avulso", "POST", "/v1/documents",
            corpo={"source": "postman", "path": "docs/postman.md", "content": "Documento criado pela coleção do Postman."},
            testes=status(200) + ['pm.test("chunks", () => pm.expect(pm.response.json().chunks).to.be.above(0));']),
        req("Busca", "POST", "/v1/search", corpo={"query": "Como esconder segredos da aplicação?", "top_k": 3},
            testes=status(200) + BUSCA_NO_CONTRATO),
        req("Busca num projeto", "POST", "/v1/search",
            corpo={"query": "Como funciona a busca?", "top_k": 3, "project_id": "{{projectId}}"},
            testes=status(200) + BUSCA_NO_CONTRATO),
        req("Pergunta vazia (422)", "POST", "/v1/search", corpo={"query": ""}, testes=status(422)),
        req("top_k acima de 10 (422)", "POST", "/v1/search", corpo={"query": "oi", "top_k": 11}, testes=status(422)),
        req("Documento com segredo (422)", "POST", "/v1/documents",
            corpo={"source": "postman", "path": ".env", "content": "x"},
            testes=status(422) + ['pm.test("code", () => pm.expect(pm.response.json().code).to.eql("ARQUIVO_NAO_PERMITIDO"));']),
    ],
}

AMBIENTE = {
    "id": "8b2e4f17-5a3c-4d69-b0e1-2c7f9a6d5e43",
    "name": "mackai-busca-local",
    "values": [
        {"key": "baseUrl", "value": "http://localhost:8002", "enabled": True},
        {"key": "projectId", "value": "7a1d0f4e-2b6c-4c1e-9f3a-5d8e7c6b4a01", "enabled": True},
    ],
}

POSTMAN.mkdir(exist_ok=True)
for nome, conteudo in [("mackai-busca.postman_collection.json", COLECAO), ("mackai-local.postman_environment.json", AMBIENTE)]:
    (POSTMAN / nome).write_text(json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"postman/{nome}")
