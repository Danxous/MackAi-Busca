# mackai-busca

Busca semântica do **MackAI** (Módulo 7). Transforma o código e os documentos do projeto em trechos e
devolve, para cada pergunta, os trechos mais parecidos em significado. É isso que faz do MackAI um RAG,
e não um chat genérico.

**Não faz:** chamar o modelo de geração de texto, montar prompt nem conhecer usuários ou conversas.

```text
mackai-conversas ──► mackai-orquestrador ──POST /v1/search──► mackai-busca ──► busca_db (PostgreSQL + pgvector)
                                                                   └──► Gemini (embeddings)
```

Stack: Python 3.12, FastAPI, Pydantic v2, asyncpg (SQL puro, sem ORM), pgvector e `google-genai`.

## Rodar localmente

### Com Docker (PostgreSQL com pgvector + serviço)

```bash
python scripts/preparar_conhecimento.py   # monta conhecimento/ a partir de fontes.json
docker compose up --build
```

A API fica em http://localhost:8002 e a documentação interativa em http://localhost:8002/docs. Sem
`GEMINI_API_KEY` no `.env`, o serviço usa TF-IDF em memória e não toca no banco.

### Sem Docker

```bash
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # sem GEMINI_API_KEY = TF-IDF, sem banco
python scripts/preparar_conhecimento.py
uvicorn busca_semantica.main:app --port 8002 --reload
```

Para testar com embeddings, preencha `GEMINI_API_KEY` com a sua chave gratuita do Google AI Studio e
aponte `DATABASE_URL` para um PostgreSQL com a extensão `vector` (por exemplo, o do `docker compose up postgres`).

### Testes

```bash
pytest                                                                         # sem banco: TF-IDF, filtro e chunking
TEST_DATABASE_URL=postgresql://mackai:mackai@localhost:5432/busca_test pytest  # + integração com pgvector
```

Os testes de integração usam um PostgreSQL de verdade (as tabelas são apagadas) e o `EmbedderFalso`,
que gera vetores determinísticos a partir das palavras do texto, sem gastar cota. O teste de
integração de `/v1/search` é o entregável técnico da US 45. No CI, os dois grupos de testes rodam.

## API interna

Contrato completo: [contracts/mackai-busca.openapi.json](contracts/mackai-busca.openapi.json) (gerado
por `python scripts/exportar_openapi.py`) e coleção do Postman em [postman/](postman/) (gerada por
`python scripts/gerar_postman.py`).

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/v1/search` | `{query, top_k, project_id?}` → trechos acima do limiar, do mais parecido para o menos |
| `GET` | `/v1/stats?project_id=` | `strategy`, `documents`, `chunks`, `sources`, `indexed_at` e `indexing` |
| `POST` | `/v1/documents` | Indexa ou atualiza um documento avulso `{source, path, content, project_id?}` → `{chunks}` |
| `POST` | `/v1/reindex` | Reindexa as fontes de `fontes.json`. Só arquivos alterados geram embeddings |
| `GET` | `/health` | Sonda de vida e prontidão (`{"status": "ok"}`) |

```json
POST /v1/search
{ "query": "Como esconder segredos da aplicação?", "top_k": 3, "project_id": "7a1d0f4e-..." }

200
{
  "strategy": "embedding",
  "scope": "global",
  "results": [
    { "source": "modulo-7", "path": "mackai-conversas/assistente_conversacional/config.py",
      "start_line": 1, "end_line": 30, "similarity": 0.71, "text": "trecho completo" }
  ]
}
```

- `results` vazio não é erro: nada passou do limiar.
- `scope` é um campo novo em relação ao documento do grupo e não quebra o contrato. Ver "Projetos" abaixo.
- Campos extras no pedido são ignorados.

### Projetos (`project_id`)

O `project_id` (UUID do projeto no Módulo 1) chega pelo Orquestrador.

- Cada documento do índice pertence a um projeto ou à **base comum** do Módulo 7 (`project_id` nulo).
- Com `project_id` e documentos daquele projeto no índice, a busca fica **restrita ao projeto** (`scope: "project"`).
- Sem `project_id`, ou se o projeto ainda não tem documentos, a busca usa a base comum (`scope: "global"`).
  Assim, tudo continua funcionando com um único conjunto de arquivos até os projetos chegarem.
- Para indexar um projeto: uma fonte em `fontes.json` com `"project_id"`, ou `POST /v1/documents` com `project_id`.

### Erros

Formato comum aos serviços: `{"detail": "mensagem legível", "code": "CODIGO"}`. Validação usa o 422 padrão do FastAPI.

| Status | `code` | Quando |
|---|---|---|
| 422 | — | `query` vazia ou acima de 4.000 caracteres, `top_k` fora de 1 a 10, `project_id` que não é UUID, caminho inválido |
| 422 | `ARQUIVO_NAO_PERMITIDO` | `POST /v1/documents` com `.env`, chave, extensão não indexada ou conteúdo com segredo |
| 503 | `INDICE_INDISPONIVEL` | `busca_db` fora do ar. O Orquestrador trata como Busca fora do ar |
| 503 | `EMBEDDINGS_INDISPONIVEIS` | A API do Gemini falhou ao gerar o embedding da pergunta (depois das novas tentativas) |

## Ingestão

**Fontes** ([fontes.json](fontes.json)): cada fonte tem `source`, `path` (pasta em `conhecimento/`) e,
opcionalmente, `project_id`. A lista `repos` é lida só por `scripts/preparar_conhecimento.py`, que roda
no CI antes do `docker build`:

- `mackai-busca`: este repositório (código, testes, docs, contrato, `docs/produto/` com backlog e guia visual);
- `mackai-conversas`: clonado de `gabrielmarinhorosa/MackAi-Conversa`;
- `mvp`: só `docs/microsservicos/` do `MVP-Modulo-7` (a arquitetura antiga do monólito fica de fora);
- `historico_git.txt`: commits das últimas 4 semanas de cada repositório, sem e-mails (US 64 e 89).

Para incluir o Orquestrador ou o repositório de outro grupo, basta uma entrada em `fontes.json` e um novo
deploy. Nenhuma mudança de código é necessária. Repositório privado: secret `CONHECIMENTO_GIT_TOKEN` no GitHub.

**Filtro de segredos (US 29):**

- extensões aceitas iguais às do MVP, mais `.env.example` e `Dockerfile`;
- pastas ignoradas: `node_modules`, `.git`, `dist`, `.venv`, `__pycache__` e `conhecimento`;
- arquivos ignorados: `.env*` (exceto `.env.example`), `*.pem`, `*.key`, `*.pfx`, `*.PublishSettings`,
  `package-lock.json`, binários e qualquer arquivo acima de 200 KB;
- conteúdo com `-----BEGIN ... PRIVATE KEY-----` ou com `api_key`/`secret`/`password` seguido de um valor
  longo também fica fora do índice. O log registra só o caminho, nunca o conteúdo.

**Processo** (em `POST /v1/reindex` e na inicialização, em segundo plano):

1. Calcula o SHA-256 de cada arquivo. Se `(project_id, source, path)` já existe com o mesmo hash, pula.
2. Senão, divide em trechos de 30 linhas com 5 de sobreposição, gera os embeddings em lotes de 20
   (`RETRIEVAL_DOCUMENT`, novas tentativas em 429 e 5xx) e troca os trechos do documento numa única transação.
3. Apaga os documentos das fontes configuradas que não estão mais nelas. Os documentos avulsos de outras
   fontes ficam. Uma fonte cuja pasta não existe é ignorada, sem apagar nada.
4. Atualiza `indexed_at`.

**Fallback TF-IDF:** sem `GEMINI_API_KEY`, o motor do MVP roda em memória com o mesmo contrato
(`strategy: "tfidf"`). Limitação: compara palavras, não significado.

## Dados (`busca_db`)

Tabelas `documents`, `chunks` (`vector(768)`) e `index_state` em
[schema.sql](busca_semantica/schema.sql). Elas são criadas na inicialização, junto com
`CREATE EXTENSION IF NOT EXISTS vector`. O índice único é `(project_id, source, path) NULLS NOT DISTINCT`.
A busca usa a distância de cosseno do pgvector (`<=>`). Trocar `EMBEDDING_MODEL` ou `EMBEDDING_DIMENSIONS`
apaga o índice na inicialização seguinte e reindexa tudo.

## Configuração

| Variável | Padrão | Observação |
|---|---|---|
| `DATABASE_URL` | `postgresql://mackai:mackai@localhost:5432/busca_db` | Secret no Azure (`?sslmode=require`) |
| `GEMINI_API_KEY` | vazio | Secret no Azure. Vazia = TF-IDF |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | |
| `EMBEDDING_DIMENSIONS` | `768` | |
| `EMBEDDING_BATCH_SIZE` | `20` | |
| `MIN_SIMILARITY_EMBEDDING` | `0.5` | Calibrar com as 10 perguntas do documento do grupo |
| `MIN_SIMILARITY_TFIDF` | `0.1` | |
| `FONTES_FILE` | `fontes.json` | |
| `MAX_FILE_KB` | `200` | |
| `REINDEX_ON_STARTUP` | `true` | |

## Estrutura

```text
busca_semantica/
  main.py          # app FastAPI, handler de erros, X-Request-ID e reindexação na inicialização
  rotas.py         # /v1/*
  modelos.py       # contrato (Pydantic)
  ingestao.py      # fontes, filtro de segredos, hash e orquestração da indexação
  chunking.py      # documentos e divisão em trechos (do MVP)
  embeddings.py    # cliente do Gemini e embedder falso para testes
  repositorio.py   # SQL com pgvector (asyncpg)
  tfidf.py         # fallback em memória (motor_de_busca.py do MVP)
  config.py        # variáveis de ambiente
  schema.sql
conhecimento/      # preenchido por scripts/preparar_conhecimento.py; fora do git
docs/produto/      # backlog de US e guia visual (indexados)
docs/deploy-azure.md
contracts/         # OpenAPI exportado
postman/           # coleção e ambiente (gerados)
scripts/           # preparar_conhecimento, exportar_openapi, gerar_postman
tests/
fontes.json
```

## Deploy (Azure Container Apps)

Passo a passo: [docs/deploy-azure.md](docs/deploy-azure.md).

- Imagem `ghcr.io/danxous/mackai-busca`, publicada pelo workflow `ci` a cada push na `main`.
- Container App `mackai-busca` no ambiente `mackai-env`, ingress **interno**, porta 8000, 0,25 vCPU e 0,5 GiB, réplicas de 0 a 1.
- Secrets `DATABASE_URL` (do `busca_db`) e `GEMINI_API_KEY`.

## Limitações

- O TF-IDF (sem chave) compara palavras, não significado.
- Os embeddings dividem a cota da chave com as respostas do Orquestrador. Evitem reindexar tudo perto da
  apresentação. Como o hash pula os arquivos sem mudança, um deploy normal só gera embeddings do que mudou.
- Ainda não há documentos por projeto: os contratos com o Módulo 1 para ler repositório e artefatos de
  cada `project_id` estão a combinar. Até lá, toda busca usa a base comum.
- O repositório do Orquestrador ainda não está em `fontes.json`: adicionem quando estiver público.
