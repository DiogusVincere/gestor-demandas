"""Configuração local que não é dado: hoje só o domínio de e-mail da equipe.

Ordem: variável de ambiente `DOMINIO_EQUIPE` > `config.json` ao lado do `servidor.py`
(copie de `config.exemplo.json`) > o padrão `empresa.exemplo`.

O domínio é como a conversa colada sabe que um e-mail é de alguém da equipe, e não do cliente.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PASTA = Path(os.path.abspath(__file__)).parent.parent
ARQUIVO = PASTA / "config.json"
PADRAO = {"dominio_equipe": "empresa.exemplo"}

_cache: dict = {"mtime": None, "dados": {}}


def ler() -> dict:
    """O `config.json` como dict (relido quando muda; vazio se não existir)."""
    try:
        mtime = ARQUIVO.stat().st_mtime
    except OSError:
        _cache["mtime"], _cache["dados"] = None, {}
        return {}
    if mtime != _cache["mtime"]:
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
            _cache["dados"] = dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            _cache["dados"] = {}
        _cache["mtime"] = mtime
    return _cache["dados"]


def dominio_equipe() -> str:
    """Só o domínio, minúsculo e sem o "@": "empresa.exemplo"."""
    valor = os.environ.get("DOMINIO_EQUIPE") or ler().get("dominio_equipe") or PADRAO["dominio_equipe"]
    return str(valor).strip().lower().lstrip("@")


def email_da_equipe(email: str) -> bool:
    """True quando o e-mail é do domínio da equipe."""
    return bool(email) and str(email).strip().lower().endswith("@" + dominio_equipe())
