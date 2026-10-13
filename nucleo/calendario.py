"""Dias úteis, feriados e o calendário de obrigações mensais da equipe.

"2 dias" numa sexta é terça. "Vence dia 20" num domingo é sexta ou segunda conforme a
obrigação — isso fica em `obrigacoes.json`, que a equipe edita.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

PASTA = Path(os.path.abspath(__file__)).parent.parent  # a pasta do app

FERIADOS_FIXOS = {(1, 1): "Confraternização", (4, 21): "Tiradentes", (5, 1): "Trabalho",
                  (9, 7): "Independência", (10, 12): "N. Sra. Aparecida", (11, 2): "Finados",
                  (11, 15): "Proclamação da República", (11, 20): "Consciência Negra",
                  (12, 25): "Natal"}
# Feriado municipal não fica no código: vai em `feriados.json` (veja feriados.exemplo.json).


def pascoa(ano: int) -> dt.date:
    """Algoritmo de Meeus/Jones/Butcher."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return dt.date(ano, mes, dia + 1)


def feriados(ano: int) -> dict:
    """{data: nome} do ano: nacionais, móveis e o que estiver em feriados.json (municipais, pontes)."""
    saida = {dt.date(ano, m, d): n for (m, d), n in FERIADOS_FIXOS.items()}
    p = pascoa(ano)
    saida[p - dt.timedelta(days=48)] = "Carnaval"
    saida[p - dt.timedelta(days=47)] = "Carnaval"
    saida[p - dt.timedelta(days=2)] = "Sexta-feira Santa"
    saida[p + dt.timedelta(days=60)] = "Corpus Christi"
    extra = PASTA / "feriados.json"
    if extra.is_file():
        try:
            for texto, nome in json.loads(extra.read_text(encoding="utf-8")).items():
                saida[dt.date.fromisoformat(texto)] = nome
        except (ValueError, OSError):
            pass
    return saida


def e_util(dia: dt.date) -> bool:
    return dia.weekday() < 5 and dia not in feriados(dia.year)


def somar_uteis(inicio: dt.date, dias: int) -> dt.date:
    """`dias` dias úteis depois de `inicio`. 0 devolve o próprio dia, ou o próximo útil."""
    atual = inicio
    if dias == 0:
        while not e_util(atual):
            atual += dt.timedelta(days=1)
        return atual
    passo = 1 if dias > 0 else -1
    restantes = abs(dias)
    while restantes:
        atual += dt.timedelta(days=passo)
        if e_util(atual):
            restantes -= 1
    return atual


def proximo_util(dia: dt.date) -> dt.date:
    return somar_uteis(dia, 0)


def util_anterior(dia: dt.date) -> dt.date:
    atual = dia
    while not e_util(atual):
        atual -= dt.timedelta(days=1)
    return atual


def ajustar_dia(dia: dt.date, regra: str) -> dt.date:
    """Se cair em fim de semana ou feriado: 'antes' puxa, 'depois' empurra, 'exato' mantém."""
    if e_util(dia) or regra == "exato":
        return dia
    return util_anterior(dia) if regra == "antes" else proximo_util(dia)


def proxima_mensal(dia_do_mes: int, regra: str, a_partir: dt.date, minimo: dt.date | None = None) -> dt.date:
    """A próxima ocorrência de "todo mês dia N" cujo dia nominal é >= `a_partir`.

    O dia do mês é o de verdade (dia 1 é dia 1); a regra só mexe quando não é útil, e pode
    puxar para o mês anterior ("dia 1 antecipado" vira 30/10 — e continua sendo a vez de
    novembro). `minimo` descarta ocorrências que, depois do ajuste, ficariam antes dele
    (usado na criação: nada nasce já atrasado). Mês sem o dia (31 em novembro) usa o último.
    """
    ano, mes = a_partir.year, a_partir.month
    for _ in range(14):
        ultimo = (dt.date(ano + (mes == 12), (mes % 12) + 1, 1) - dt.timedelta(days=1)).day
        nominal = dt.date(ano, mes, min(dia_do_mes, ultimo))
        if nominal >= a_partir:
            ajustada = ajustar_dia(nominal, regra)
            if minimo is None or ajustada >= minimo:
                return ajustada
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return a_partir


def mes_seguinte_da_ocorrencia(prazo: dt.date, dia_do_mes: int, regra: str) -> dt.date:
    """O 1º dia do mês depois do mês NOMINAL da ocorrência `prazo`.

    Com "antes", dia 1 pode ter sido gravado como 30/10 — o mês nominal é novembro, então
    a próxima é a de dezembro. Com "depois", dia 31 pode ter ido para 02/11 — nominal outubro.
    """
    ano, mes = prazo.year, prazo.month
    if regra == "antes" and prazo.day > dia_do_mes:
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    elif regra == "depois" and prazo.day < dia_do_mes and prazo.day <= 3:
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return dt.date(ano, mes, 1)


# --------------------------------------------------------------- obrigações
OBRIGACOES_PADRAO = [
    {"nome": "DCTFWeb", "dia": 15, "ajuste": "anterior", "palavras": ["dctfweb", "dctf"]},
    {"nome": "DAS (Simples)", "dia": 20, "ajuste": "posterior", "palavras": ["das", "simples"]},
    {"nome": "GPS / INSS", "dia": 20, "ajuste": "anterior", "palavras": ["gps", "inss"]},
    {"nome": "FGTS", "dia": 20, "ajuste": "anterior", "palavras": ["fgts"]},
    {"nome": "ISS", "dia": 10, "ajuste": "posterior", "palavras": ["iss"]},
    {"nome": "ICMS", "dia": 20, "ajuste": "posterior", "palavras": ["icms", "gia"]},
    {"nome": "PIS/COFINS", "dia": 25, "ajuste": "anterior", "palavras": ["pis", "cofins"]},
    {"nome": "EFD Contribuições", "dia": 15, "ajuste": "posterior",
     "palavras": ["efd contribuicoes", "sped contribuicoes"]},
    {"nome": "EFD-Reinf", "dia": 15, "ajuste": "anterior", "palavras": ["reinf"]},
    {"nome": "Livros fiscais", "dia": 20, "ajuste": "posterior", "palavras": ["livro"]},
]


def obrigacoes() -> list:
    """A lista editável em `obrigacoes.json`; sem o arquivo, a padrão."""
    caminho = PASTA / "obrigacoes.json"
    if caminho.is_file():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return OBRIGACOES_PADRAO


def vencimento(obrigacao: dict, ano: int, mes: int) -> dt.date:
    """O dia da obrigação no mês, puxado para o útil conforme a regra dela."""
    primeiro_do_seguinte = dt.date(ano + (mes == 12), (mes % 12) + 1, 1)
    ultimo = (primeiro_do_seguinte - dt.timedelta(days=1)).day
    dia = dt.date(ano, mes, min(obrigacao.get("dia", 20), ultimo))
    if e_util(dia):
        return dia
    return util_anterior(dia) if obrigacao.get("ajuste") == "anterior" else proximo_util(dia)


def proximas_obrigacoes(hoje: dt.date | None = None, dias: int = 7) -> list:
    """[(data, nome)] que vencem nos próximos `dias`."""
    hoje = hoje or dt.date.today()
    limite = hoje + dt.timedelta(days=dias)
    saida = set()
    for o in obrigacoes():
        for delta in (0, 1):
            ano, mes = hoje.year, hoje.month + delta
            if mes > 12:
                ano, mes = ano + 1, 1
            v = vencimento(o, ano, mes)
            if hoje <= v <= limite:
                saida.add((v, o["nome"]))
    return sorted(saida)


def obrigacao_no_texto(texto_normalizado: str, hoje: dt.date | None = None) -> tuple:
    """(nome, data) da obrigação citada no texto, com o vencimento mais próximo. Ou (None, None)."""
    hoje = hoje or dt.date.today()
    palavras = texto_normalizado.split()
    for o in obrigacoes():
        for p in o.get("palavras", []):
            if (" " in p and p in texto_normalizado) or p in palavras:
                v = vencimento(o, hoje.year, hoje.month)
                if v < hoje:
                    ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
                    v = vencimento(o, ano, mes)
                return o["nome"], v
    return None, None
