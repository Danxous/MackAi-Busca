"""Embeddings do Gemini (US 21 e 24) e um embedder falso e determinístico para os testes (US 42)."""

import asyncio
import hashlib
import logging
import math
from typing import Literal, Protocol

from google import genai
from google.genai import errors, types

from .tfidf import tokenize

log = logging.getLogger("mackai.busca")

Tarefa = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class FalhaEmbeddings(Exception):
    pass


class Embedder(Protocol):
    modelo: str
    dimensoes: int

    async def embed(self, textos: list[str], tarefa: Tarefa) -> list[list[float]]: ...


class EmbedderGemini:
    """Um cliente por app. Lotes de `tamanho_lote` textos; 429 e 5xx esperam e tentam de novo."""

    def __init__(self, api_key: str, modelo: str, dimensoes: int, tamanho_lote: int = 20,
                 tentativas: int = 5, espera_inicial_s: float = 2.0):
        self._client = genai.Client(api_key=api_key)
        self.modelo = modelo
        self.dimensoes = dimensoes
        self._lote = tamanho_lote
        self._tentativas = tentativas
        self._espera = espera_inicial_s

    async def embed(self, textos: list[str], tarefa: Tarefa) -> list[list[float]]:
        vetores: list[list[float]] = []
        for inicio in range(0, len(textos), self._lote):
            vetores.extend(await self._embed_lote(textos[inicio:inicio + self._lote], tarefa))
        return vetores

    async def _embed_lote(self, textos: list[str], tarefa: Tarefa) -> list[list[float]]:
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = await self._client.aio.models.embed_content(
                    model=self.modelo,
                    contents=textos,
                    config=types.EmbedContentConfig(task_type=tarefa, output_dimensionality=self.dimensoes),
                )
                vetores = [e.values for e in resposta.embeddings or []]
                if len(vetores) != len(textos) or any(len(v or []) != self.dimensoes for v in vetores):
                    raise FalhaEmbeddings("resposta de embeddings fora do esperado")
                return vetores
            except errors.APIError as erro:
                temporario = erro.code == 429 or (erro.code or 0) >= 500
                if not temporario or tentativa == self._tentativas:
                    raise FalhaEmbeddings(f"Gemini respondeu {erro.code}") from erro
                espera = self._espera * 2 ** (tentativa - 1)
                log.warning("embeddings: Gemini respondeu %s, nova tentativa em %.0f s", erro.code, espera)
                await asyncio.sleep(espera)
            except Exception as erro:  # rede, timeout, resposta inválida
                if isinstance(erro, FalhaEmbeddings) or tentativa == self._tentativas:
                    raise FalhaEmbeddings(str(erro)) from erro
                await asyncio.sleep(self._espera)
        raise FalhaEmbeddings("sem resposta")  # inalcançável


class EmbedderFalso:
    """Vetores determinísticos: cada palavra cai numa dimensão pelo hash. Textos com as mesmas palavras ficam
    parecidos, então dá para testar pgvector e o limiar sem gastar cota. Conta as chamadas recebidas."""

    def __init__(self, dimensoes: int = 768, modelo: str = "falso"):
        self.modelo = modelo
        self.dimensoes = dimensoes
        self.chamadas = 0
        self.textos_recebidos = 0

    async def embed(self, textos: list[str], tarefa: Tarefa) -> list[list[float]]:
        self.chamadas += 1
        self.textos_recebidos += len(textos)
        return [self._vetor(t) for t in textos]

    def _vetor(self, texto: str) -> list[float]:
        vetor = [0.0] * self.dimensoes
        for token in tokenize(texto):
            indice = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % self.dimensoes
            vetor[indice] += 1.0
        norma = math.sqrt(sum(v * v for v in vetor))
        if not norma:  # texto sem palavras: vetor fixo, para o pgvector não receber um vetor nulo
            vetor[0], norma = 1.0, 1.0
        return [v / norma for v in vetor]
