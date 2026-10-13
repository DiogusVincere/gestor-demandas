"""Colar a mensagem inteira: WhatsApp, e-mail ou texto corrido vira uma ou mais demandas.

O que se tira de uma mensagem colada:
- o **formato** (linhas `[08/10, 14:32] Fulano: …` são WhatsApp; `De:`/`Assunto:` são e-mail);
- **quem mandou**: e-mail, telefone ou nome — e, por eles, o cliente (`contatos.json` na pasta de
  dados, mais o que a equipe ensinar aqui);
- **os pedidos**: itens numerados ou com marcador viram um pedido cada; senão, as frases com
  "preciso", "pode me mandar", "consegue", ou com um tipo do catálogo; senão, a mensagem toda;
- **as datas** citadas em cada pedido.

Cada pedido passa pelo entendedor da linha única, com o cliente na frente. A mensagem
original vai para a descrição da tarefa, com data e origem.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import catalogo
from .clientes import Indice, normalizar
from .config import email_da_equipe
from .entender import Entendimento, VERBOS_PEDIDO, entender

WHATSAPP = re.compile(r"^\s*\[?(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})(?::\d{2})?\]?\s*-?\s*([^:\n]{1,60}?):\s*(.*)$")
EMAIL_CABECALHO = re.compile(r"^\s*(de|from|remetente|assunto|subject|enviado em|enviada em|sent|data|date|para|to|cc)\s*:\s*(.*)$", re.I)
EMAIL_ENDERECO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TELEFONE = re.compile(r"(?:\+?55\s?)?\(?(\d{2})\)?\s?9?\d{4}[-\s]?\d{4}")
CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
ITEM = re.compile(r"^\s*(?:\d{1,2}[\)\.\-:]|[-*•▪●]|[a-z]\))\s+(.{3,})$", re.I)
PEDIDO = re.compile(r"\b(preciso|precisamos|precisava|pode(?:ria)?s?|consegue|consegues|me manda|me envia|me mande|me envie|gostaria|favor|por favor|solicito|quero|queria|tem como|da pra|dá pra|será que|sera que|necessito|preciso que)\b")
CORTESIA = re.compile(r"^(bom dia|boa tarde|boa noite|oi|ola|olá|tudo bem\??|obrigad[oa]|abra[cç]os?|att\.?|atenciosamente|grat[oa])[\s,!.]*$", re.I)


@dataclass
class Mensagem:
    formato: str = "texto"              # whatsapp | email | texto
    remetente_nome: str = ""
    remetente_email: str = ""
    remetente_telefone: str = ""
    cnpj: str = ""
    quando: str = ""
    assunto: str = ""
    corpo: str = ""                     # só o que a pessoa escreveu, limpo
    pedidos: list = field(default_factory=list)
    cliente: object = None
    cliente_motivo: str = ""
    candidatos: list = field(default_factory=list)
    entendimentos: list = field(default_factory=list)


def contatos_conhecidos(aprendizado: dict | None = None, indice: Indice | None = None) -> dict:
    """e-mail/telefone/CNPJ → código: o `contatos.json` (opcional, ao lado do clientes.json) mais o que a
    equipe ensinou escolhendo o cliente de uma conversa (`aprendizado.remetentes`)."""
    mapa = {}
    if indice is not None:
        mapa.update(indice.contatos())
    for chave, codigo in ((aprendizado or {}).get("remetentes") or {}).items():
        mapa[chave.lower()] = codigo
    return mapa


def _telefone_limpo(texto: str) -> str:
    return re.sub(r"\D", "", texto)[-11:]


def separar_mensagem(texto: str) -> Mensagem:
    """Descobre o formato e separa quem, quando, assunto e o corpo."""
    m = Mensagem()
    linhas = [l.rstrip() for l in texto.strip().splitlines()]
    corpo = []
    falas = [WHATSAPP.match(l) for l in linhas]
    if sum(1 for f in falas if f) >= 1 and len(linhas) <= 80:
        m.formato = "whatsapp"
        autores = {}
        for l, f in zip(linhas, falas):
            if f:
                m.quando = m.quando or f.group(1)
                autores[f.group(3).strip()] = autores.get(f.group(3).strip(), 0) + 1
                corpo.append(f.group(4))
            elif l.strip():
                corpo.append(l)
        if autores:
            m.remetente_nome = max(autores, key=autores.get)
            tel = _telefone_limpo(m.remetente_nome)
            if len(tel) >= 10:
                m.remetente_telefone = tel
    else:
        for l in linhas:
            h = EMAIL_CABECALHO.match(l)
            if h and len(corpo) < 3:
                campo, valor = h.group(1).lower(), h.group(2).strip()
                m.formato = "email"
                if campo in ("de", "from", "remetente"):
                    e = EMAIL_ENDERECO.search(valor)
                    m.remetente_email = e.group(0).lower() if e else ""
                    m.remetente_nome = re.sub(r"<.*?>|\(.*?\)|\"", "", valor).strip() or m.remetente_nome
                elif campo in ("assunto", "subject"):
                    m.assunto = valor
                elif campo in ("enviado em", "enviada em", "sent", "data", "date"):
                    m.quando = valor
                continue
            corpo.append(l)
    texto_corpo = "\n".join(corpo)
    if not m.remetente_email:
        e = EMAIL_ENDERECO.search(texto_corpo)
        if e and not email_da_equipe(e.group(0)):
            m.remetente_email = e.group(0).lower()
    c = CNPJ.search(texto_corpo)
    if c:
        m.cnpj = re.sub(r"\D", "", c.group(0))
    # tira citação de e-mail anterior e assinatura
    texto_corpo = re.split(r"\n\s*(?:-{3,}|_{3,}|>|Em .{5,80} escreveu:|On .{5,80} wrote:|De: )", texto_corpo, maxsplit=1)[0]
    m.corpo = "\n".join(l for l in texto_corpo.splitlines() if not CORTESIA.match(l.strip())).strip()
    return m


def achar_pedidos(corpo: str) -> list:
    """As frases que são pedido. Itens de lista primeiro; senão frases com verbo de pedido ou tipo."""
    linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
    itens = [ITEM.match(l).group(1).strip() for l in linhas if ITEM.match(l)]
    if len(itens) >= 2:
        return itens
    frases = []
    for l in linhas:
        for f in re.split(r"(?<=[.!?;])\s+", l):
            f = f.strip(" .!?;")
            if len(f) >= 6:
                frases.append(f)
    com_pedido = [f for f in frases if PEDIDO.search(normalizar(f).lower())
                  or any(re.search(r"\b" + re.escape(v) + r"\b", normalizar(f).lower()) for v in VERBOS_PEDIDO)
                  or catalogo.achar(f)[0]]
    if com_pedido:
        # frases coladas que falam do mesmo tipo são um pedido só; frase curta sem tipo
        # ("Pode me mandar até amanhã?") é complemento da anterior, não pedido novo
        saida = []
        for f in com_pedido:
            tipo = catalogo.achar(f)[0]
            if saida and tipo and catalogo.achar(saida[-1])[0] == tipo:
                saida[-1] = saida[-1] + ". " + f
            elif saida and not tipo and len(f) < 40:
                saida[-1] = saida[-1] + ". " + f
            else:
                saida.append(f)
        return saida[:6]
    return [corpo.strip()[:160]] if corpo.strip() else []


def interpretar(texto: str, indice: Indice, pessoas=(), hoje: dt.date | None = None,
                aprendizado: dict | None = None) -> Mensagem:
    """A mensagem colada → quem é, o que pediu, e um Entendimento por pedido."""
    hoje = hoje or dt.date.today()
    m = separar_mensagem(texto)
    contatos = contatos_conhecidos(aprendizado, indice)
    if m.remetente_email and m.remetente_email in contatos:
        m.cliente, m.cliente_motivo = indice.achar(contatos[m.remetente_email]), f"pelo e-mail {m.remetente_email}"
    elif m.remetente_telefone and m.remetente_telefone in contatos:
        m.cliente, m.cliente_motivo = indice.achar(contatos[m.remetente_telefone]), "pelo telefone"
    elif m.cnpj and m.cnpj in contatos:
        m.cliente, m.cliente_motivo = indice.achar(contatos[m.cnpj]), "pelo CNPJ"
    if m.cliente is None and m.remetente_email and "@" in m.remetente_email:
        # o domínio do e-mail costuma ser o nome da empresa: financeiro@empresa-exemplo.com.br
        dominio = m.remetente_email.split("@", 1)[1].split(".")[0]
        if dominio not in ("gmail", "hotmail", "outlook", "yahoo", "uol", "bol", "terra", "icloud", "live", "msn"):
            achados = indice.por_nome(dominio, minimo=80)
            if achados:
                m.cliente, m.cliente_motivo = achados[0][0], f"pelo domínio do e-mail ({dominio})"
                m.candidatos = [c for c, p in achados[1:4] if achados[0][1] - p <= 8]
    if m.cliente is None and m.remetente_nome and not m.remetente_telefone:
        achados = indice.por_nome(m.remetente_nome, minimo=70)
        if achados:
            m.cliente, m.cliente_motivo = achados[0][0], f"pelo nome “{m.remetente_nome}”"
            m.candidatos = [c for c, p in achados[1:4] if achados[0][1] - p <= 10]
    # mensagens curtas sem cabeçalho: o cliente pode estar no próprio texto
    m.pedidos = achar_pedidos(m.corpo or texto)
    for pedido in m.pedidos:
        linha = pedido
        if m.cliente and not re.search(r"\b" + re.escape(m.cliente.codigo) + r"\b", normalizar(pedido)):
            linha = f"{m.cliente.codigo} {pedido}"
        e = entender(linha, indice, pessoas=pessoas, hoje=hoje, aprendizado=aprendizado)
        if m.cliente and e.cliente is None:
            e.cliente, e.cliente_motivo = m.cliente, m.cliente_motivo
        elif e.cliente is not None and m.cliente is None and len(m.pedidos) == 1:
            m.cliente, m.cliente_motivo = e.cliente, e.cliente_motivo
        if m.formato in ("whatsapp", "email") and not e.origem:
            e.origem = m.formato
        if m.assunto and len(e.titulo) < 8:
            e.titulo = m.assunto[:120]
        m.entendimentos.append(e)
    return m


def descricao_da_mensagem(m: Mensagem) -> str:
    """O que vai para a descrição da tarefa: a mensagem como chegou."""
    cab = []
    if m.formato == "whatsapp":
        cab.append(f"WhatsApp de {m.remetente_nome or 'cliente'}" + (f" em {m.quando}" if m.quando else ""))
    elif m.formato == "email":
        cab.append(f"E-mail de {m.remetente_nome or m.remetente_email or 'cliente'}" + (f" em {m.quando}" if m.quando else "")
                   + (f" — assunto: {m.assunto}" if m.assunto else ""))
    else:
        cab.append("Mensagem colada")
    return "\n".join(cab) + "\n\n" + (m.corpo or "").strip()
