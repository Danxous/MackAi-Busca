"""App FastAPI do mackai-busca: handler de erros, X-Request-ID e reindexação na inicialização."""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .config import Configuracao
from .embeddings import Embedder, EmbedderGemini
from .erros import ErroApi
from .ingestao import Indexador
from .repositorio import IndicePgvector
from .rotas import router
from .tfidf import IndiceTfidf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mackai.busca")

DESCRICAO = """
Busca semântica do MackAI (Módulo 7): transforma o código e os documentos do projeto em trechos e devolve,
para cada pergunta, os trechos mais parecidos em significado. Serviço **interno**: só o `mackai-orquestrador`
chama estas rotas.

**Estratégia:** com `GEMINI_API_KEY`, embeddings do Gemini guardados no PostgreSQL com pgvector
(`strategy: "embedding"`). Sem a chave, TF-IDF em memória (`strategy: "tfidf"`), com o mesmo contrato.

**Projetos:** `project_id` (UUID do Módulo 1) restringe a busca aos documentos daquele projeto. Se o projeto
ainda não tiver documentos indexados, a busca usa a base comum do Módulo 7 e responde `scope: "global"`.

**Erros:** `{"detail": "mensagem legível", "code": "CODIGO"}`. Validação continua no 422 padrão do FastAPI.

**Rastreamento:** o `X-Request-ID` recebido volta na resposta e aparece nos logs.
"""

ESPERA_BANCO_S = 10


def criar_indice(cfg: Configuracao, embedder: Embedder | None):
    if embedder is None and cfg.gemini_api_key:
        embedder = EmbedderGemini(cfg.gemini_api_key, cfg.embedding_model, cfg.embedding_dimensions,
                                  cfg.embedding_batch_size)
    if embedder is None:
        log.info("sem GEMINI_API_KEY: busca por TF-IDF em memória (compara palavras, não significado)")
        return IndiceTfidf(cfg.min_similarity_tfidf)
    return IndicePgvector(cfg, embedder)


async def reindexar_ao_iniciar(indexador: Indexador) -> None:
    """Roda em segundo plano: /health responde na hora e /v1/search usa o que já está no banco."""
    while True:
        try:
            await indexador.indice.abrir()
            break
        except ErroApi:
            log.warning("reindexação inicial: busca_db indisponível, nova tentativa em %s s", ESPERA_BANCO_S)
            await asyncio.sleep(ESPERA_BANCO_S)
    try:
        await indexador.reindexar()
    except Exception:
        log.exception("reindexação inicial falhou")


def criar_app(cfg: Configuracao | None = None, embedder: Embedder | None = None) -> FastAPI:
    """`embedder` existe para os testes trocarem o Gemini pelo EmbedderFalso."""
    cfg = cfg or Configuracao.do_ambiente()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.indice = criar_indice(cfg, embedder)
        app.state.indexador = Indexador(app.state.indice, cfg)
        tarefa = asyncio.create_task(reindexar_ao_iniciar(app.state.indexador)) if cfg.reindex_on_startup else None
        yield
        if tarefa:
            tarefa.cancel()
            with suppress(asyncio.CancelledError):
                await tarefa
        await app.state.indice.fechar()

    app = FastAPI(title="mackai-busca", version="1.0.0", description=DESCRICAO, lifespan=lifespan)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ErroApi)
    async def erro_api(request: Request, erro: ErroApi):
        return JSONResponse({"detail": erro.detail, "code": erro.code}, status_code=erro.status)

    @app.exception_handler(HTTPException)
    async def erro_http(request: Request, erro: HTTPException):
        return JSONResponse({"detail": str(erro.detail), "code": f"HTTP_{erro.status_code}"},
                            status_code=erro.status_code, headers=erro.headers)

    @app.exception_handler(Exception)
    async def erro_inesperado(request: Request, erro: Exception):
        log.exception("request_id=%s erro inesperado", getattr(request.state, "request_id", "-"))
        return JSONResponse({"detail": "Erro interno.", "code": "ERRO_INTERNO"}, status_code=500)

    @app.get("/health", tags=["saúde"], summary="Sonda de vida e prontidão do Container Apps")
    async def health():
        return {"status": "ok"}

    app.include_router(router)
    return app


app = criar_app()
