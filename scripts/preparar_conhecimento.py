"""Monta a pasta conhecimento/ a partir de fontes.json, antes do `docker build` (CI) ou do teste local.

    python scripts/preparar_conhecimento.py

Para cada fonte, cada item de `repos` vira uma subpasta:
- `"local": true` copia deste repositório os caminhos de `include`;
- `"url"` clona o repositório (só os commits das últimas 4 semanas) e copia `include` (ou tudo).

Também gera `historico_git.txt` na raiz da fonte, sem e-mails (US 64 e 89). Um repositório que não puder ser
clonado (privado, fora do ar) é pulado com aviso: o build continua com o que deu para baixar.

Para incluir o repositório de outro grupo: adicione em fontes.json uma fonte nova, por exemplo
`{"source": "modulo-3", "path": "conhecimento/modulo-3", "repos": [{"dir": "app", "url": "...", "branch": "main"}]}`
e, se for de um projeto do Módulo 1, `"project_id": "<uuid>"`. Nenhuma mudança de código é necessária.
Repositório privado: defina GIT_TOKEN (secret do GitHub com permissão de leitura).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PERIODO = "4 weeks ago"
IGNORAR = shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "dist",
                                 "frontend_dist", "conhecimento", ".env")


def git(*args: str, cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def url_com_token(url: str) -> str:
    token = os.environ.get("GIT_TOKEN")
    if token and url.startswith("https://"):
        return url.replace("https://", f"https://x-access-token:{token}@", 1)
    return url


def historico(repo: Path, nome: str) -> str:
    try:
        log = git("log", f"--since={PERIODO}", "--date=short", "--format=%h %ad %an %s", "--shortstat", cwd=repo)
    except subprocess.CalledProcessError:
        return ""
    return f"## {nome}\n\n{log.strip()}\n\n" if log.strip() else ""


def copiar(origem: Path, destino: Path, include: list[str] | None) -> None:
    for item in include or [p.name for p in origem.iterdir() if p.name != ".git"]:
        fonte = origem / item
        if not fonte.exists():
            continue
        alvo = destino / item
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if fonte.is_dir():
            shutil.copytree(fonte, alvo, ignore=IGNORAR, dirs_exist_ok=True)
        elif not fonte.name.startswith(".env") or fonte.name == ".env.example":
            shutil.copy2(fonte, alvo)


def preparar_fonte(fonte: dict, tmp: Path) -> None:
    destino = (RAIZ / fonte["path"]).resolve()
    if RAIZ / "conhecimento" not in destino.parents:
        sys.exit(f"{fonte['path']}: o destino precisa ficar dentro de conhecimento/")
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    historicos = []
    for repo in fonte.get("repos", []):
        if repo.get("local"):
            copiar(RAIZ, destino / repo["dir"], repo.get("include"))
            historicos.append(historico(RAIZ, repo["dir"]))
            print(f"  {repo['dir']}: copiado deste repositório")
            continue
        clone = tmp / f"{fonte['source']}-{repo['dir']}"
        try:
            git("clone", "--quiet", f"--shallow-since={PERIODO}", "--branch", repo.get("branch", "main"),
                url_com_token(repo["url"]), str(clone))
        except subprocess.CalledProcessError:
            try:  # sem commits no período, o --shallow-since falha: tenta só o último commit
                git("clone", "--quiet", "--depth", "1", "--branch", repo.get("branch", "main"),
                    url_com_token(repo["url"]), str(clone))
            except subprocess.CalledProcessError as erro:
                print(f"  AVISO {repo['dir']}: não foi possível clonar {repo['url']} ({erro.stderr.strip()[:200]})")
                continue
        copiar(clone, destino / repo["dir"], repo.get("include"))
        historicos.append(historico(clone, repo["dir"]))
        print(f"  {repo['dir']}: clonado de {repo['url']}")
    texto = "".join(historicos)
    if texto:
        (destino / "historico_git.txt").write_text(
            f"# Histórico do git (últimas 4 semanas)\n\n{texto}", encoding="utf-8")


def main() -> None:
    fontes = json.loads((RAIZ / "fontes.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        for fonte in fontes:
            print(f"{fonte['source']} -> {fonte['path']}")
            preparar_fonte(fonte, Path(tmp))


if __name__ == "__main__":
    main()
