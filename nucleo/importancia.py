"""O farol da demanda — e o motivo, sempre escrito.

Importância só pelo texto é fraca: "agora" para um cliente é educação, para outro
é desespero. Então são quatro sinais somados — palavras, prazo, calendário fiscal
e histórico do cliente — e o que a pessoa corrigiu uma vez vale mais que todos.
"""
from __future__ import annotations

import datetime as dt

from . import calendario, catalogo

URGENTES = {"urgente": 2, "urgencia": 2, "pra ontem": 3, "para ontem": 3, "agora": 2,
            "hoje": 1, "imediato": 2, "imediatamente": 2, "correndo": 1, "rapido": 1,
            "banco": 1, "licitacao": 2, "fiscalizacao": 2, "multa": 2, "intimacao": 2,
            "notificacao": 1, "bloqueio": 2, "bloqueado": 2, "prazo final": 2, "ultimo dia": 2}
NIVEIS = ("baixa", "media", "alta")


def avaliar(texto_normalizado: str, tipo: str, prazo: dt.date | None,
            abertas_do_cliente: int = 0, aprendido: str = "",
            hoje: dt.date | None = None) -> tuple:
    """(importancia, motivo). `aprendido` é o que a pessoa escolheu da última vez para
    este cliente+tipo e, se existir, manda."""
    hoje = hoje or dt.date.today()
    if aprendido in NIVEIS:
        return aprendido, "como você escolheu da última vez"

    pontos = {"baixa": 0, "media": 1, "alta": 2}.get(catalogo.importancia(tipo), 1)
    motivos = []
    if tipo:
        motivos.append(f"{catalogo.nome(tipo).lower()} costuma ser {catalogo.importancia(tipo)}")

    alvo = " " + texto_normalizado + " "
    achadas = [p for p in URGENTES if f" {p} " in alvo or f" {p}," in alvo or f" {p}." in alvo]
    if achadas:
        pontos += max(URGENTES[p] for p in achadas)
        motivos.append("“" + "”, “".join(achadas[:2]) + "” no texto")

    if prazo is not None:
        faltam = (prazo - hoje).days
        if faltam <= 0:
            pontos += 2
            motivos.append("vence hoje" if faltam == 0 else f"já venceu há {-faltam} dia(s)")
        elif faltam <= 2:
            pontos += 1
            motivos.append(f"vence em {faltam} dia(s)")

    nome_obrig, data_obrig = calendario.obrigacao_no_texto(texto_normalizado, hoje)
    if nome_obrig and data_obrig and 0 <= (data_obrig - hoje).days <= 5:
        pontos += 1
        motivos.append(f"{nome_obrig} vence {data_obrig:%d/%m}")

    if abertas_do_cliente >= 3:
        pontos += 1
        motivos.append(f"o cliente já tem {abertas_do_cliente} demandas abertas")

    nivel = "alta" if pontos >= 3 else "media" if pontos >= 1 else "baixa"
    return nivel, "; ".join(motivos) if motivos else "nada no texto pede pressa"
