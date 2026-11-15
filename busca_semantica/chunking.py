"""Documentos e divisão em trechos de linhas com sobreposição (lógica do MVP, US 26)."""

import hashlib
from dataclasses import dataclass, field
from uuid import UUID

# Identifica um documento no índice: (project_id, source, path). project_id nulo = base comum do Módulo 7.
Chave = tuple[UUID | None, str, str]


@dataclass
class Documento:
    source: str
    path: str  # relativo à raiz da fonte, com "/"
    content: str
    project_id: UUID | None = None
    content_hash: str = field(init=False)

    def __post_init__(self):
        self.content_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def chave(self) -> Chave:
        return (self.project_id, self.source, self.path)


@dataclass
class Chunk:
    source: str
    path: str
    start_line: int
    end_line: int
    text: str
    project_id: UUID | None = None


def split_into_chunks(source: str, path: str, content: str, chunk_lines: int = 30, overlap: int = 5,
                      project_id: UUID | None = None) -> list[Chunk]:
    lines = content.splitlines()
    chunks = []
    step = chunk_lines - overlap
    for start in range(0, max(len(lines), 1), step):
        piece = lines[start:start + chunk_lines]
        text = "\n".join(piece).strip()
        if text:
            chunks.append(Chunk(source, path, start + 1, start + len(piece), text, project_id))
        if start + chunk_lines >= len(lines):
            break
    return chunks
