"""O catálogo: os tipos de demanda que a equipe recebe, com prazo, importância e checklist.

Mora em `catalogo.json`, na pasta do app, que a equipe edita. Aqui só se lê e se procura
o tipo dentro do texto — a palavra mais longa que casar manda, para "carta de
faturamento" não cair em "faturamento pro banco".
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .clientes import normalizar

PASTA = Path(os.path.abspath(__file__)).parent.parent
ARQUIVO = PASTA / "catalogo.json"

_cache: dict = {"quando": 0.0, "tipos": {}}


def tipos() -> dict:
    """{chave: {nome, palavras, prazo_uteis, importancia, checklist}}; relê quando o json muda."""
    try:
        mtime = ARQUIVO.stat().st_mtime
    except OSError:
        return _cache["tipos"]
    if mtime != _cache["quando"]:
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
            _cache["tipos"] = dados.get("tipos", {})
            _cache["quando"] = mtime
        except (ValueError, OSError):
            pass
    return _cache["tipos"]


def info(chave: str) -> dict:
    return tipos().get(chave, {})


def nome(chave: str) -> str:
    return info(chave).get("nome", chave or "")


def _padrao(palavra: str):
    """A palavra do catálogo com plural tolerado: "emitir nota" também casa "emitir notas"."""
    partes = [re.escape(p) + r"s?" for p in palavra.split()]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(partes) + r"(?![a-z0-9])")


def achar_todos(texto_normalizado: str) -> list:
    """[(chave, palavra, posição)] de todo tipo citado, em ordem de aparição; o mais longo manda
    quando dois casam no mesmo lugar."""
    alvo = " " + normalizar(texto_normalizado).lower() + " "
    achados = []
    for chave, dados in tipos().items():
        for palavra in dados.get("palavras", []):
            p = normalizar(palavra).lower()
            if not p:
                continue
            for m in _padrao(p).finditer(alvo):
                achados.append((chave, p, m.start() - 1, m.end() - 1))
    achados.sort(key=lambda x: (x[2], -(x[3] - x[2])))
    saida, fim_anterior = [], -1
    for chave, p, inicio, fim in achados:
        if inicio < fim_anterior:
            continue  # está dentro de um casamento mais longo que começou antes
        saida.append((chave, p, inicio))
        fim_anterior = fim
    return saida


def achar(texto_normalizado: str) -> tuple:
    """(chave, palavra que casou) do tipo mais específico citado no texto, ou ('', '')."""
    todos = achar_todos(texto_normalizado)
    if not todos:
        return "", ""
    chave, palavra, _i = max(todos, key=lambda x: len(x[1]))
    return chave, palavra


def checklist(chave: str) -> list:
    return list(info(chave).get("checklist", []))


def prazo_uteis(chave: str) -> int | None:
    valor = info(chave).get("prazo_uteis")
    return int(valor) if isinstance(valor, (int, float)) else None


def importancia(chave: str) -> str:
    return info(chave).get("importancia", "media")
