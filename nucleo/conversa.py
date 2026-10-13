"""A conversa colada: quem falou, o que foi pedido e o que você já combinou.

A primeira versão do "colar" tratava o texto como um bloco: achava o remetente e caçava frases com verbo
de pedido. Aqui a mensagem vira uma CONVERSA, em quatro camadas:

1. **Turnos** — cada fala tem nome, lado (cliente ou equipe) e texto. Reconhece WhatsApp exportado
   (`08/10/2026 14:32 - Nome: …`, `[08/10/2026, 14:32] Nome: …`), WhatsApp Web copiado
   (`[14:32, 08/10/2026] Nome: …`), e-mail com respostas encadeadas (`De:` / `Em … escreveu:`),
   transcrição à mão (`Cliente: …` / `Eu: …`) e texto solto, separado por parágrafo e classificado
   pela VOZ: "preciso que vocês…", "segue em anexo" é o cliente; "vou fazer até sexta",
   "pra ana", "cliente pediu" é você. Seu nome e a Equipe são o lado da equipe; "Você" também.
2. **Pedidos → tarefas com checklist** — das falas do cliente. Pedidos na MESMA frase ficam numa
   tarefa só; o checklist sai da própria frase: enumerações ("balancete, DRE e razão de agosto"),
   vários meses ("de julho a setembro"), perguntas ("Responder: …") e anexos ("Conferir o extrato
   enviado"). Frase só com prazo ou urgência ("preciso até sexta") complementa o pedido anterior.
3. **O que você registrou manda** — das suas falas saem o prazo prometido ("vou mandar até sexta"),
   o que você pediu ao cliente ("me manda o contrato" → "Receber do cliente: contrato"), responsável
   ("pra ana"), prioridade, recorrência e "me avisar".
4. **Status sugerido** pela ordem das falas: você pediu algo e o cliente não mandou → Aguardando
   cliente; ele mandou ("segue em anexo") → A fazer, com o item marcado; você fechou com
   "enviado" → concluída.

Nada aqui usa IA: são regras, e cada decisão guarda o motivo para a tela mostrar.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import catalogo
from .clientes import Indice, normalizar
from .config import email_da_equipe
from .entender import (PEDE_AVISO, VERBOS_INFORMACAO, VERBOS_PEDIDO, achar_cliente, achar_data, achar_pessoa,
                       achar_recorrencia, corrigir_digitacao, entender, separar)
from .mensagem import (CNPJ, CORTESIA, EMAIL_CABECALHO, EMAIL_ENDERECO, ITEM, PEDIDO, _telefone_limpo,
                       contatos_conhecidos)

# ---------------------------------------------------------------- formatos
# 08/10/2026 14:32 - Nome: msg | [08/10/2026, 14:32:10] Nome: msg | [08/10, 14:32] Nome: msg
WA_DATA_HORA = re.compile(r"^\s*\[?(\d{1,2}/\d{1,2}(?:/\d{2,4})?),?\s+(\d{1,2}:\d{2})(?::\d{2})?\]?\s*-?\s*([^:\n]{1,60}?):\s(.*)$")
# [14:32, 08/10/2026] Nome: msg  (WhatsApp Web e Desktop, ao copiar mensagens selecionadas)
WA_HORA_DATA = re.compile(r"^\s*\[(\d{1,2}:\d{2})(?::\d{2})?,\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\]\s*([^:\n]{1,60}?):\s(.*)$")
# Cliente: msg | Eu: msg | Maria Silva: msg  (transcrição à mão)
NOME_FALA = re.compile(r"^\s*([A-Za-zÀ-ÿ][\wÀ-ÿ.'-]*(?:\s[\wÀ-ÿ.'-]+){0,3}):\s+(\S.*)$")
NOMES_QUE_NAO_SAO_FALA = {"obs", "ps", "att", "nota", "assunto", "de", "para", "cc", "ref", "importante", "prazo", "valor",
                          "data", "competencia", "status", "subject", "from", "to", "sent", "date", "tel", "telefone",
                          "email", "e-mail", "cnpj", "endereco", "site", "lembrete", "atencao", "resumo", "detalhe",
                          "detalhes", "pedido", "demanda", "tarefa", "titulo", "checklist", "cliente novo", "obs.",
                          "enviado em", "enviada em", "responsavel", "lista", "tipo", "origem", "audio", "imagem", "video",
                          "arquivo", "documento", "transcricao", "mensagem", "anexo", "figurinha", "localizacao", "contato"}
# "Áudio: Oi, Ana…" / "🎤 Áudio: …" é a transcrição de um áudio; o rótulo não é fala
MARCA_MIDIA = re.compile(r"^\s*(?:[^\w\s]{1,3}\s*)?(?:[áa]udio|transcri[çc][ãa]o(?: do [áa]udio)?|imagem|v[íi]deo|documento|arquivo)\s*:\s*", re.I | re.M)
# Dados de nota a emitir, como o cliente manda no WhatsApp: "*Tomador:* X - CNPJ: … *Valor: R$ …* Descrição: …"
FICHA_TOMADOR = re.compile(r"\b(?:tomador|raz[aã]o social|empresa|prestador|para quem|cliente final)\s*:", re.I)
FICHA_CAMPO = re.compile(r"\b(tomador|raz[aã]o social|empresa|prestador|para quem|cliente final|cnpj|cpf|endere[çc]o|valor|cnae|"
                         r"descri[çc][ãa]o|discrimina[çc][ãa]o|servi[çc]o|compet[êe]ncia|vencimento|data|obs|observa[çc][ãa]o|"
                         r"e-?mail|telefone|im|inscri[çc][ãa]o municipal|reten[çc][ãa]o|iss|natureza)\s*:\s*", re.I)
CNPJ_SOLTO = re.compile(r"\d{2}[.\s]?\d{3}[.\s]?\d{3}\s?[/\-.]?\s?\d{4}\s?[-/.]?\s?\d{2}")
VALOR_BR = re.compile(r"(?:r\$|rs)?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
# O chat de um software de atendimento: a hora numa linha só depois de cada mensagem, o nome em MAIÚSCULA
# só antes das mensagens de quem atende; o cliente aparece sem nome.
HORA_SOZINHA = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$")
NOME_MAIUSCULO = re.compile(r"^\s*[A-ZÀ-Ý][A-ZÀ-Ý.'-]{1,}(?:\s+(?:D[AEO]S?\s+)?[A-ZÀ-Ý][A-ZÀ-Ý.'-]{1,}){1,4}\s*$")
# "Vocês conseguem verificar, por favor?", "pode ver pra mim?": eco do pedido, não pergunta para responder
PEDIDO_ECO = re.compile(r"^(?:(?:voces|vcs|vc|voce) )?(?:conseguem?|pode(?:m|ria|riam)?|da pra|tem como|teria como)(?: me| nos)?"
                        r"(?: (?:verificar|ver|olhar|checar|conferir|ajudar|fazer|dar uma olhada|providenciar|resolver|analisar|avaliar))?"
                        r"(?: (?:isso|isto|pra mim|pra gente|para mim|por favor|pf|pfv|por gentileza|a[ií]|nisso))*\s*\??$")
SISTEMA_WA = re.compile(r"(<m[ií]dia oculta>|<anexo:?[^>]*>|\(?arquivo anexado\)?|documento omitido|imagem ocultada|"
                        r"imagem omitida|v[ií]deo omitido|[áa]udio omitido|figurinha omitida|mensagem apagada|"
                        r"essa mensagem foi apagada|chamada de (?:voz|v[ií]deo)(?: perdida)?|liga[çc][ãa]o de voz(?: perdida)?)", re.I)
SEPARADOR_EMAIL = re.compile(r"^\s*(?:-{3,}\s*(?:mensagem original|original message|mensagem encaminhada|forwarded message)"
                             r"\s*-{3,}|_{6,}|-{8,})\s*$", re.I)
ESCREVEU = re.compile(r"^\s*(?:Em|On)\s+.{5,200}?\s+(?:escreveu|wrote):?\s*$", re.I)
CITADO = re.compile(r"^\s*>\s?")
ASSINATURA = re.compile(r"^\s*(atenciosamente|att\.?|atte\.?|abra[çc]os?|cordialmente|grat[oa]|obrigad[oa]|--+|__+)[\s,.!]*$", re.I)

# ---------------------------------------------------------------- lados
NOMES_EQUIPE = {"voce", "eu", "equipe", "escritorio", "contabilidade", "atendimento", "fiscal"}
NOMES_CLIENTE = {"cliente", "ela", "ele", "contato"}
# a voz de uma fala sem nome: quem escreve assim é o cliente…
VOZ_CLIENTE = re.compile(r"\b(voces|vcs|poderiam|poderia|podem|pode me|pode nos|me (?:manda|mandar|envia|enviar|mande|envie|passa|passar|"
                         r"encaminha|encaminhar)|nos (?:envie|mande|manda|envia|encaminhe)|gostaria|gostariamos|segue|seguem|em anexo|anexo|"
                         r"obrigad[oa]|por favor|por gentileza|bom dia|boa tarde|boa noite|tudo bem|conseguem|consegue me|preciso que|"
                         r"precisamos que|preciso d[oa]s?|precisamos d[oa]s?|aguardo|atenciosamente|att|grat[oa]|me ajud[ae]|nos ajud[ae]|"
                         r"vou precisar|estou precisando|estamos precisando|solicito|solicitamos|favor)\b")
# …e assim é você (ou alguém da equipe) anotando ou respondendo
VOZ_EQUIPE = re.compile(r"\b(vou|vamos|tenho que|temos que|tenho de|preciso (?:fazer|emitir|gerar|mandar|enviar|ver|conferir|puxar|tirar|"
                    r"retificar|apurar)|pediu|pede|pedindo|quer|solicitou|cobrou|cobrando|perguntou|mandou|enviou|ligou|falou|respondeu|"
                    r"me avisar|me lembrar|lembrar|atribuir|fica (?:pra|para|com)|ja (?:fiz|mandei|enviei|emiti)|feito|anotar|"
                    r"recorrente|todo dia|todo mes|todia|@\w+)\b")

# ---------------------------------------------------------------- o que está na frase
DOCUMENTO = re.compile(r"\b(notas? fiscais?|notas?|nfs?-?e|nfse|nfe|nf|guias?|das|darfs?|gps|boletos?|extratos?|balancetes?|dre|razao|"
                       r"balancos?|contratos? sociais?|contratos?|alteracao contratual|certidoes|certidao|cnds?|declaracoes|declaracao|"
                       r"relatorios?|planilhas?|comprovantes?|recibos?|folhas?|holerites?|xmls?|sped|livros?|cartas?|cartao cnpj|alvaras?|"
                       r"inscricao|procuracao|certificados?|cadastro|faturamento|apuracao|irpf|irpj|dirf|dctfweb|dctf|reinf|esocial|"
                       r"pgdas|defis|ecd|ecf|rais|caged|fgts|inss|iss|icms|gia|sintegra|simples|imposto de renda|informe|demonstrativos?|"
                       r"aliquota|parcelamento|protocolo|requerimento|cnpj|distrato|ata|fluxo de caixa|conciliacao|documentos?|arquivos?|"
                       r"pdf|danfe|carta de correcao|fatura|duplicata|orcamento|proposta|senha|acesso|codigo de acesso|login|"
                       r"procuracao eletronica|e-cac|ecac|ir|dirpf|dimob|dmed)\b")
MESES = {"janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "mar": 3, "abril": 4, "abr": 4, "maio": 5, "mai": 5,
         "junho": 6, "jun": 6, "julho": 7, "jul": 7, "agosto": 8, "ago": 8, "setembro": 9, "set": 9, "outubro": 10,
         "out": 10, "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12}
MES_NOME = r"(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)"
MES_PADRAO = re.compile(r"\b(?:(?:mes|competencia|comp\.?|ref\.?|referente a) (?:de )?)?" + MES_NOME + r"(?:[/ ]?(?:de )?(\d{4}|\d{2}))?\b")
MES_NUMERICO = re.compile(r"(?<![\d/])(\d{1,2})/(\d{4})(?![\d/])")
INTERVALO_MESES = re.compile(r"\bde " + MES_NOME + r"(?: de (\d{4}))? (?:a|ate|até) " + MES_NOME + r"(?:(?: de)? (\d{4}))?\b")
MAIUSCULAS = {"cnd": "CND", "dre": "DRE", "das": "DAS", "darf": "DARF", "iss": "ISS", "icms": "ICMS", "xml": "XML", "xmls": "XMLs",
              "nf": "NF", "nfe": "NF-e", "nfse": "NFS-e", "nfs-e": "NFS-e", "nf-e": "NF-e", "gps": "GPS", "fgts": "FGTS", "inss": "INSS",
              "cnpj": "CNPJ", "dctf": "DCTF", "dctfweb": "DCTFWeb", "pgdas": "PGDAS", "sped": "SPED", "irpf": "IRPF", "irpj": "IRPJ",
              "dirf": "DIRF", "ecd": "ECD", "ecf": "ECF", "rais": "RAIS", "gia": "GIA", "pdf": "PDF", "ir": "IR", "e-cac": "e-CAC",
              "cnds": "CNDs", "defis": "DEFIS", "reinf": "Reinf", "esocial": "eSocial", "dimob": "DIMOB", "dmed": "DMED"}
PERGUNTA = re.compile(r"^(qual|quais|quando|quanto|quantos|quantas|como|onde|por que|porque|pq|sera que|ja |tem como|teria como|"
                      r"da pra|sabe|sabem|voces sabem|vcs sabem|o que|oq|que dia|que valor|e verdade|e normal|posso|podemos|"
                      r"devo|devemos|precisa|precisamos|e preciso|e necessario|tem que|tenho que|temos que|existe|tem algum|tem alguma)\b")
# "gostaria de saber se…", "me confirma se…": pergunta sem interrogação
PERGUNTA_INDIRETA = re.compile(r"\b(?:gostaria de saber|gostariamos de saber|queria saber|quero saber|queremos saber|saber se|"
                               r"me (?:informa|informe|informar|confirma|confirme|confirmar|explica|explique|diz|diga)|"
                               r"(?:podem|pode|poderia|poderiam) (?:me |nos )?(?:informar|confirmar|dizer|explicar|verificar se)|"
                               r"tirar uma duvida|uma duvida|duvida:|fiquei com uma duvida|tenho uma duvida)\b\s*(?:se |sobre |qual |quando |como |o |a )?(.*)$")
CORTESIA_PERGUNTA = re.compile(r"\b(?:tudo bem|tudo bom|td bem|tudo certo|como vai|como esta|como vao|como vc esta|beleza|tranquilo|"
                               r"td certo|tudo joia|tudo otimo|td bom)\b")
# o cliente mandou alguma coisa
ENVIOU = re.compile(r"\b(segue|seguem|em anexo|anexo|anexei|anexamos|mandei|mandamos|enviei|enviamos|encaminhei|encaminhamos|ta ai|"
                    r"esta ai|aqui esta|aqui estao|conforme (?:solicitado|pedido|combinado)|ja (?:mandei|enviei|encaminhei))\b")
# o cliente prometeu mandar
CLIENTE_PROMETE = re.compile(r"\b(mando|envio|te mando|te envio|vou (?:mandar|enviar|passar|ver|providenciar|pedir)|assim que|"
                             r"ate (?:hoje|amanha|a tarde|o fim do dia|segunda|terca|quarta|quinta|sexta)|"
                             r"ja (?:vou|estou) (?:mandar|enviando|providenciando)|daqui a pouco|mais tarde|hoje a tarde|"
                             r"hoje ainda|ainda hoje)\b")
URGENCIA = re.compile(r"\b(urgente|urgencia|urgentissimo|pra ontem|para ontem|o quanto antes|o mais rapido possivel|"
                      r"com urgencia|hoje sem falta|precisa ser hoje|tem que ser hoje|correndo)\b")
# você pediu algo ao cliente
EQUIPE_PEDE = re.compile(r"\b(?:me (?:mandem|enviem|passem|encaminhem|manda|envia|mande|envie|passa|passe|encaminha|encaminhe)|"
                     r"(?:nos|pra gente|para a gente) (?:mandem|enviem|passem|encaminhem|manda|envia|mande|envie|passa|passe|encaminha)|"
                     r"pode(?:m|ria|riam)? (?:me |nos )?(?:mandar|enviar|passar|encaminhar)|"
                     r"consegue(?:m)? (?:me |nos )?(?:mandar|enviar|passar|encaminhar)|preciso (?:que (?:voce|vc|voces|vcs) (?:me |nos )?"
                     r"(?:mandem|enviem|passem|encaminhem|mande|envie|passe|encaminhe)|d[oa]s? )|vou precisar d[oa]s? |vamos precisar d[oa]s? |"
                     r"favor (?:enviar|mandar|encaminhar)|aguardo (?:o|a|os|as) |me (?:confirma|confirme|confirmar) |"
                     r"(?:envia|manda|enviem|mandem) (?:pra|para) (?:mim|a gente|nos)|preciso (?:receber|ter) )"
                     r"\s*(?:o |a |os |as |um |uma |esse |essa |aquele |aquela )?(.{3,90}?)"
                     r"(?=[.!?;]|,? ?(?:por favor|pf|pfv|por gentileza|que|pra|para|ate|até|assim que|quando|ok|ta|tá)\b|$)")
# você prometeu ou já fez
EQUIPE_PROMETE = re.compile(r"\b(vou|vamos|irei|iremos|te mando|te envio|mando|envio|faco|fazemos|providencio|providenciamos|ja vou|"
                        r"estou (?:fazendo|vendo|providenciando)|fico de|ficamos de|deixa comigo|pode deixar|vou ver|"
                        r"te retorno|retorno|te respondo|respondo|te aviso|aviso|te dou um retorno|dou um retorno|te falo|falo)\b")
EQUIPE_CONCLUIU = re.compile(r"\b(feito|pronto|enviado|enviada|enviei|mandei|encaminhei|segue|em anexo|resolvido|resolvi|emitido|emitida|"
                         r"ja (?:mandei|enviei|fiz|emiti|esta feito|foi|resolvi)|esta (?:anexo|enviado|feito|pronto))\b")
VERBO_DE_TAREFA = re.compile(r"\b(emitir|gerar|fazer|enviar|mandar|retificar|apurar|conferir|puxar|tirar|renovar|cancelar|corrigir|"
                             r"protocolar|ligar|responder|cobrar|verificar|baixar|separar|montar|calcular|transmitir|lancar|"
                             r"parcelar|pagar|agendar|atualizar|cadastrar|alterar|configurar|parametrizar|ajustar|instalar|"
                             r"integrar|implantar|habilitar|liberar|regularizar|consultar|analisar|solicitar|providenciar)\b")
# oração que é só narrativa ou cortesia: não vira título
NARRATIVA = re.compile(r"\b(comentou|falou|disse|mexeu|conseguiu|tentou|tudo bem|bom dia|boa tarde|boa noite|obrigad[oa]|"
                       r"entao|entao,|a[ií]|certinho|desculp[ae])\b")
ARTIGO_INICIO = re.compile(r"^(?:(?:a|o|as|os|da|do|das|dos|de|um|uma|uns|umas|tambem|e|mais|com|dessa|desse|deste|desta|"
                           r"esse|essa|este|esta|aquele|aquela|meu|minha|meus|minhas|nosso|nossa|seu|sua|todo|toda|todos|todas|"
                           r"as nossas|os nossos|minha|sobre|referente a|referente ao|ref|ref\.)\s+)+")
PROPOSITO = re.compile(r"\s+(?:pro|pra|para|porque|pq|pois|que|ate|até|no|na|nos|nas|em|com|sem|por|dia|hoje|amanha|urgente|"
                       r"o mais|assim|quando|antes|depois|ainda|tambem|se|caso|obrigad[oa])\b.*$")


# ---------------------------------------------------------------- dados
@dataclass
class Turno:
    nome: str = ""
    lado: str = ""                 # cliente | equipe | ""
    lado_motivo: str = ""
    quando: str = ""
    texto: str = ""                # o que foi dito, sem cortesia e sem marcas de sistema
    texto_bruto: str = ""          # como veio (para a descrição e para achar e-mail/CNPJ)
    email: str = ""
    anexo: bool = False
    assunto: str = ""


@dataclass
class Item:
    texto: str
    origem: str = "cliente"        # cliente | equipe | pergunta | anexo | catalogo
    feito: bool = False
    motivo: str = ""


@dataclass
class Tarefa:
    texto: str                     # a linha que o entendedor recebe (cliente + pedido + complementos)
    frases: list = field(default_factory=list)
    turno: int = -1
    itens: list = field(default_factory=list)      # [Item]
    entendimento: object = None
    titulo: str = ""
    deliveraveis: list = field(default_factory=list)   # itens que podem virar tarefas separadas


@dataclass
class Conversa:
    formato: str = "texto"         # whatsapp | email | conversa | texto
    turnos: list = field(default_factory=list)
    so_minha: bool = False         # só você falou: é a linha única, em várias linhas
    remetente_nome: str = ""
    remetente_email: str = ""
    remetente_telefone: str = ""
    cnpj: str = ""
    quando: str = ""
    assunto: str = ""
    cliente: object = None
    cliente_motivo: str = ""
    candidatos: list = field(default_factory=list)
    tarefas: list = field(default_factory=list)
    status_tipo: str = "aberto"    # aberto | aguardando | feito
    status_motivo: str = ""
    prazo: dt.date | None = None
    prazo_motivo: str = ""
    pessoa: str = ""
    pessoa_motivo: str = ""
    prioridade: str = ""           # "urgente" quando alguém disse; senão vazio (o app decide)
    prioridade_motivo: str = ""
    recorrencia: str = ""
    avisar: bool = False
    juntar: bool = False
    pode_juntar: bool = False
    pode_separar: bool = False
    avisos: list = field(default_factory=list)
    lados_automaticos: dict = field(default_factory=dict)   # nome → lado que o app decidiu

    @property
    def entendimentos(self) -> list:
        return [t.entendimento for t in self.tarefas]


# ---------------------------------------------------------------- 1. turnos
def _limpar_fala(texto: str) -> tuple:
    """(texto sem cortesia e marcas de sistema, tinha anexo?)."""
    texto = re.sub(r"[‎‏‪-‮﻿⁠​]", "", texto)      # marcas invisíveis do WhatsApp
    texto = re.sub(r"[*~]|^[\s•▪●\-]+(?=\S)", " ", texto, flags=re.M)              # *negrito*, ~riscado~, marcadores
    texto = MARCA_MIDIA.sub("", texto)                                    # "Áudio: …" é transcrição: fica só a fala
    anexo = bool(SISTEMA_WA.search(texto)) or bool(re.search(r"\.(pdf|xml|xlsx?|docx?|zip|rar|jpe?g|png|csv|txt)\b", texto, re.I))
    linhas = []
    for l in SISTEMA_WA.sub(" ", texto).splitlines():
        s = l.strip()
        if s and not CORTESIA.match(s):
            linhas.append(s)
    return "\n".join(linhas).strip(), anexo


def _nome_de_escreveu(linha: str) -> tuple:
    """"Em qua., 8 de out. de 2026 às 09:12, Maria Silva <maria@x.com> escreveu:" → (nome, e-mail)."""
    corpo = re.sub(r"\s*(?:escreveu|wrote):?\s*$", "", linha.strip(), flags=re.I)
    e = EMAIL_ENDERECO.search(corpo)
    email = e.group(0).lower() if e else ""
    corpo = re.sub(r"<[^>]*>|\([^)]*\)", "", corpo)
    corpo = corpo.replace(email, "")
    nome = corpo.rsplit(",", 1)[-1].strip(" \"'“”") if "," in corpo else ""
    if not nome or len(nome) > 60 or re.search(r"\d{4}", nome):
        nome = (email.split("@")[0] if email else "").replace(".", " ").title()
    return nome, email


def _turnos_whatsapp(linhas: list) -> list:
    turnos, atual, vazia_antes = [], None, False
    for l in linhas:
        m = WA_DATA_HORA.match(l) or WA_HORA_DATA.match(l)
        if m:
            g = m.groups()
            data, nome, texto = (g[0], g[2], g[3]) if WA_DATA_HORA.match(l) else (g[1], g[2], g[3])
            atual = Turno(nome=nome.strip(), quando=data, texto_bruto=texto)
            turnos.append(atual)
            vazia_antes = False
        elif not l.strip():
            vazia_antes = True
        elif atual is None or vazia_antes:
            # linha solta antes da primeira fala, ou depois de uma linha em branco: é a sua anotação
            atual = Turno(nome="", texto_bruto=l.strip())
            turnos.append(atual)
            vazia_antes = False
        else:
            atual.texto_bruto += "\n" + l.strip()
    return turnos


def _turnos_email(linhas: list) -> list:
    blocos = []

    def novo():
        b = Turno()
        b._cab = True          # ainda lendo cabeçalho
        b._corpo = []
        blocos.append(b)
        return b

    atual = novo()
    for l in linhas:
        if SEPARADOR_EMAIL.match(l):
            atual = novo()
            continue
        if ESCREVEU.match(l):
            atual = novo()
            atual.nome, atual.email = _nome_de_escreveu(l)
            atual._cab = False
            continue
        h = EMAIL_CABECALHO.match(l)
        if h:
            campo, valor = h.group(1).lower(), h.group(2).strip()
            if campo in ("de", "from", "remetente"):
                if not atual._cab or atual.nome or atual.email:
                    atual = novo()
                e = EMAIL_ENDERECO.search(valor)
                atual.email = e.group(0).lower() if e else ""
                atual.nome = re.sub(r"<.*?>|\(.*?\)|\"", "", valor).strip() or atual.nome
                atual._cab = True
                continue
            if atual._cab or not atual._corpo:
                if campo in ("assunto", "subject"):
                    atual.assunto = valor
                elif campo in ("enviado em", "enviada em", "sent", "data", "date"):
                    atual.quando = valor
                continue
        if CITADO.match(l):
            if atual._corpo and not getattr(atual, "_citado", False):
                atual = novo()
                atual._citado = True
                atual._cab = False
            l = CITADO.sub("", l)
        elif l.strip():
            atual._cab = False
        if l.strip() or atual._corpo:
            atual._corpo.append(l.rstrip())
    saida = []
    for b in blocos:
        corpo = "\n".join(b._corpo).strip()
        if not corpo and not b.nome and not b.email:
            continue
        b.texto_bruto = corpo
        # a assinatura fica fora do que é lido como pedido
        util = []
        for l in corpo.splitlines():
            if ASSINATURA.match(l) and util:
                break
            util.append(l)
        b._util = "\n".join(util)
        saida.append(b)
    if len(saida) >= 2:
        saida.reverse()          # e-mail responde por cima: o mais antigo está embaixo
    return saida


def _e_cabecalho_de_nome(linha: str, eu: str, equipe) -> bool:
    """`ANA SOUZA` numa linha só: o software de atendimento mostra assim quem atende."""
    s = linha.strip()
    if not s or len(s) > 60 or HORA_SOZINHA.match(s):
        return False
    chave = normalizar(s).lower()
    conhecidos = [normalizar(n).lower() for n in [eu, *equipe] if n]
    if any(_mesma_pessoa(chave, n) for n in conhecidos) and len(chave.split()) <= 4 and not VERBO_DE_TAREFA.search(chave):
        return True
    return bool(NOME_MAIUSCULO.match(s)) and not DOCUMENTO.search(chave) and not catalogo.achar_todos(chave)


def _turnos_chat(linhas: list, eu: str = "", equipe=()) -> list:
    """O chat de um software de atendimento: mensagem, linha com a hora, e o nome em maiúscula só de quem atende.

    Quem fala sem cabeçalho de nome é o cliente. A hora fecha a mensagem anterior.
    """
    turnos, atual, nome_pendente = [], None, ""
    for l in linhas:
        s = l.strip()
        if not s:
            continue
        if HORA_SOZINHA.match(s):
            if atual is not None:
                atual.quando = atual.quando or s
            atual = None
            continue
        if _e_cabecalho_de_nome(s, eu, equipe):
            nome_pendente = s.title() if s.isupper() else s
            atual = None
            continue
        if atual is None:
            atual = Turno(nome=nome_pendente, texto_bruto=s)
            if not nome_pendente:
                atual.lado, atual.lado_motivo = "cliente", "sem nome: no chat, quem atende é que aparece com nome"
            turnos.append(atual)
            nome_pendente = ""
        else:
            atual.texto_bruto += "\n" + s
    return turnos


def _turnos_transcricao(linhas: list) -> list | None:
    """`Cliente: …` / `Eu: …` / `Maria: …` — só vale se parecer mesmo uma conversa."""
    falas = []
    for l in linhas:
        m = NOME_FALA.match(l)
        nome = normalizar(m.group(1)).lower() if m else ""
        falas.append(m if m and nome not in NOMES_QUE_NAO_SAO_FALA and len(nome) <= 40 and not EMAIL_CABECALHO.match(l) else None)
    nomes = {normalizar(f.group(1)).lower() for f in falas if f}
    if sum(1 for f in falas if f) < 2 or len(nomes) > 4:
        return None
    if len(nomes) == 1 and not (nomes & (NOMES_EQUIPE | NOMES_CLIENTE)):
        return None
    turnos, atual = [], None
    for l, f in zip(linhas, falas):
        if f:
            atual = Turno(nome=f.group(1).strip(), texto_bruto=f.group(2))
            turnos.append(atual)
        elif l.strip():
            if atual is None:
                atual = Turno(nome="", texto_bruto=l.strip())
                turnos.append(atual)
            else:
                atual.texto_bruto += "\n" + l.strip()
    return turnos


def voz(texto: str, equipe=()) -> str:
    """Quem fala assim: 'cliente', 'equipe' ou '' quando não dá para saber."""
    norm = corrigir_digitacao(normalizar(texto).lower())
    c = len(VOZ_CLIENTE.findall(norm))
    w = len(VOZ_EQUIPE.findall(norm))
    # "pra ana", "@bruno": só quem é da equipe escreve assim
    primeiros = {normalizar(p).lower().split()[0] for p in equipe if p and normalizar(p).strip()}
    if primeiros and re.search(r"(?:\b(?:pra|para|p/|atribuir a|passar para|fica com)\s+(?:o |a )?|@)(" + "|".join(re.escape(p) for p in primeiros) + r")\b", norm):
        w += 2
    # linha curta só de ajustes ("até sexta, urgente", "me avisar dia 20") é anotação sua
    poucas = len(norm.split()) <= 6
    if poucas and not (DOCUMENTO.search(norm) or catalogo.achar_todos(norm) or PEDIDO.search(norm)):
        if URGENCIA.search(norm) or PEDE_AVISO.search(norm) or achar_data(norm, dt.date.today())[0]:
            w += 1
    if w > c:
        return "equipe"
    if c > w:
        return "cliente"
    return "cliente" if (c and PEDIDO.search(norm)) else ""


def _turnos_texto(linhas: list, equipe=()) -> list:
    """Texto solto: parágrafos; uma linha com voz diferente da anterior começa outra fala."""
    turnos, atual, voz_atual = [], None, ""
    for l in linhas:
        s = l.strip()
        if not s:
            atual = None
            continue
        v = voz(s, equipe)
        if atual is None or (v and voz_atual and v != voz_atual):
            atual = Turno(nome="", texto_bruto=s)
            turnos.append(atual)
            voz_atual = v
        else:
            atual.texto_bruto += "\n" + s
            voz_atual = voz_atual or v
    return turnos


def separar_turnos(texto: str, equipe=(), eu: str = "") -> tuple:
    """(formato, [Turno]) — descobre o formato e corta a conversa em falas."""
    linhas = [l.rstrip() for l in texto.strip().splitlines()]
    if any(WA_DATA_HORA.match(l) or WA_HORA_DATA.match(l) for l in linhas):
        formato, turnos = "whatsapp", _turnos_whatsapp(linhas)
    elif any(EMAIL_CABECALHO.match(l) for l in [x for x in linhas if x.strip()][:8]) \
            or any(ESCREVEU.match(l) or SEPARADOR_EMAIL.match(l) for l in linhas):
        formato, turnos = "email", _turnos_email(linhas)
    elif sum(1 for l in linhas if HORA_SOZINHA.match(l)) >= 2 or \
            (any(HORA_SOZINHA.match(l) for l in linhas) and any(_e_cabecalho_de_nome(l, eu, equipe) for l in linhas)):
        formato, turnos = "chat", _turnos_chat(linhas, eu, equipe)
    else:
        turnos = _turnos_transcricao(linhas)
        if turnos is not None:
            formato = "conversa"
        else:
            formato, turnos = "texto", _turnos_texto(linhas, equipe)
    for t in turnos:
        bruto = getattr(t, "_util", t.texto_bruto)
        t.texto, t.anexo = _limpar_fala(bruto)
        if not t.email:
            e = EMAIL_ENDERECO.search(t.texto_bruto)
            if e and formato != "email":
                t.email = e.group(0).lower()
    return formato, [t for t in turnos if t.texto or t.anexo or t.nome]


# ---------------------------------------------------------------- 2. lados
def _mesma_pessoa(a: str, b: str) -> bool:
    """'ana' é 'Ana Souza'; 'ana souza' não é 'ana dias'."""
    pa, pb = normalizar(a).lower().split(), normalizar(b).lower().split()
    if not pa or not pb:
        return False
    menor, maior = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return maior[:len(menor)] == menor


def decidir_lados(turnos: list, eu: str = "", equipe=(), aprendizado: dict | None = None,
                  lados: dict | None = None, contatos: dict | None = None) -> dict:
    """Dá lado a cada turno. Devolve {nome → lado} do que o app decidiu sozinho."""
    aprendidos = (aprendizado or {}).get("lados") or {}
    lados = {normalizar(k).lower(): v for k, v in (lados or {}).items() if v in ("cliente", "equipe")}
    contatos = contatos or {}
    automaticos = {}
    pendentes = []
    for i, t in enumerate(turnos):
        chave = normalizar(t.nome).lower()
        if f"#{i}" in lados:
            t.lado, t.lado_motivo = lados[f"#{i}"], "você marcou"      # fala sem nome, marcada pela posição
        elif t.lado:
            continue                                                   # o formato já decidiu (chat: sem nome = cliente)
        elif chave and chave in lados:
            t.lado, t.lado_motivo = lados[chave], "você marcou"
        elif t.email and email_da_equipe(t.email):
            t.lado, t.lado_motivo = "equipe", "e-mail da equipe"
        elif chave in NOMES_EQUIPE:
            t.lado, t.lado_motivo = "equipe", ""
        elif chave in NOMES_CLIENTE:
            t.lado, t.lado_motivo = "cliente", ""
        elif chave and chave in aprendidos:
            t.lado, t.lado_motivo = aprendidos[chave], "aprendido"
        elif chave and eu and _mesma_pessoa(chave, eu):
            t.lado, t.lado_motivo = "equipe", "é você"
        elif chave and any(_mesma_pessoa(chave, p) for p in equipe if p):
            t.lado, t.lado_motivo = "equipe", "da equipe"
        elif (t.email and t.email in contatos) or (len(_telefone_limpo(t.nome)) >= 10 and _telefone_limpo(t.nome) in contatos):
            t.lado, t.lado_motivo = "cliente", "contato conhecido"
        else:
            pendentes.append(t)
    # quem tem nome e ninguém conhece: pela voz de tudo que a pessoa disse; sem voz, é cliente
    por_nome = {}
    for t in pendentes:
        por_nome.setdefault(normalizar(t.nome).lower(), []).append(t)
    for chave, grupo in por_nome.items():
        if not chave:
            continue
        v = voz("\n".join(t.texto for t in grupo), equipe)
        lado = v or "cliente"
        for t in grupo:
            t.lado, t.lado_motivo = lado, ("pela voz" if v else "nome desconhecido")
        automaticos[grupo[0].nome] = lado
    # fala sem nome: pela voz; sem voz, herda a vizinha (antes de uma fala sua, é do cliente)
    for i, t in enumerate(turnos):
        if t.lado or t.nome:
            continue
        v = voz(t.texto, equipe)
        if v:
            t.lado, t.lado_motivo = v, "pela voz"
    for i, t in enumerate(turnos):
        if t.lado:
            continue
        depois = next((x.lado for x in turnos[i + 1:] if x.lado), "")
        antes = next((x.lado for x in reversed(turnos[:i]) if x.lado), "")
        if depois == "equipe" and not antes:
            t.lado = "cliente"
        elif antes:
            t.lado = antes
        elif depois:
            t.lado = depois
        t.lado_motivo = "pela posição" if t.lado else ""
    return automaticos


# ---------------------------------------------------------------- 3. frases → itens
def _bonito(item: str, original: str = "") -> str:
    """Item limpo, com os acentos do texto original de volta e as siglas em maiúscula."""
    item = re.sub(r"\s+", " ", item).strip(" ,.;:-")
    item = ARTIGO_INICIO.sub("", item)
    mapa = {}
    for w in re.findall(r"[\wÀ-ÿ-]+", original or ""):
        mapa.setdefault(normalizar(w).lower(), w)
    palavras = []
    for p in item.split():
        baixa = p.lower().strip("(),")
        if baixa in MAIUSCULAS:
            palavras.append(MAIUSCULAS[baixa])
        else:
            palavras.append(mapa.get(baixa, p))
    saida = " ".join(palavras)
    return saida[:1].upper() + saida[1:] if saida else ""


def _minuscula_inicial(texto: str) -> str:
    """'Carta de faturamento' → 'carta de faturamento'; 'CND federal' fica."""
    return texto[:1].lower() + texto[1:] if len(texto) > 1 and texto[1].islower() else texto


def _ano_do_mes(mes: int, ano: str | None, hoje: dt.date) -> int:
    if ano:
        a = int(ano)
        return a + 2000 if a < 100 else a
    return hoje.year if mes <= hoje.month else hoje.year - 1


def _meses(norm: str, hoje: dt.date) -> list:
    """[(mm/aaaa, trecho)] dos meses citados, na ordem; "de julho a setembro" vira três."""
    saida = []
    m = INTERVALO_MESES.search(norm)
    if m:
        m1, a1, m2, a2 = MESES[m.group(1)], m.group(2), MESES[m.group(3)], m.group(4)
        ano1 = _ano_do_mes(m1, a1 or a2, hoje) if (a1 or a2) else _ano_do_mes(m2, None, hoje)
        ano2 = _ano_do_mes(m2, a2 or a1, hoje) if (a1 or a2) else ano1
        if m1 > m2 and not (a1 or a2):
            ano1 -= 1
        atual = dt.date(ano1, m1, 1)
        fim = dt.date(ano2, m2, 1)
        while atual <= fim and len(saida) < 24:
            saida.append((f"{atual.month:02d}/{atual.year}", m.group(0)))
            atual = dt.date(atual.year + (atual.month == 12), atual.month % 12 + 1, 1)
        return saida
    for m in MES_PADRAO.finditer(norm):
        mes = MESES[m.group(1)]
        # "mar", "set", "out", "dez", "ago", "mai", "jun", "jul" soltos são palavras comuns: só com ano, ou precedidos de "de"/"mês de"
        if len(m.group(1)) == 3 and not m.group(2) and not re.search(r"\b(?:de|mes|competencia|ref\.?|referente a|comp\.?)\s*$", norm[:m.start()]):
            continue
        saida.append((f"{mes:02d}/{_ano_do_mes(mes, m.group(2), hoje)}", m.group(0)))
    for m in MES_NUMERICO.finditer(norm):
        if 1 <= int(m.group(1)) <= 12:
            saida.append((f"{int(m.group(1)):02d}/{m.group(2)}", m.group(0)))
    m = re.search(r"\b(?:meses?|competencias?) (?:de )?(\d{1,2})(?: e | a |, )(\d{1,2})(?:[/-](\d{2,4}))?\b", norm)
    if m and not saida and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 12:
        for g in (m.group(1), m.group(2)):
            saida.append((f"{int(g):02d}/{_ano_do_mes(int(g), m.group(3), hoje)}", m.group(0)))
    vistos, limpos = set(), []
    for comp, trecho in saida:
        if comp not in vistos:
            vistos.add(comp)
            limpos.append((comp, trecho))
    return limpos


def _e_documento(parte: str) -> bool:
    return bool(DOCUMENTO.search(parte) or catalogo.achar_todos(parte))


def itens_da_frase(frase: str, hoje: dt.date) -> list:
    """O checklist que está dentro da própria frase do cliente.

    "preciso do balancete, da DRE e do razão de agosto pro banco" → Balancete 08/2026, DRE 08/2026,
    Razão 08/2026. "balancete de julho a setembro" → um por mês. Uma coisa só → [].
    """
    norm = corrigir_digitacao(normalizar(frase).lower())
    norm = re.sub(r"[?!]+$", "", norm)
    achados = catalogo.achar_todos(norm)
    docs = [(m.start(), m.end()) for m in DOCUMENTO.finditer(norm)]
    inicios = [i for _c, _p, i in achados] + [i for i, _f in docs]
    if not inicios:
        return []
    fim_ultimo = max([i + len(p) for _c, p, i in achados] + [f for _i, f in docs])
    inicio = min(inicios)
    # o pedido em si vai do primeiro documento até o propósito ("pro banco", "até sexta")
    zona = norm[inicio:]
    corte = PROPOSITO.search(zona, max(0, fim_ultimo - inicio))
    if corte:
        zona = zona[:corte.start()]
    # "pode me mandar" no começo do primeiro item
    zona = re.sub(r"^(?:.*?\b(?:preciso|precisamos|gostaria|pode(?:m|ria|riam)?|consegue(?:m)?|me (?:manda|envia|mande|envie)|"
                  r"solicito|quero|queria|segue|favor|enviar|mandar|emitir|gerar|fazer|providenciar|tirar|puxar)\b\s*)"
                  r"(?:de |do |da |dos |das |o |a |os |as |me |nos |um |uma )*", "", zona, count=1)
    partes = [p.strip(" ,.;:") for p in re.split(r",|;| e | \+ | mais ", zona) if p.strip(" ,.;:")]
    partes = [ARTIGO_INICIO.sub("", p) for p in partes]
    partes = [p for p in partes if p]
    if not partes:
        return []
    meses_frase = _meses(norm, hoje)
    itens = []
    base_anterior = ""
    for p in partes:
        meses_p = _meses(p, hoje)
        so_mes = bool(meses_p) and not _e_documento(p) and len(re.sub(MES_NOME, "", p).split()) <= 2
        if so_mes and base_anterior:
            for comp, _t in meses_p:
                itens.append(f"{base_anterior} {comp}")
            continue
        if not _e_documento(p) or VERBO_DE_TAREFA.search(p) and not catalogo.achar_todos(p):
            continue
        base = p
        for _comp, trecho in meses_p:
            base = base.replace(trecho, " ")
        base = re.sub(r"\b(?:de|do|da|dos|das|mes|competencia|ref\.?|referente a)\s*$", "", re.sub(r"\s+", " ", base)).strip(" ,.-")
        base = re.sub(r"\b(?:de|do|da) (?:mes )?$", "", base).strip()
        if not base:
            continue
        base_anterior = base
        if meses_p:
            for comp, _t in meses_p:
                itens.append(f"{base} {comp}")
        else:
            itens.append(base)
    # "balancete, DRE e razão de agosto" / "livros de julho a setembro": o período dito uma vez
    # (no fim) vale para todo item que ficou sem mês
    trechos = {t for _c, t in meses_frase}
    if meses_frase and len(trechos) == 1 and itens and any(not re.search(r"\d{2}/\d{4}", i) for i in itens):
        comps = [c for c, _t in meses_frase]
        expandidos = []
        for i in itens:
            if re.search(r"\d{2}/\d{4}", i):
                expandidos.append(i)
            else:
                expandidos.extend(f"{i} {c}" for c in comps)
        itens = expandidos
    if len(itens) < 2:
        return []
    vistos, saida = set(), []
    for i in itens:
        b = _bonito(i, frase)
        if b and b.lower() not in vistos:
            vistos.add(b.lower())
            saida.append(b)
    return saida


def _frases(texto: str) -> list:
    """Frases de uma fala, uma por item de lista ou por pontuação. Mantém o '?'."""
    saida = []
    for l in texto.splitlines():
        l = l.strip()
        if not l:
            continue
        m = ITEM.match(l)
        if m:
            saida.append(("item", m.group(1).strip()))
            continue
        for f in re.split(r"(?<=[.!?;])\s+(?=\S)", l):
            f = f.strip()
            if len(f) >= 3:
                saida.append(("frase", f))
    return saida


# ---------------------------------------------------------------- 4. a conversa inteira
def _objeto_pedido(texto_equipe: str) -> list:
    """O que você pediu ao cliente, numa fala sua: ["contrato social atualizado", …]."""
    norm = corrigir_digitacao(normalizar(texto_equipe).lower())
    saida = []
    for m in EQUIPE_PEDE.finditer(norm):
        alvo = m.group(1).strip(" ,.;:?!")
        alvo = re.sub(r"\b(?:por favor|pf|pfv|por gentileza|pra mim|para mim|pra gente|obrigad[oa]|ok|ta|tá)\b.*$", "", alvo).strip(" ,.;:")
        alvo = ARTIGO_INICIO.sub("", alvo)
        if 2 <= len(alvo) <= 90 and alvo not in ("que", "isso", "ai", "aqui"):
            saida.append(alvo)
    return saida


def achar_fichas_de_nota(texto: str) -> list:
    """Os dados de nota que o cliente manda prontos, um bloco por nota:
    "Tomador: COMERCIO MODELO - CNPJ: 12.345.678/0001-90 Endereço: … Valor: R$ 1.074,89 Descrição: consultoria"
    → [{tomador, cnpj, valor, descricao, cnae}]. Sem "Tomador:" (ou "Razão social:") não é ficha."""
    inicios = [m.start() for m in FICHA_TOMADOR.finditer(texto)]
    if not inicios:
        return []
    fichas = []
    for i, ini in enumerate(inicios):
        bloco = texto[ini:inicios[i + 1] if i + 1 < len(inicios) else len(texto)]
        partes = FICHA_CAMPO.split(bloco)
        campos = {}
        for nome, valor in zip(partes[1::2], partes[2::2]):
            campos.setdefault(normalizar(nome).lower(), valor.strip(" -–:.,;\n"))
        tomador = next((campos[k] for k in ("tomador", "razao social", "empresa", "prestador", "para quem", "cliente final") if campos.get(k)), "")
        tomador = re.sub(r"\s*[-–]\s*$", "", tomador.split("\n")[0]).strip(" .,")
        cnpj = CNPJ_SOLTO.search(campos.get("cnpj", "") or bloco)
        valor = VALOR_BR.search(campos.get("valor", ""))
        descricao = next((campos[k] for k in ("descricao", "discriminacao", "servico", "natureza") if campos.get(k)), "")
        if not tomador and not valor:
            continue
        fichas.append({"tomador": tomador[:80], "cnpj": re.sub(r"\D", "", cnpj.group(0)) if cnpj else "",
                       "valor": valor.group(1) if valor else "", "descricao": descricao.split("\n")[0].strip(" .")[:120],
                       "cnae": campos.get("cnae", "").split("\n")[0][:80], "competencia": campos.get("competencia", "")[:10]})
    return fichas


def _item_da_ficha(f: dict) -> str:
    nome = " ".join(f["tomador"].split()[:4]) or (f["cnpj"] and f"CNPJ {f['cnpj']}") or "tomador sem nome"
    partes = [f"NF para {nome}"]
    if f["valor"]:
        partes.append(f"R$ {f['valor']}")
    if f["descricao"]:
        partes.append(f["descricao"][:70])
    return " · ".join(partes)


def _recortar_pedido(frase: str) -> str:
    """De uma frase longa e falada (áudio transcrito), a oração que é o pedido.

    "Então, ele comentou que o sistema de cobrança não tava configurado, pediu pra gente configurar, a Carla mexeu
    no que conseguiu, e aí vocês ficaram de parametrizar pra gente conseguir emitir as notas fiscais"
    → "vocês ficaram de parametrizar pra gente conseguir emitir as notas fiscais". Frase curta volta inteira.
    """
    if len(frase.split()) <= 14:
        return frase
    oracoes = [o.strip() for o in re.split(r",\s+|;\s+|\s+e a[ií]\s+|\s+ent[ãa]o\s+|\s+mas\s+|\s+por[ée]m\s+", frase) if o.strip()]
    if len(oracoes) < 2:
        return frase
    melhor, melhor_pontos = None, -99
    for i, o in enumerate(oracoes):
        n = corrigir_digitacao(normalizar(o).lower())
        pontos = 0
        pontos += 3 * len(catalogo.achar_todos(n))
        pontos += 2 if DOCUMENTO.search(n) else 0
        pontos += 2 if VERBO_DE_TAREFA.search(n) else 0
        pontos += 1 if re.search(r"\b(voces|vcs|preciso|precisamos|gostaria|pra gente|para a gente|ficaram de|ficou de)\b", n) else 0
        pontos -= 2 if NARRATIVA.search(n) and not VERBO_DE_TAREFA.search(n) else 0
        pontos -= 1 if len(n.split()) <= 2 else 0
        if pontos > melhor_pontos:
            melhor, melhor_pontos = i, pontos
    if melhor is None or melhor_pontos <= 0:
        return frase
    escolhida = oracoes[melhor]
    # "…ficaram de parametrizar" + "pra gente conseguir emitir as notas": a oração seguinte completa o verbo
    if melhor + 1 < len(oracoes) and re.match(r"^(?:pra|para|a fim de|de forma|que)\b", normalizar(oracoes[melhor + 1]).lower()) \
            and len(escolhida.split()) + len(oracoes[melhor + 1].split()) <= 24:
        escolhida += ", " + oracoes[melhor + 1]
    return escolhida


def _texto_para_entender(cliente_codigo: str, frases: list, complementos: list) -> str:
    limpas = [re.sub(r"[?!.]+$", "", f.strip()).strip() for f in frases]
    if len(limpas) > 1 and all(len(f.split()) <= 6 for f in limpas):
        base = " e ".join(limpas)          # "CND federal e CND estadual"
    else:
        base = ". ".join(limpas)
    if complementos:
        base += ", " + ", ".join(c.strip(" .,") for c in complementos)
    if cliente_codigo and not re.search(r"\b" + re.escape(cliente_codigo) + r"\b", normalizar(base)):
        base = f"{cliente_codigo} {base}"
    return base


def _cliente_confiavel(norm: str, cliente, trecho: str, motivo: str, indice: Indice) -> bool:
    """Numa conversa, uma palavra solta não identifica cliente: "de forma automática" não é a FORMA & CIA,
    "tudo bem ?" não é ninguém. Vale: código explícito, apelido ensinado, nome com duas palavras, ou uma
    palavra depois de "do/da/cliente/@" (como você escreve: "do 101", "da padaria")."""
    if cliente is None:
        return False
    if motivo.startswith("código"):
        return True
    t = normalizar(trecho).lower().strip()
    if not t or not re.fullmatch(r"[a-z0-9][a-z0-9 .&-]*", t):
        return False
    if t in indice.apelidos:
        return True
    palavras = t.split()
    if len(palavras) >= 2:
        return True
    # "de forma automática" e "para a auditoria" não apontam cliente; "do 101", "da padaria", "cliente horizonte" apontam
    return bool(re.search(r"(?:\b(?:do|da|pro|pra|cliente|cli)\s+|@)" + re.escape(t) + r"\b", norm))


def _achar_cliente_da_conversa(conv: Conversa, turnos: list, indice: Indice, aprendizado: dict | None) -> None:
    contatos = contatos_conhecidos(aprendizado, indice)
    do_cliente = [t for t in turnos if t.lado == "cliente"]
    nomes = {}
    for t in do_cliente:
        if t.nome and normalizar(t.nome).lower() not in NOMES_CLIENTE:
            nomes[t.nome] = nomes.get(t.nome, 0) + 1
        conv.remetente_email = conv.remetente_email or t.email
        if not conv.cnpj and not FICHA_TOMADOR.search(t.texto):
            # CNPJ numa ficha de nota é do tomador, não de quem escreve
            c = CNPJ.search(t.texto_bruto)
            if c:
                conv.cnpj = re.sub(r"\D", "", c.group(0))
    if nomes:
        conv.remetente_nome = max(nomes, key=nomes.get)
        tel = _telefone_limpo(conv.remetente_nome)
        if len(tel) >= 10:
            conv.remetente_telefone = tel
    if conv.remetente_email and conv.remetente_email in contatos:
        conv.cliente, conv.cliente_motivo = indice.achar(contatos[conv.remetente_email]), f"pelo e-mail {conv.remetente_email}"
    elif conv.remetente_telefone and conv.remetente_telefone in contatos:
        conv.cliente, conv.cliente_motivo = indice.achar(contatos[conv.remetente_telefone]), "pelo telefone"
    elif conv.cnpj and conv.cnpj in contatos:
        conv.cliente, conv.cliente_motivo = indice.achar(contatos[conv.cnpj]), "pelo CNPJ"
    elif conv.remetente_nome and normalizar(conv.remetente_nome).lower() in contatos:
        conv.cliente, conv.cliente_motivo = indice.achar(contatos[normalizar(conv.remetente_nome).lower()]), f"“{conv.remetente_nome}” já ensinado"
    if conv.cliente is None and conv.remetente_email and "@" in conv.remetente_email:
        dominio = conv.remetente_email.split("@", 1)[1].split(".")[0]
        if dominio not in ("gmail", "hotmail", "outlook", "yahoo", "uol", "bol", "terra", "icloud", "live", "msn"):
            achados = indice.por_nome(dominio, minimo=80)
            if achados:
                conv.cliente, conv.cliente_motivo = achados[0][0], f"pelo domínio do e-mail ({dominio})"
                conv.candidatos = [c for c, p in achados[1:4] if achados[0][1] - p <= 8]
    if conv.cliente is None:
        # "do 101", "da padaria" em qualquer fala sua, ou "aqui é da Padaria Central" na do cliente
        for t in turnos:
            if t.lado != "equipe" and not re.search(r"\baqui (e|é) d[ao]\b", normalizar(t.texto).lower()):
                continue
            norm_t = corrigir_digitacao(normalizar(t.texto).lower())
            c, cands, trecho, motivo = achar_cliente(norm_t, indice)
            if _cliente_confiavel(norm_t, c, trecho, motivo, indice):
                conv.cliente, conv.cliente_motivo, conv.candidatos = c, motivo or "citado na conversa", cands
                break
    if conv.cliente is None and conv.remetente_nome and not conv.remetente_telefone:
        achados = indice.por_nome(conv.remetente_nome, minimo=70)
        if achados and len(normalizar(conv.remetente_nome).split()) >= 2:
            conv.cliente, conv.cliente_motivo = achados[0][0], f"pelo nome “{conv.remetente_nome}”"
            conv.candidatos = [c for c, p in achados[1:4] if achados[0][1] - p <= 10]
        elif achados:
            # "Daniel" sozinho não identifica empresa: vira sugestão, e a escolha ensina o nome
            conv.candidatos = [c for c, _p in achados[:4]]
            conv.cliente_motivo = f"“{conv.remetente_nome}” pode ser um destes"


def interpretar(texto: str, indice: Indice, pessoas=(), hoje: dt.date | None = None, aprendizado: dict | None = None,
                eu: str = "", equipe=(), lados: dict | None = None, juntar: bool | None = None) -> Conversa:
    """A conversa colada → quem é, o que pediu, o que você combinou, e as tarefas com checklist."""
    hoje = hoje or dt.date.today()
    aprendizado = aprendizado or {}
    conv = Conversa()
    conv.formato, turnos = separar_turnos(texto, equipe, eu)
    conv.turnos = turnos
    if not turnos:
        return conv
    conv.lados_automaticos = decidir_lados(turnos, eu=eu, equipe=equipe, aprendizado=aprendizado, lados=lados,
                                           contatos=contatos_conhecidos(aprendizado, indice))
    conv.quando = next((t.quando for t in turnos if t.quando), "")
    conv.assunto = next((t.assunto for t in turnos if t.assunto), "")
    conv.so_minha = all(t.lado == "equipe" for t in turnos)
    _achar_cliente_da_conversa(conv, turnos, indice, aprendizado)
    codigo = conv.cliente.codigo if conv.cliente else ""

    if conv.so_minha:
        _tarefas_das_minhas_linhas(conv, turnos, indice, pessoas, hoje, aprendizado)
        return conv

    # --- as falas do cliente viram pedidos; as suas, combinados
    tarefas: list = []
    perguntas_soltas: list = []
    complementos_soltos: list = []
    pediu_ao_cliente: list = []      # (índice do turno, item)
    cliente_enviou_em: list = []     # índices de turno
    cliente_prometeu_em: list = []
    equipe_concluiu_em: list = []
    houve_equipe_antes = False
    texto_equipe = []
    def nova_tarefa(f, idx, tipos, origem, motivo, item_de_lista=False):
        ta = Tarefa(texto="", frases=[f], turno=idx)
        ta.frases_tipos = [tp for tp, _p, _i in tipos]
        ta.de_lista = item_de_lista
        ta.complementos = []
        ta.itens = [Item(x, origem=origem, motivo=motivo) for x in itens_da_frase(f, hoje)]
        if item_de_lista and not ta.itens:
            # "1. CND federal" guarda o próprio item: se o próximo for do mesmo tipo, os dois viram checklist
            ta.proprio = Item(_bonito(re.sub(r"[?!.]+$", "", f), f), origem=origem, motivo=motivo)
        tarefas.append(ta)
        return ta

    def frase_sem_pergunta(f):
        s = f.strip().rstrip("?!. ").strip()
        return s[:1].upper() + s[1:]

    # dados de nota prontos ("Tomador: … Valor: … Descrição: …"): uma tarefa "Emitir N notas", um item por nota;
    # as falas que só pedem a emissão ("consegue fazer essas duas emissões?") pertencem a ela
    fichas_por_turno = {idx: achar_fichas_de_nota(t.texto) for idx, t in enumerate(turnos) if t.lado == "cliente"}
    fichas_por_turno = {k: v for k, v in fichas_por_turno.items() if v}
    tarefa_notas = None
    if fichas_por_turno:
        todas = [f for fs in fichas_por_turno.values() for f in fs]
        n = len(todas)
        nomes = ", ".join(" ".join(f["tomador"].split()[:3]) for f in todas if f["tomador"])
        tarefa_notas = Tarefa(texto="", frases=["emitir nota fiscal"], turno=min(fichas_por_turno))   # a linha dá o tipo; o título é fixo
        tarefa_notas.frases_tipos = ["nota_fiscal"]
        tarefa_notas.de_lista, tarefa_notas.complementos = False, []
        tarefa_notas.titulo_fixo = (f"Emitir {n} nota{'s' if n > 1 else ''} fisca{'is' if n > 1 else 'l'}" + (f": {nomes}" if nomes else ""))[:140]
        tarefa_notas.itens = [Item(_item_da_ficha(f), origem="cliente", motivo="dados da nota na mensagem") for f in todas]
        tarefa_notas.itens.append(Item("Enviar o PDF e o XML ao cliente", origem="catalogo"))
        try:
            tarefa_notas.valor_total = round(sum(float(f["valor"].replace(".", "").replace(",", ".")) for f in todas if f["valor"]), 2)
        except ValueError:
            tarefa_notas.valor_total = 0.0
        tarefas.append(tarefa_notas)

    for idx, t in enumerate(turnos):
        norm_t = corrigir_digitacao(normalizar(t.texto).lower())
        if idx in fichas_por_turno:
            continue
        if t.lado == "equipe":
            houve_equipe_antes = True
            texto_equipe.append(norm_t)
            for _k, f in _frases(t.texto):
                nf = corrigir_digitacao(normalizar(f).lower())
                for alvo in _objeto_pedido(f):
                    pediu_ao_cliente.append((idx, Item(f"Receber do cliente: {_minuscula_inicial(_bonito(alvo, f))}", origem="equipe",
                                                       motivo=f"você pediu: “{f[:80]}”")))
                tipos = catalogo.achar_todos(nf)
                # uma fala sua que descreve uma tarefa ("tenho que emitir a nota também") entra como pedido
                if tipos and VERBO_DE_TAREFA.search(nf) and not EQUIPE_PROMETE.search(nf) and not EQUIPE_PEDE.search(nf) \
                        and not any(tp == t2 for tp, _p, _i in tipos for tt in tarefas for t2 in tt.frases_tipos):
                    nova_tarefa(f, idx, tipos, "equipe", f"da sua fala: “{f[:80]}”")
            if EQUIPE_CONCLUIU.search(norm_t) and not EQUIPE_PEDE.search(norm_t):
                equipe_concluiu_em.append(idx)
            continue
        if t.lado != "cliente":
            continue
        e_anexo = t.anexo and (not t.texto or len(t.texto.split()) <= 6)
        if e_anexo:
            nome_arq = t.texto.strip()
            destino = tarefas[-1] if tarefas else None
            if (idx - 1) in cliente_enviou_em and destino is not None and destino.itens and destino.itens[-1].origem == "anexo":
                # "segue o extrato em anexo" + o arquivo logo abaixo: é o mesmo anexo
                if nome_arq and nome_arq not in destino.itens[-1].texto:
                    destino.itens[-1].texto += f": {nome_arq}"
            else:
                item = Item("Conferir o anexo" + (f": {nome_arq}" if nome_arq else " que o cliente mandou"), origem="anexo",
                            motivo="arquivo anexado na conversa")
                if destino is not None:
                    destino.itens.append(item)
                else:
                    complementos_soltos.append(item)
            cliente_enviou_em.append(idx)
            continue
        frases = _frases(t.texto)
        tem_lista = sum(1 for k, _f in frases if k == "item") >= 2
        ultima_do_turno = None
        for tipo_frase, f in frases:
            nf = corrigir_digitacao(normalizar(f).lower())
            tipos = catalogo.achar_todos(nf)
            tem_doc = bool(DOCUMENTO.search(nf))
            e_pergunta = f.rstrip().endswith("?")
            tem_pedido = bool(PEDIDO.search(nf)) or any(re.search(r"\b" + re.escape(v) + r"\b", nf) for v in VERBOS_PEDIDO)
            data, trecho_data, _m = achar_data(nf, hoje)
            urgente = bool(URGENCIA.search(nf))
            enviou = bool(ENVIOU.search(nf)) and not tem_pedido
            if e_pergunta and CORTESIA_PERGUNTA.search(nf) and len(nf.split()) <= 9 and not (tipos or tem_doc):
                continue                       # "Fala Ana, bom dia, tudo bem?" não é pergunta para responder
            if PEDIDO_ECO.match(re.sub(r"\s+", " ", re.sub(r"[,;]", " ", nf)).strip(" ?!.")):
                continue                       # "vocês conseguem verificar, por favor?" repete o pedido de cima
            if tarefa_notas is not None and re.search(r"\b(emiss(?:ao|oes)|emitir|emita|emite|notas?|nfs?-?e|nfse)\b", nf) \
                    and not [tp for tp, _p, _i in tipos if tp != "nota_fiscal"]:
                # "consegue fazer essas duas emissões?" é o pedido das fichas de nota, não outra tarefa
                if data:
                    tarefa_notas.complementos.append(trecho_data)
                continue
            if enviou:
                cliente_enviou_em.append(idx)
                if tem_doc or tipos:
                    alvo = itens_da_frase(f, hoje) or [_bonito(DOCUMENTO.search(nf).group(0) if DOCUMENTO.search(nf) else tipos[0][1], f)]
                    destino = ultima_do_turno or (tarefas[-1] if tarefas else None)
                    for a in alvo:
                        item = Item(f"Conferir {_minuscula_inicial(a)} (enviado pelo cliente)", origem="anexo", motivo=f"o cliente disse: “{f[:80]}”")
                        if destino is not None:
                            destino.itens.append(item)
                        else:
                            complementos_soltos.append(item)
                continue
            if CLIENTE_PROMETE.search(nf) and houve_equipe_antes and not tipos and not tem_pedido:
                cliente_prometeu_em.append(idx)
                continue
            indireta = PERGUNTA_INDIRETA.search(nf)
            if indireta or (e_pergunta and (not (tipos or tem_doc) or PERGUNTA.match(nf)) and not (tem_pedido and (tipos or tem_doc))):
                if indireta:
                    resto = f[len(f) - len(indireta.group(1)):].strip() if indireta.group(1) else f
                    texto_item = "Responder: " + (resto[:1].lower() + resto[1:]).rstrip(".?! ")
                else:
                    texto_item = "Responder: " + frase_sem_pergunta(f) + "?"
                item = Item(texto_item, origem="pergunta", motivo=f"pergunta do cliente: “{f[:80]}”")
                if ultima_do_turno is not None:
                    ultima_do_turno.itens.append(item)
                else:
                    perguntas_soltas.append(item)
                continue
            if tem_lista and tipo_frase != "item":
                # "Ana, preciso de:" / "até sexta por favor" em volta de uma lista numerada
                if data or urgente:
                    complementos_soltos.append(Item(trecho_data or "urgente", origem="complemento"))
                continue
            if tipos or tem_doc or tipo_frase == "item":
                motivo = f"o cliente disse: “{f[:80]}”"
                tipos_f = {tp for tp, _p, _i in tipos}
                mesmo_tipo = ultima_do_turno is not None and tipos_f and ultima_do_turno.frases_tipos and \
                    tipos_f <= set(ultima_do_turno.frases_tipos) and (tipo_frase != "item" or getattr(ultima_do_turno, "de_lista", False))
                if mesmo_tipo:
                    ultima_do_turno.frases.append(f)
                    if tipo_frase == "item":
                        proprio = getattr(ultima_do_turno, "proprio", None)
                        if proprio is not None:
                            ultima_do_turno.itens.insert(0, proprio)
                            ultima_do_turno.proprio = None
                        ultima_do_turno.itens.append(Item(_bonito(re.sub(r"[?!.]+$", "", f), f), origem="cliente", motivo=motivo))
                    else:
                        ultima_do_turno.itens.extend(Item(x, origem="cliente", motivo=motivo) for x in itens_da_frase(f, hoje))
                else:
                    ultima_do_turno = nova_tarefa(re.sub(r"\?+$", "", f.strip()), idx, tipos, "cliente", motivo, item_de_lista=(tipo_frase == "item"))
                for item in perguntas_soltas:
                    ultima_do_turno.itens.append(item)
                for c in complementos_soltos:
                    if c.origem == "complemento":
                        ultima_do_turno.complementos.append(c.texto)
                    else:
                        ultima_do_turno.itens.append(c)
                perguntas_soltas, complementos_soltos = [], []
                continue
            if (data or urgente) and len(nf.split()) <= 12:
                # "preciso até sexta", "é urgente": complementa o pedido, não é pedido novo
                alvo = ultima_do_turno or (tarefas[-1] if tarefas else None)
                pedaco = trecho_data or "urgente"
                if alvo is not None:
                    alvo.complementos.append(pedaco)
                else:
                    complementos_soltos.append(Item(pedaco, origem="complemento"))
                continue
            if tem_pedido and len(nf.split()) >= 3 and not houve_equipe_antes and not f.rstrip().endswith(":"):
                ultima_do_turno = nova_tarefa(re.sub(r"\?+$", "", f.strip()), idx, [], "cliente", f"o cliente disse: “{f[:80]}”")
                continue
            # o resto é conversa ("ok", "obrigado", "tudo bem?")
    # nada que pareça pedido: a primeira fala do cliente inteira é o pedido
    if not tarefas:
        primeira = next((t for t in turnos if t.lado == "cliente" and t.texto and not t.anexo), None)
        if primeira is not None:
            nova_tarefa(primeira.texto.replace("\n", ". ")[:200], turnos.index(primeira), [], "cliente", "única fala do cliente")
    if tarefas:
        for item in perguntas_soltas:
            tarefas[-1].itens.append(item)
        for c in complementos_soltos:
            if c.origem == "complemento":
                for ta in tarefas:
                    if c.texto not in ta.complementos:
                        ta.complementos.append(c.texto)
            else:
                tarefas[0].itens.append(c)
        # "1. CND federal" sozinho: o item próprio não vira checklist de um item só
        for ta in tarefas:
            ta.proprio = None

    # --- o que você registrou vale para todas
    norm_equipe = "\n".join(texto_equipe)
    if norm_equipe:
        conv.pessoa, trecho = achar_pessoa(norm_equipe, pessoas)
        if conv.pessoa:
            conv.pessoa_motivo = f"você escreveu “{trecho}”"
        conv.recorrencia, _tr = achar_recorrencia(norm_equipe)
        conv.avisar = bool(PEDE_AVISO.search(norm_equipe))
        # a data que vale é a da sua última promessa ("te retorno amanhã"); sem promessa, a primeira data escrita
        datas_equipe = []
        for linha in norm_equipe.splitlines():
            for f in re.split(r"(?<=[.!?;])\s+|,\s+(?=\w+ (?:verific|retorn|mand|envi|faz|fa[çc]o|respond|avis))", linha):
                data, trecho_d, motivo = achar_data(f, hoje)
                if data:
                    datas_equipe.append((bool(EQUIPE_PROMETE.search(f)), data, f.strip(" ,"), trecho_d))
        promessas = [d for d in datas_equipe if d[0]]
        if promessas:
            _p, data, f, _t = promessas[-1]
            conv.prazo, conv.prazo_motivo = data, "você combinou com o cliente: “" + f[:60] + "”"
        elif datas_equipe:
            _p, data, _f, trecho_d = datas_equipe[0]
            conv.prazo, conv.prazo_motivo = data, f"você escreveu “{trecho_d}”"
    if URGENCIA.search(norm_equipe):
        conv.prioridade, conv.prioridade_motivo = "urgente", "você marcou como urgente"
    elif any(URGENCIA.search(normalizar(t.texto).lower()) for t in turnos if t.lado == "cliente"):
        conv.prioridade, conv.prioridade_motivo = "urgente", "o cliente pediu com urgência"

    # --- status pela ordem das falas
    ultimo_pedido = max((i for i, _it in pediu_ao_cliente), default=-1)
    enviou_depois = any(i > ultimo_pedido for i in cliente_enviou_em) if ultimo_pedido >= 0 else False
    if ultimo_pedido >= 0 and not enviou_depois:
        conv.status_tipo = "aguardando"
        conv.status_motivo = pediu_ao_cliente[-1][1].motivo
        if any(i > ultimo_pedido for i in cliente_prometeu_em):
            conv.status_motivo += " — o cliente disse que manda"
    elif ultimo_pedido >= 0 and enviou_depois:
        conv.status_tipo, conv.status_motivo = "aberto", "você pediu e o cliente já mandou"
        for _i, it in pediu_ao_cliente:
            it.feito = True
    elif equipe_concluiu_em and equipe_concluiu_em[-1] == len(turnos) - 1 and not cliente_enviou_em[-1:] == [len(turnos) - 1]:
        conv.status_tipo, conv.status_motivo = "feito", f"você fechou a conversa: “{turnos[-1].texto[:60]}”"
    for _i, it in pediu_ao_cliente:
        (tarefas[0] if tarefas else Tarefa(texto="")).itens.append(it)

    # --- cada tarefa passa pelo entendedor (título, tipo, prazo padrão, prioridade)
    for ta in tarefas:
        ta.texto = _texto_para_entender(codigo, [_recortar_pedido(f) for f in ta.frases], getattr(ta, "complementos", []))
        fala_do_cliente = 0 <= ta.turno < len(turnos) and turnos[ta.turno].lado == "cliente"
        e = entender(ta.texto, indice, pessoas=pessoas, hoje=hoje, aprendizado=aprendizado, cliente_por_nome=not fala_do_cliente)
        # a fala do cliente não serve para adivinhar o cliente por uma palavra solta ("de forma automática"
        # não é a FORMA & CIA; "a Carla" não é cliente). Só código explícito, apelido ensinado ou nome composto.
        if e.cliente is not None and not _cliente_confiavel(e.normalizado, e.cliente, e.cliente_trecho, e.cliente_motivo, indice):
            e.cliente, e.candidatos_cliente, e.cliente_motivo = None, [], ""
        if conv.cliente and e.cliente is None:
            e.cliente, e.cliente_motivo = conv.cliente, conv.cliente_motivo
        elif e.cliente is not None and conv.cliente is None and len(tarefas) == 1:
            conv.cliente, conv.cliente_motivo = e.cliente, e.cliente_motivo
        e.pessoa = conv.pessoa or ""        # nome dentro da fala do cliente não é da equipe
        if conv.prazo:
            e.prazo, e.prazo_motivo = conv.prazo, conv.prazo_motivo
        elif e.prazo is None or e.prazo_motivo.startswith("padrão"):
            # prazo dito pelo cliente em outra frase ("preciso até sexta" dois turnos depois)
            for t in turnos:
                if t.lado == "cliente":
                    d, td, _m = achar_data(corrigir_digitacao(normalizar(t.texto).lower()), hoje)
                    if d:
                        e.prazo, e.prazo_motivo = d, f"o cliente disse “{td}”"
                        break
        if conv.recorrencia:
            e.recorrencia = conv.recorrencia
        e.avisar = e.avisar or conv.avisar
        if conv.formato in ("whatsapp", "email", "chat") and not e.origem:
            e.origem = conv.formato
        if conv.assunto and len(e.titulo) < 8:
            e.titulo = conv.assunto[:120]
        if getattr(ta, "titulo_fixo", ""):
            e.titulo = ta.titulo_fixo
            if getattr(ta, "valor_total", 0):
                e.extraidos = dict(e.extraidos or {}, valor=ta.valor_total)
        ta.entendimento = e
        ta.titulo = e.titulo
        ta.deliveraveis = [it for it in ta.itens if it.origem in ("cliente", "equipe") and not it.texto.startswith("Receber do cliente")]
        # sem item vindo da conversa, o roteiro do catálogo entra
        if not any(it.origem in ("cliente", "equipe") for it in ta.itens) and e.tipo:
            ta.itens = [Item(x, origem="catalogo") for x in catalogo.checklist(e.tipo)] + ta.itens
        elif ta.deliveraveis and e.tipo and not any("enviar" in it.texto.lower() for it in ta.itens):
            ta.itens.append(Item("Enviar ao cliente", origem="catalogo"))
    conv.tarefas = tarefas
    conv.pode_juntar = len(tarefas) > 1
    conv.pode_separar = len(tarefas) == 1 and len(tarefas[0].deliveraveis) > 1
    if juntar is True and conv.pode_juntar:
        _juntar(conv, codigo, indice, pessoas, hoje, aprendizado)
    elif juntar is False and conv.pode_separar:
        _separar(conv, codigo, indice, pessoas, hoje, aprendizado)
    if not conv.cliente:
        conv.avisos.append("não achei o cliente — clique na ficha para escolher")
    return conv


def _tarefas_das_minhas_linhas(conv: Conversa, turnos: list, indice: Indice, pessoas, hoje, aprendizado) -> None:
    """Só você falou: cada linha é a caixa de cima, que pode ser várias demandas."""
    codigo = conv.cliente.codigo if conv.cliente else ""
    for idx, t in enumerate(turnos):
        for linha in t.texto.splitlines():
            if not linha.strip():
                continue
            for pedaco in separar(linha, indice):
                e = entender(pedaco, indice, pessoas=pessoas, hoje=hoje, aprendizado=aprendizado)
                if e.cliente is None and conv.cliente:
                    e.cliente, e.cliente_motivo = conv.cliente, conv.cliente_motivo
                elif e.cliente is not None and conv.cliente is None:
                    conv.cliente, conv.cliente_motivo = e.cliente, e.cliente_motivo
                    codigo = e.cliente.codigo
                ta = Tarefa(texto=pedaco, frases=[pedaco], turno=idx, entendimento=e, titulo=e.titulo)
                ta.frases_tipos = [e.tipo] if e.tipo else []
                itens = itens_da_frase(pedaco, hoje)
                ta.itens = [Item(x, origem="equipe", motivo="da sua linha") for x in itens] or \
                    [Item(x, origem="catalogo") for x in (e.checklist or [])]
                ta.deliveraveis = [it for it in ta.itens if it.origem == "equipe"]
                conv.tarefas.append(ta)
    conv.pode_juntar = len(conv.tarefas) > 1
    conv.pode_separar = len(conv.tarefas) == 1 and len(conv.tarefas[0].deliveraveis) > 1


def _juntar(conv: Conversa, codigo: str, indice, pessoas, hoje, aprendizado) -> None:
    """Todas as tarefas numa só: cada uma vira item (ou traz os seus itens)."""
    base = conv.tarefas[0]
    itens = []
    for ta in conv.tarefas:
        proprios = [it for it in ta.itens if it.origem in ("cliente", "equipe")]
        if proprios:
            itens.extend(proprios)
        else:
            itens.append(Item(ta.titulo, origem="cliente", motivo="era uma tarefa separada"))
    for ta in conv.tarefas:
        itens.extend(it for it in ta.itens if it.origem in ("pergunta", "anexo") or it.texto.startswith("Receber do cliente"))
    titulos = [ta.titulo for ta in conv.tarefas]
    titulo = " e ".join(_minuscula_inicial(t) if i else t for i, t in enumerate(titulos))
    if len(titulo) > 90:
        titulo = f"{titulos[0]} (+{len(titulos) - 1})"
    nova = Tarefa(texto=_texto_para_entender(codigo, [f for ta in conv.tarefas for f in ta.frases], []),
                  frases=[f for ta in conv.tarefas for f in ta.frases], turno=base.turno)
    nova.entendimento = base.entendimento
    nova.titulo = titulo
    vistos, limpos = set(), []
    for it in itens:
        if it.texto.lower() not in vistos:
            vistos.add(it.texto.lower())
            limpos.append(it)
    if not any("enviar" in it.texto.lower() for it in limpos):
        limpos.append(Item("Enviar ao cliente", origem="catalogo"))
    nova.itens = limpos
    nova.deliveraveis = [it for it in limpos if it.origem in ("cliente", "equipe") and not it.texto.startswith("Receber do cliente")]
    conv.tarefas = [nova]
    conv.juntar = True
    conv.pode_separar = len(nova.deliveraveis) > 1


def _separar(conv: Conversa, codigo: str, indice, pessoas, hoje, aprendizado) -> None:
    """Uma tarefa com vários entregáveis vira uma tarefa por entregável; o resto fica na primeira."""
    base = conv.tarefas[0]
    novas = []
    resto = [it for it in base.itens if it not in base.deliveraveis and it.origem != "catalogo"]
    for i, it in enumerate(base.deliveraveis):
        linha = _texto_para_entender(codigo, [it.texto], getattr(base, "complementos", []))
        e = entender(linha, indice, pessoas=pessoas, hoje=hoje, aprendizado=aprendizado)
        be = base.entendimento
        e.cliente, e.cliente_motivo = be.cliente, be.cliente_motivo
        e.prazo, e.prazo_motivo = be.prazo, be.prazo_motivo
        e.pessoa, e.recorrencia, e.avisar, e.origem = be.pessoa, be.recorrencia, be.avisar, be.origem
        ta = Tarefa(texto=linha, frases=[it.texto], turno=base.turno, entendimento=e, titulo=it.texto)
        ta.frases_tipos = [e.tipo] if e.tipo else []
        ta.itens = [Item(x, origem="catalogo") for x in (catalogo.checklist(e.tipo) if e.tipo else [])]
        if i == 0:
            ta.itens.extend(resto)
        ta.deliveraveis = []
        novas.append(ta)
    conv.tarefas = novas
    conv.juntar = False
    conv.pode_juntar = len(novas) > 1
    conv.pode_separar = False


def descricao(conv: Conversa) -> str:
    """O que vai para a descrição da tarefa: a conversa como chegou, com quem falou."""
    nome = conv.remetente_nome or conv.remetente_email or "cliente"
    if conv.formato == "whatsapp":
        cab = f"WhatsApp de {nome}" + (f" em {conv.quando}" if conv.quando else "")
    elif conv.formato == "email":
        cab = f"E-mail de {nome}" + (f" em {conv.quando}" if conv.quando else "") + (f" — assunto: {conv.assunto}" if conv.assunto else "")
    elif conv.formato == "conversa":
        cab = f"Conversa com {nome}"
    elif conv.formato == "chat":
        cab = f"Chat de atendimento com {nome}" + (f" ({conv.quando})" if conv.quando else "")
    else:
        cab = "Mensagem colada"
    com_lados = any(t.lado == "equipe" for t in conv.turnos) and any(t.lado == "cliente" for t in conv.turnos)
    linhas = []
    for t in conv.turnos:
        corpo = (t.texto_bruto or t.texto).strip()
        if not corpo:
            corpo = "(anexo)" if t.anexo else ""
        if not corpo:
            continue
        if com_lados or t.nome:
            quem = t.nome or ("Você" if t.lado == "equipe" else "Cliente")
            linhas.append(f"{quem}: {corpo}" if "\n" not in corpo else f"{quem}:\n{corpo}")
        else:
            linhas.append(corpo)
    return cab + "\n\n" + "\n".join(linhas).strip()
