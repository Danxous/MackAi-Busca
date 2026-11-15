"""Erros da API no formato comum aos serviços: {"detail": "...", "code": "..."} (US 50)."""


class ErroApi(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status = status
        self.code = code
        self.detail = detail


def indice_indisponivel() -> ErroApi:
    return ErroApi(503, "INDICE_INDISPONIVEL", "O índice de busca (busca_db) não respondeu. Tente novamente em instantes.")


def embeddings_indisponiveis() -> ErroApi:
    return ErroApi(503, "EMBEDDINGS_INDISPONIVEIS", "A API de embeddings não respondeu. Tente novamente em instantes.")


def arquivo_nao_permitido(motivo: str) -> ErroApi:
    return ErroApi(422, "ARQUIVO_NAO_PERMITIDO", f"O documento não pode ser indexado: {motivo}.")
