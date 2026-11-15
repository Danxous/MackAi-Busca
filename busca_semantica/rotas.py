"""Rotas internas /v1/*. Só o mackai-orquestrador (mesmo ambiente do Container Apps) chama este serviço."""

import logging
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Query, Request

from .chunking import Documento
from .embeddings import FalhaEmbeddings
from .erros import arquivo_nao_permitido, embeddings_indisponiveis
from .ingestao import motivo_bloqueio_caminho, motivo_bloqueio_conteudo
from .modelos import (Erro, Estatisticas, PedidoBusca, PedidoDocumento, RespostaBusca, RespostaDocumento,
                      RespostaReindex, Trecho)

log = logging.getLogger("mackai.busca")

router = APIRouter(prefix="/v1")

E503 = {503: {"model": Erro, "description": "busca_db (INDICE_INDISPONIVEL) ou embeddings (EMBEDDINGS_INDISPONIVEIS) fora do ar"}}


@router.post("/search", response_model=RespostaBusca, tags=["busca"], responses=E503,
             summary="Trechos mais parecidos com a pergunta, acima do limiar")
async def buscar(pedido: PedidoBusca, request: Request):
    indice = request.app.state.indice
    try:
        escopo, resultados = await indice.buscar(pedido.query, pedido.top_k, pedido.project_id)
    except FalhaEmbeddings as erro:
        log.warning("request_id=%s embeddings da pergunta falharam: %s", request.state.request_id, erro)
        raise embeddings_indisponiveis() from erro
    log.info("request_id=%s busca strategy=%s scope=%s top_k=%s resultados=%s", request.state.request_id,
             indice.estrategia, escopo, pedido.top_k, len(resultados))
    return RespostaBusca(
        strategy=indice.estrategia,
        scope=escopo,
        results=[Trecho(source=c.source, path=c.path, start_line=c.start_line, end_line=c.end_line,
                        similarity=round(similaridade, 4), text=c.text) for c, similaridade in resultados],
    )


@router.get("/stats", response_model=Estatisticas, tags=["índice"], responses=E503,
            summary="Tamanho do índice e horário da última indexação")
async def estatisticas(request: Request,
                       project_id: UUID | None = Query(None, description="Sem projeto = índice inteiro.")):
    dados = await request.app.state.indice.estatisticas(project_id)
    return Estatisticas(strategy=request.app.state.indice.estrategia, indexing=request.app.state.indexador.indexando,
                        **dados)


@router.post("/documents", response_model=RespostaDocumento, tags=["índice"],
             responses={422: {"model": Erro, "description": "Validação ou ARQUIVO_NAO_PERMITIDO (segredo, .env, extensão)"},
                        **E503},
             summary="Indexa ou atualiza um documento avulso")
async def documento(pedido: PedidoDocumento, request: Request):
    motivo = motivo_bloqueio_caminho(pedido.path) or motivo_bloqueio_conteudo(pedido.content)
    if motivo:
        log.warning("request_id=%s documento recusado (%s): %s/%s", request.state.request_id, motivo,
                    pedido.source, pedido.path)
        raise arquivo_nao_permitido(motivo)
    doc = Documento(pedido.source, pedido.path, pedido.content, pedido.project_id)
    try:
        chunks = await request.app.state.indexador.documento_avulso(doc)
    except FalhaEmbeddings as erro:
        raise embeddings_indisponiveis() from erro
    return RespostaDocumento(chunks=chunks)


@router.post("/reindex", response_model=RespostaReindex, tags=["índice"], responses=E503,
             summary="Reindexa todas as fontes de fontes.json (só os arquivos alterados geram embeddings)")
async def reindexar(request: Request):
    resultado = await request.app.state.indexador.reindexar()
    return RespostaReindex(**asdict(resultado))
