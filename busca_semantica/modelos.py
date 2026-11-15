"""Modelos Pydantic: o contrato interno /v1/* consumido pelo mackai-orquestrador."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

Estrategia = Literal["embedding", "tfidf"]

TextoBusca = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
NomeFonte = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
def _caminho_relativo(valor: str) -> str:
    partes = valor.split("/")
    if valor.startswith("/") or "\\" in valor or "\x00" in valor or ".." in partes or "" in partes:
        raise ValueError("use um caminho relativo com '/', sem '..', sem barra inicial e sem partes vazias")
    return valor


Caminho = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
                    AfterValidator(_caminho_relativo)]


class Erro(BaseModel):
    detail: str
    code: str


class PedidoBusca(BaseModel):
    query: TextoBusca = Field(description="Pergunta (ou pergunta anterior + atual). De 1 a 4.000 caracteres.")
    top_k: int = Field(3, ge=1, le=10)
    project_id: UUID | None = Field(
        None, description="Projeto do Módulo 1. Se o projeto tiver documentos indexados, a busca fica restrita a "
                          "eles; senão, usa a base comum do Módulo 7.")

    model_config = {"json_schema_extra": {"examples": [
        {"query": "Como esconder segredos da aplicação?", "top_k": 3},
        {"query": "Quais serviços dependem do banco de pedidos?", "top_k": 3,
         "project_id": "7a1d0f4e-2b6c-4c1e-9f3a-5d8e7c6b4a01"},
    ]}}


class Trecho(BaseModel):
    source: str = Field(description="Fonte do trecho, por exemplo `modulo-7`.")
    path: str = Field(description="Caminho relativo à raiz da fonte.")
    start_line: int
    end_line: int
    similarity: float = Field(description="Similaridade de cosseno, de 0 a 1.")
    text: str = Field(description="Trecho completo. Quem corta o pedaço exibido é o Orquestrador.")


class RespostaBusca(BaseModel):
    strategy: Estrategia
    scope: Literal["project", "global"] = Field(
        description="`project` quando a busca ficou restrita ao `project_id`; `global` na base comum.")
    results: list[Trecho] = Field(description="Só os trechos acima do limiar, do mais parecido para o menos. "
                                              "Vazio não é erro.")


class Estatisticas(BaseModel):
    strategy: Estrategia
    documents: int
    chunks: int
    sources: list[str]
    indexed_at: datetime | None
    indexing: bool = Field(description="`true` enquanto uma reindexação está rodando.")


class PedidoDocumento(BaseModel):
    source: NomeFonte
    path: Caminho
    content: Annotated[str, StringConstraints(min_length=1, max_length=200 * 1024)]
    project_id: UUID | None = Field(None, description="Projeto do Módulo 1 dono do documento. Nulo = base comum.")

    model_config = {"json_schema_extra": {"examples": [
        {"source": "modulo-7", "path": "docs/novo.md", "content": "texto do documento"},
    ]}}


class RespostaDocumento(BaseModel):
    chunks: int


class RespostaReindex(BaseModel):
    documents: int = Field(description="Documentos encontrados nas fontes depois do filtro.")
    embedded_chunks: int = Field(description="Trechos que geraram embeddings nesta rodada (0 no TF-IDF).")
    skipped_documents: int = Field(description="Documentos com o mesmo hash, pulados.")
    removed_documents: int = Field(description="Documentos que saíram das fontes e foram apagados do índice.")
    failed_documents: int = Field(0, description="Documentos que falharam nos embeddings; entram na próxima rodada.")
