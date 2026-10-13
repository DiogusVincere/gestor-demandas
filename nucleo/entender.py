"""A linha única: `101 carta de faturamento agora` vira cliente, tipo, prazo, prioridade.

Tudo por regra, e tudo visível: o que foi entendido volta em `Entendimento`, com o
motivo de cada parte, para a tela mostrar em fichas e a pessoa corrigir num clique.
Gravar nunca depende de entender tudo — o que faltar fica em branco e a demanda
nasce mesmo assim.

Calibrado com frases do dia a dia de uma equipe de serviços, como:
    "padaria pediu o para emitir nota para agora, ele pede urgente"
    "comercio modelo pediu para retificar o fechamento do mês 5 até dia 17"
    "cliente 103, tenho que enviar a aliquota todo mês pós fechamento do simples nacional"
    "Todo dia primeiro do mês tenho que emitir notas para a 105"
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import calendario, catalogo
from .clientes import Indice, chave_codigo, normalizar

DIAS_SEMANA = {"segunda": 0, "seg": 0, "terca": 1, "ter": 1, "quarta": 2, "qua": 2,
               "quinta": 3, "qui": 3, "sexta": 4, "sex": 4, "sabado": 5, "sab": 5, "domingo": 6, "dom": 6}
VERBOS_PEDIDO = ("pediu", "pedindo", "quer", "precisa", "precisando", "solicitou", "solicita",
                 "cobrou", "cobrando", "perguntou", "pergunta", "pede", "ligou pedindo")
VERBOS_INFORMACAO = ("mandou", "enviou", "respondeu", "chegou", "retornou", "pagou", "assinou",
                     "entregou", "devolveu", "confirmou", "aprovou")
ORIGENS = (("whatsapp", ("whatsapp", "whats", "zap", "wpp")), ("email", ("e-mail", "email", "mail")),
           ("telefone", ("ligou", "ligacao", "telefone", "telefonou")), ("presencial", ("veio aqui", "presencial")))
# Um número depois destas palavras não é código de cliente ("modelo 56", "dia 15", "anexo 3").
NAO_E_CODIGO = ("modelo", "mod", "dia", "anexo", "art", "artigo", "n", "no", "nº", "numero",
                "ate", "em", "r$", "x", "nota", "nf", "nfe", "nfse", "parcela", "mes", "mês", "ano", "pag",
                "pagina", "competencia", "comp", "guia", "das", "darf", "boleto", "cada", "todo", "a")
# Depois destas, o que vem costuma ser o cliente ("do 101", "da padaria", "cliente 102").
ANTES_DO_CLIENTE = ("do", "da", "de", "pro", "pra", "para o", "para a", "para", "com o", "com a",
                    "cliente", "cli", "@")
# Palavras que parecem nome mas não identificam cliente nenhum.
PALAVRAS_VAZIAS = {"banco", "contabil", "contabilidade", "prefeitura", "receita", "cliente", "empresa",
                   "fiscal", "pessoal", "departamento", "escritorio",
                   "pedido", "demanda", "nota", "notas", "guia", "mes", "setembro", "outubro", "agosto",
                   "contador", "contadora", "sistema", "portal", "email", "whatsapp", "hoje", "agora",
                   "amanha", "urgente", "fechamento", "simples", "nacional", "pagamento", "das", "dos",
                   "via", "guias", "gente", "aqui", "vocês", "voces", "certidao", "balancete", "carta",
                   "faturamento", "licitacao", "financeiro", "gerente", "oi", "ola", "bom", "boa", "dia",
                   "tarde", "noite", "tambem", "precisamos", "precisa", "preciso", "pode", "mandar"}
# "pagar o DAS todo dia 20": se cair no fim de semana, antecipa. Emitir nota, enviar, conferir: adia.
PALAVRAS_DE_PAGAMENTO = ("pagar", "pagamento", "guia", "das", "darf", "gps", "fgts", "boleto",
                         "vencimento", "recolher", "recolhimento", "parcela")
DIA_DO_MES = r"(\d{1,2}|primeiro|1o|1º)"
PADROES_RECORRENCIA = [
    re.compile(r"\b(?:todo|toda|a cada|cada) (?:mes|mês)[, ]*(?:no |todo )?dia " + DIA_DO_MES + r"\b"),
    re.compile(r"\btodo dia " + DIA_DO_MES + r"(?: d[eo] (?:cada )?(?:mes|mês))?\b"),
    re.compile(r"\b(?:mensal|mensalmente)[, ]*(?:no )?dia " + DIA_DO_MES + r"\b"),
    re.compile(r"\bdia " + DIA_DO_MES + r" de (?:todo|cada) (?:mes|mês)\b"),
]
PADRAO_SEMANAL = re.compile(r"\btod[ao]s? (?:as |os )?(segunda|terca|quarta|quinta|sexta|sabado|domingo)s?(?:-feira)?\b")
PADRAO_CADA_DIAS = re.compile(r"\ba cada (\d{1,3}) dias?\b")
PADRAO_CADA_SEMANAS = re.compile(r"\ba cada (\d{1,2}) semanas?\b")
# Erros de digitação e abreviações que a equipe usa de verdade ("todia 8", "td mes", "tds os dias")
CORRECOES = [(r"\btodia\b", "todo dia"), (r"\btd (mes|mês)\b", r"todo \1"), (r"\btds? os dias\b", "todos os dias"),
             (r"\btdo (mes|dia)\b", r"todo \1"), (r"\bmensalm\.?\b", "mensalmente"), (r"\bqnd\b", "quando"),
             (r"\bq\b", "que"), (r"\bpra mim\b", "para mim"), (r"\bp/ ", "para "), (r"\bvc\b", "voce"),
             (r"\bhj\b", "hoje"), (r"\bamanh\b", "amanha"), (r"\bsegunda feira\b", "segunda"), (r"\bsexta feira\b", "sexta")]
# "é recorrente", "fixa", "de sempre" = repete todo mês, mesmo sem dizer o dia
PALAVRAS_RECORRENTE = re.compile(r"\b(recorrente|recorrencia|demanda fixa|tarefa fixa|fixo|fixa|de sempre|sempre|todo fechamento|a cada fechamento|mensal(?:mente)?|todo mes|todos os meses)\b")
# "me avisar", "avisar", "lembrar" = quer o balão do Windows no dia
PEDE_AVISO = re.compile(r"\b(me avis[ae]r?|avisar|avise|lembrar|me lembr[ae]r?|lembrete|alerta|alertar)\b")
# "pra Ana", "atribuir à Carla", "@bruno", "Carla vai fazer", "passar para o Daniel"
PADROES_PESSOA = [
    re.compile(r"\b(?:atribu[ia]r (?:a|para|pra) (?:o |a )?|passar (?:para|pra) (?:o |a )?|responsavel:? (?:o |a )?|delegar (?:a|para|pra) (?:o |a )?)([a-z]+(?: [a-z]+)?)\b"),
    re.compile(r"(?:^|\s)@([a-z]+)\b"),
    re.compile(r"\b([a-z]+) (?:vai|pode|fica de|fica para|que) (?:fazer|ver|cuidar|resolver|tratar)\b"),
    re.compile(r"\b(?:pra|para|p/)\s+(?:o |a )?([a-z]+)\b"),
]
# "pós fechamento do simples", "depois do DAS", "antes do vencimento do ISS"
OBRIGACAO_NO_TEXTO = re.compile(
    r"\b(apos|depois d[eo]|pos|antes d[eo]|ate o|ate|no dia d[eo]) (?:(?:o |a )?(?:fechamento|vencimento|apuracao) d[eoa] )?"
    r"(das|simples(?: nacional)?|dctfweb|dctf|iss|icms|gia|gps|inss|fgts|pis|cofins|reinf|efd|livros?)\b")
# coisa sua, não do departamento: "eu: ir no RH", "minha vez de lavar a máquina de café", "tirar o lixo"
PREFIXO_PESSOAL = re.compile(r"^\s*(?:eu|pessoal|meu|minha|lembrete pessoal|para mim|pra mim|lembrete)\s*[:\-–]\s*", re.I)
PALAVRAS_PESSOAIS = re.compile(
    r"\b(minha vez|nossa vez|vez de|lavar|lixo|banheiro|cafe|cafeteira|maquina de cafe|copa|cozinha|geladeira|"
    r"ir (?:no|na|ao|a|pro|pra) (?:rh|medico|dentista|banco|mercado|correio|cartorio|academia|escola|creche|posto|farmacia|oficina)|"
    r"rh|medico|dentista|almoco|almocar|academia|remedio|farmacia|exame|consulta|"
    r"pagar (?:a |o |as |os )?(?:conta|boleto|aluguel|luz|agua|internet|cartao|condominio)|comprar|"
    r"buscar (?:o |a |os |as )?(?:filho|filha|criancas|meninos|meninas)|aniversario|presente|"
    r"beber agua|tomar agua|tomar remedio|carro|oficina|estacionamento|chaves?|senha do wifi|regar|plantas?|"
    r"lembrar de (?:beber|tomar|comer|ligar para a? ?mae|ligar pra mae))\b")
# "lavar a máquina toda sexta, rodízio": cada vez passa para o próximo da equipe
RODIZIO = re.compile(r"\b(?:em )?(rodizio|revezamento|revezar|revezando|cada um por vez|um por vez|alternando|alternar|a vez de cada um)\b")
# "às 15h", "as 15:30", "15h30", "depois do almoço", "de manhã", "fim do dia"
HORA_EXPLICITA = re.compile(r"(?<![\d/])(?:(?:as|às|la pelas|pelas|a partir das)\s+)?(\d{1,2})(?::(\d{2})|h(\d{2})?)(?![\d/])")
HORA_COM_AS = re.compile(r"\b(?:as|às)\s+(\d{1,2})(?![\d/:h])")
PERIODOS = [(r"\bde manha\b|\bpela manha\b|\bcedo\b", "09:00"), (r"\bantes do almoco\b", "11:30"), (r"\bdepois do almoco\b|\bapos o almoco\b|\bpos almoco\b", "13:30"),
            (r"\ba tarde\b|\bde tarde\b|\bpela tarde\b", "14:30"), (r"\bno fim do dia\b|\bfim do dia\b|\bfinal do dia\b|\bantes de ir embora\b", "17:30"),
            (r"\ba noite\b|\bde noite\b", "18:30")]


def achar_hora(norm: str) -> tuple:
    """("15:00", trecho) quando a linha diz uma hora; ("", "") senão. Hora de 6 a 22 só, para não pegar "dia 15"."""
    m = HORA_EXPLICITA.search(norm)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
        if 6 <= h <= 22 and mi < 60:
            return f"{h:02d}:{mi:02d}", m.group(0).strip()
    m = HORA_COM_AS.search(norm)
    if m:
        h = int(m.group(1))
        if 6 <= h <= 22:
            return f"{h:02d}:00", m.group(0).strip()
    for padrao, hora in PERIODOS:
        m = re.search(padrao, norm)
        if m:
            return hora, m.group(0)
    return "", ""


# Vence-se por URGÊNCIA, não por data: só mexe na prioridade e some do título.
FRASES_DE_PRESSA = re.compile(r"\b(?:ele|ela|o cliente|a cliente|cliente|eles)? ?(?:pede|pediu|disse|falou|e|esta|ta) (?:que e |que esta |com )?(?:urgente|urgencia|pressa)\b")


@dataclass
class Entendimento:
    texto: str
    titulo: str = ""
    cliente: object = None               # clientes.Cliente | None
    candidatos_cliente: list = field(default_factory=list)
    cliente_motivo: str = ""
    cliente_trecho: str = ""             # o que no texto virou o cliente (para aprender apelido)
    tipo: str = ""
    tipo_palavra: str = ""
    prazo: dt.date | None = None
    prazo_motivo: str = ""
    pessoa: str = ""
    pessoas: list = field(default_factory=list)   # "pra ana e bruno": todas; `pessoa` é a primeira
    grupo: str = ""
    etiquetas: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    notas: str = ""
    origem: str = ""
    e_informacao: bool = False
    recorrencia: str = ""
    avisar: bool = False                 # "me avisar" → lembrete no dia
    lembrete_cada: int | None = None     # "me avisar a cada 30 min" → repete no dia, em minutos
    hora: str = ""                       # "às 15h", "depois do almoço" → lembrete com hora ("15:00")
    pessoal: bool = False                # "eu: ir no RH", "minha vez de lavar a máquina": coisa sua, não do departamento
    pessoal_motivo: str = ""
    rodizio: bool = False                # "lavar a máquina toda sexta, rodízio": a cada vez passa para o próximo da equipe
    extraidos: dict = field(default_factory=dict)   # competencia, documento, valor
    avisos: list = field(default_factory=list)
    normalizado: str = ""

    @property
    def tipo_nome(self) -> str:
        return catalogo.nome(self.tipo) if self.tipo else ""


# ---------------------------------------------------------------- datas
def _proximo_dia_da_semana(hoje: dt.date, alvo: int, que_vem: bool) -> dt.date:
    delta = (alvo - hoje.weekday()) % 7
    if que_vem and delta < 7:
        delta += 7 if delta == 0 or hoje.weekday() >= alvo else 0
    return hoje + dt.timedelta(days=delta)


def _ultimo_dia_do_mes(d: dt.date) -> dt.date:
    primeiro_seguinte = dt.date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return primeiro_seguinte - dt.timedelta(days=1)


def _dia_mes(hoje: dt.date, dia: int, mes: int) -> dt.date:
    ano = hoje.year if (mes, dia) >= (hoje.month, hoje.day) else hoje.year + 1
    return dt.date(ano, mes, dia)


def _proximo_dia(hoje: dt.date, dia: int) -> dt.date:
    if dia >= hoje.day:
        try:
            return dt.date(hoje.year, hoje.month, dia)
        except ValueError:
            return _ultimo_dia_do_mes(hoje)
    ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
    try:
        return dt.date(ano, mes, dia)
    except ValueError:
        return _ultimo_dia_do_mes(dt.date(ano, mes, 1))


def achar_data(norm: str, hoje: dt.date) -> tuple:
    """(data, trecho que casou, motivo) ou (None, '', '')."""
    t = " " + norm + " "
    regras = [
        (r"\b(pra|para) ontem\b", lambda m: (hoje, "pra ontem")),
        (r"\bdepois de amanha\b", lambda m: (hoje + dt.timedelta(days=2), "depois de amanhã")),
        (r"\b(pra |para )?amanha\b", lambda m: (hoje + dt.timedelta(days=1), "amanhã")),
        (r"\b(pra |para )?(hoje|agora|imediato|imediatamente)\b", lambda m: (hoje, m.group(2))),
        (r"\bem (\d{1,2}) dias? uteis\b", lambda m: (calendario.somar_uteis(hoje, int(m.group(1))), f"em {m.group(1)} dias úteis")),
        (r"\b(\d{1,2}) dias? uteis\b", lambda m: (calendario.somar_uteis(hoje, int(m.group(1))), f"{m.group(1)} dias úteis")),
        (r"\bem (\d{1,2}) dias?\b", lambda m: (hoje + dt.timedelta(days=int(m.group(1))), f"em {m.group(1)} dias")),
        (r"\bem (\d{1,2}) semanas?\b", lambda m: (hoje + dt.timedelta(weeks=int(m.group(1))), f"em {m.group(1)} semana(s)")),
        (r"\b(ate o |ate |no |para o |para |pro )?(\d{1,2})/(\d{1,2})/(\d{4})\b", lambda m: (dt.date(int(m.group(4)), int(m.group(3)), int(m.group(2))), m.group(0).strip())),
        (r"\b(ate o |ate |no |para o |para |pro )?(\d{1,2})/(\d{1,2})(?![/\d])\b", lambda m: (_dia_mes(hoje, int(m.group(2)), int(m.group(3))), m.group(0).strip())),
        (r"\b(ate o |ate |no |para o |para |pro )?dia (\d{1,2})\b", lambda m: (_proximo_dia(hoje, int(m.group(2))), f"dia {m.group(2)}")),
        (r"\b(ate o |ate |no )?(fim|final) do mes\b", lambda m: (_ultimo_dia_do_mes(hoje), "fim do mês")),
        (r"\bsemana que vem\b", lambda m: (_proximo_dia_da_semana(hoje, 0, True), "semana que vem")),
        (r"\b(ate |para |pra |na |no )?(proxima |proximo )?(segunda|terca|quarta|quinta|sexta|sabado|domingo|seg|ter|qua|qui|sex|sab|dom)(-feira)?( que vem)?\b",
         lambda m: (_proximo_dia_da_semana(hoje, DIAS_SEMANA[m.group(3)], bool(m.group(2) or m.group(5))), m.group(0).strip())),
    ]
    for padrao, fabrica in regras:
        m = re.search(padrao, t)
        if m:
            try:
                data, motivo = fabrica(m)
            except ValueError:
                continue
            return data, m.group(0).strip(), motivo
    return None, "", ""


def achar_obrigacao_relativa(norm: str, hoje: dt.date) -> tuple:
    """"pós fechamento do simples" → (data, trecho, motivo, nome da obrigação, deslocamento em dias úteis)."""
    m = OBRIGACAO_NO_TEXTO.search(norm)
    if not m:
        return None, "", "", "", 0
    nome, data = calendario.obrigacao_no_texto(m.group(2), hoje)
    if not nome:
        return None, "", "", "", 0
    relacao = m.group(1)
    deslocamento = 1 if relacao in ("apos", "pos") or relacao.startswith("depois") else 0
    alvo = calendario.somar_uteis(data, deslocamento) if deslocamento else data
    motivo = f"{'depois d' if deslocamento else 'até '}{'o ' if deslocamento else ''}{nome} ({data:%d/%m})"
    return alvo, m.group(0), motivo, nome, deslocamento


def _numero_do_dia(texto: str) -> int:
    return 1 if texto in ("primeiro", "1o", "1º") else int(texto)


def achar_recorrencia(norm: str) -> tuple:
    """(recorrência, trecho). Formatos: mensal:N:antes|depois, semanal:seg, dias:N, obrig:<nome>:<deslocamento>."""
    regra = "antes" if any(re.search(r"\b" + p + r"\b", norm) for p in PALAVRAS_DE_PAGAMENTO) else "depois"
    for padrao in PADROES_RECORRENCIA:
        m = padrao.search(norm)
        if m:
            return f"mensal:{_numero_do_dia(m.group(1))}:{regra}", m.group(0)
    m = PADRAO_SEMANAL.search(norm)
    if m:
        return f"semanal:{m.group(1)[:3]}", m.group(0)
    m = PADRAO_CADA_DIAS.search(norm)
    if m:
        return f"dias:{int(m.group(1))}", m.group(0)
    m = PADRAO_CADA_SEMANAS.search(norm)
    if m:
        return f"dias:{int(m.group(1)) * 7}", m.group(0)
    m = re.search(r"\b(toda semana|semanalmente)\b", norm)
    if m:
        return "semanal:seg", m.group(0)
    m = re.search(r"\b(todo dia|diariamente|todos os dias)\b(?! \d)", norm)
    if m:
        return "dias:1", m.group(0)
    m = re.search(r"\b(quinzenal(?:mente)?|a cada quinze dias|de 15 em 15 dias)\b", norm)
    if m:
        return "dias:15", m.group(0)
    m = re.search(r"\b(trimestral(?:mente)?|a cada 3 meses|a cada tres meses)\b", norm)
    if m:
        return "dias:90", m.group(0)
    m = re.search(r"\b(semestral(?:mente)?|a cada 6 meses|a cada seis meses)\b", norm)
    if m:
        return "dias:180", m.group(0)
    m = re.search(r"\b(anual(?:mente)?|todo ano|a cada ano|uma vez por ano)\b", norm)
    if m:
        return "dias:365", m.group(0)
    m = PALAVRAS_RECORRENTE.search(norm)
    if m:
        # "é recorrente" sem dia: repete todo mês no mesmo dia do prazo (ou dia 1), e a ficha deixa trocar
        return f"mensal:1:{regra}", m.group(0)
    return "", ""


def corrigir_digitacao(norm: str) -> str:
    for padrao, troca in CORRECOES:
        norm = re.sub(padrao, troca, norm)
    return norm


def achar_pessoas(norm: str, pessoas) -> tuple:
    """([nomes como estão na equipe], [trechos]) — "pra ana e bruno", "@carla @daniel", "atribuir à Ana".

    Uma tarefa pode ser de várias pessoas: depois de um nome reconhecido, "e <nome>" / ", <nome>"
    também contam, desde que sejam da equipe.
    """
    conhecidas = {normalizar(p).lower(): p for p in pessoas if p}
    primeiros = {}
    for chave, nome in conhecidas.items():
        primeiros.setdefault(chave.split()[0], nome)
    excluidos = ("mim", "hoje", "amanha", "o", "a", "gente", "ele", "ela", "voce", "nos", "eu")

    def canonico(candidato: str):
        candidato = candidato.strip()
        if candidato in conhecidas:
            return conhecidas[candidato]
        primeiro = candidato.split()[0] if candidato else ""
        if primeiro in primeiros and primeiro not in excluidos:
            return primeiros[primeiro]
        return ""

    nomes, trechos = [], []
    for padrao in PADROES_PESSOA:
        for m in padrao.finditer(norm):
            nome = canonico(m.group(1))
            if not nome:
                continue
            if nome not in nomes:
                nomes.append(nome)
                trechos.append(m.group(0) if m.group(1).strip() in conhecidas else m.group(0).replace(m.group(1).strip(), m.group(1).strip().split()[0]))
            # "pra ana e bruno", "pra ana, bruno e carla"
            resto = norm[m.end():]
            while True:
                seg = re.match(r"^\s*(?:,|e)\s+(?:o |a )?([a-z]+)", resto)
                if not seg:
                    break
                outro = canonico(seg.group(1))
                if not outro:
                    break
                if outro not in nomes:
                    nomes.append(outro)
                    trechos.append(seg.group(0).strip())
                resto = resto[seg.end():]
    return nomes, trechos


def achar_pessoa(norm: str, pessoas) -> tuple:
    """(nome como está na equipe, trecho) quando a linha atribui a alguém conhecido."""
    conhecidas = {normalizar(p).lower(): p for p in pessoas if p}
    primeiros = {}
    for chave, nome in conhecidas.items():
        primeiros.setdefault(chave.split()[0], nome)
    for padrao in PADROES_PESSOA:
        for m in padrao.finditer(norm):
            candidato = m.group(1).strip()
            if candidato in conhecidas:
                return conhecidas[candidato], m.group(0)
            primeiro = candidato.split()[0]
            if primeiro in primeiros and primeiro not in ("mim", "hoje", "amanha", "o", "a", "gente", "ele", "ela"):
                return primeiros[primeiro], m.group(0).replace(candidato, primeiro)
    return "", ""


# ---------------------------------------------------------------- números que significam coisa
def achar_extraidos(norm: str, hoje: dt.date) -> tuple:
    """Competência, número de documento e valor citados na linha. (dict, [trechos a tirar do título])."""
    saida, trechos = {}, []
    # "fechamento do mês 5": o "fechamento" fica no título; só o "mês 5" vira competência
    m = re.search(r"\b((?:competencia|comp\.?|referente a|ref\.?|d[eo] mes(?: de)?|mes(?: de)?)\s*(?:de )?(\d{1,2})(?:[/-](\d{2,4}))?)\b", norm)
    if m and 1 <= int(m.group(2)) <= 12:
        mes = int(m.group(2))
        ano = int(m.group(3)) if m.group(3) else (hoje.year if mes <= hoje.month else hoje.year - 1)
        if ano < 100:
            ano += 2000
        saida["competencia"] = f"{mes:02d}/{ano}"
        trechos.append(m.group(1))
    else:
        m = re.search(r"(?<![\d/])(\d{2})/(\d{4})(?![\d/])", norm)
        if m and 1 <= int(m.group(1)) <= 12:
            saida["competencia"] = f"{int(m.group(1)):02d}/{m.group(2)}"
    m = re.search(r"\b(?:nf-?s?-?e?|nota(?: fiscal)?|nfse|nfe)\s*(?:n[º°o]?\.?\s*)?(\d{2,9})\b", norm)
    if m:
        saida["documento"] = m.group(1)
    m = re.search(r"r\$\s*([\d.]+(?:,\d{1,2})?)", norm)
    if m:
        try:
            saida["valor"] = float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass
    return saida, trechos


# ---------------------------------------------------------------- cliente
def _candidatos_numericos(norm: str, indice: Indice) -> list:
    saida = []
    # "582," e "582." no fim de frase são código; "1.500,00" não (ponto/vírgula seguidos de dígito)
    for m in re.finditer(r"(?<![\w/.,])@?(\d{1,4})(?![\w/%:]|[.,]\d)", norm):
        codigo = chave_codigo(m.group(1))
        if not codigo or not indice.achar(codigo):
            continue
        antes = norm[:m.start()].rstrip()
        palavra_antes = antes.split()[-1] if antes else ""
        if palavra_antes in NAO_E_CODIGO:
            continue
        pontos = 1
        if m.start() == 0 or m.group(0).startswith("@"):
            pontos += 3
        if palavra_antes in ANTES_DO_CLIENTE or norm[max(0, m.start() - 8):m.start()].strip() in ("para o", "para a", "com o", "com a"):
            pontos += 2
        saida.append((pontos, -m.start(), codigo, m.group(0)))
    return sorted(saida, reverse=True)


def achar_cliente(norm: str, indice: Indice) -> tuple:
    """(cliente, candidatos, trecho, motivo)."""
    numericos = _candidatos_numericos(norm, indice)
    if numericos:
        _p, _pos, codigo, trecho = numericos[0]
        return indice.achar(codigo), [], trecho.strip(), f"código {codigo}"

    tentativas = []
    for v in VERBOS_PEDIDO + VERBOS_INFORMACAO + ("ligou", "mandou msg", "mandou mensagem", "tenho que", "precisa"):
        m = re.search(r"^(?:o |a |cliente |o cliente |a cliente )?(.{2,40}?)[, ]+" + re.escape(v) + r"\b", norm)
        if m:
            tentativas.append(m.group(1))
            break
    palavras = norm.split()
    for i, p in enumerate(palavras):
        if p in ANTES_DO_CLIENTE and i + 1 < len(palavras):
            for n in (3, 2, 1):
                tentativas.append(" ".join(palavras[i + 1:i + 1 + n]))
    for n in (3, 2, 1):
        if len(palavras) >= n:
            tentativas.append(" ".join(palavras[:n]))
            tentativas.append(" ".join(palavras[-n:]))

    vistas = set()
    sugestao = tentativas[0] if tentativas and any(
        re.search(r"\b" + re.escape(v) + r"\b", norm) for v in VERBOS_PEDIDO + VERBOS_INFORMACAO + ("ligou",)) else ""
    for tentativa in tentativas:
        tentativa = re.sub(r"^(o |a |os |as |cliente |o cliente |a cliente )", "", tentativa).strip(" ,.;:")
        if len(tentativa) < 3 or tentativa.isdigit() or tentativa in vistas:
            continue
        vistas.add(tentativa)
        if all(p in PALAVRAS_VAZIAS or len(p) < 3 for p in tentativa.split()):
            continue
        achados = indice.por_nome(tentativa)
        if achados:
            melhor, pontos = achados[0]
            candidatos = [c for c, p in achados[1:4] if pontos - p <= 8]
            if candidatos:
                return melhor, candidatos, tentativa, f"parece “{tentativa}” — confira"
            return melhor, [], tentativa, f"pelo nome: “{tentativa}”"
    sugestao = re.sub(r"^(o |a |os |as |cliente |o cliente |a cliente )", "", sugestao).strip(" ,.;:")
    if sugestao and not sugestao.isdigit() and not all(p in PALAVRAS_VAZIAS for p in sugestao.split()):
        return None, [], "", "apelido?" + sugestao
    return None, [], "", ""


# ---------------------------------------------------------------- várias numa linha
def separar(texto: str, indice: Indice) -> list:
    """Uma linha que são várias demandas vira várias linhas.

    "101, 102, 103: enviar o das"  → uma por cliente.
    "101 pediu carta de faturamento e cnd federal" → uma por tipo do catálogo, o cliente repetido.
    """
    linha = texto.strip().splitlines()[0] if texto.strip() else ""
    norm = normalizar(linha).lower()
    m = re.match(r"^\s*((?:\d{1,4}\s*[,;e]\s*)+\d{1,4})\s*[:\-–]\s*(.+)$", norm)
    if m:
        codigos = [c for c in re.split(r"[,;e\s]+", m.group(1)) if c]
        if len(codigos) > 1 and all(indice.achar(c) for c in codigos):
            resto = linha[m.end(1):].lstrip(" :-–")
            return [f"{c} {resto}" for c in codigos]
    tipos = catalogo.achar_todos(norm)
    if len({t for t, _p, _i in tipos}) >= 2:
        # corta no " e " (ou vírgula) que fica entre dois tipos diferentes
        cortes = []
        for (t1, _p1, i1), (t2, _p2, i2) in zip(tipos, tipos[1:]):
            if t1 == t2:
                continue
            meio = norm[i1:i2]
            k = max(meio.rfind(" e "), meio.rfind(", "), meio.rfind(" + "))
            if k >= 0:
                cortes.append(i1 + k)
        if cortes:
            partes, inicio = [], 0
            for k in cortes:
                partes.append(linha[inicio:k].strip(" ,+"))
                inicio = k + (3 if norm[k:k + 3] == " e " else 2)
            partes.append(linha[inicio:].strip(" ,+"))
            primeira_norm = normalizar(partes[0]).lower()
            cliente, _c, trecho, _m = achar_cliente(primeira_norm, indice)
            prefixo = f"{cliente.codigo} " if cliente else ""
            saida = [partes[0]]
            for p in partes[1:]:
                if prefixo and not re.search(r"\b" + re.escape(cliente.codigo) + r"\b", normalizar(p).lower()):
                    p = prefixo + p
                saida.append(p)
            return [p for p in saida if p.strip()]
    return [texto]


# ---------------------------------------------------------------- principal
def entender(texto: str, indice: Indice, pessoas=(), hoje: dt.date | None = None,
             aprendizado: dict | None = None, cliente_por_nome: bool = True) -> Entendimento:
    """`cliente_por_nome=False`: a frase é do CLIENTE (conversa colada) — uma palavra solta dela não
    vira cliente por parecença de nome ("de forma automática" não é a FORMA & CIA). Código e apelido valem."""
    hoje = hoje or dt.date.today()
    aprendizado = aprendizado or {}
    e = Entendimento(texto=texto.strip())
    linhas = [l.rstrip() for l in e.texto.splitlines()]
    primeira = linhas[0] if linhas else ""
    for l in linhas[1:]:
        s = l.strip()
        if s.startswith(("- ", "* ", "[ ] ", "[] ")):
            e.checklist.append(re.sub(r"^(- |\* |\[ \] |\[\] )", "", s).strip())
        elif s:
            e.notas += (s + "\n")
    e.notas = e.notas.strip()

    # a correção de digitação vale no texto bruto também, senão "todia 8" fica no título
    bruto = primeira
    for padrao, troca in CORRECOES:
        bruto = re.sub(padrao, troca, bruto, flags=re.I)
    norm = corrigir_digitacao(normalizar(bruto).lower())
    remover = []

    # "eu: …", "pessoal: …" é coisa sua, não do departamento (as palavras típicas decidem mais abaixo)
    m = PREFIXO_PESSOAL.match(bruto)
    if m:
        e.pessoal, e.pessoal_motivo = True, f"você escreveu “{m.group(0).strip()}”"
        bruto = bruto[m.end():]
        norm = corrigir_digitacao(normalizar(bruto).lower())
    # "toda sexta, rodízio": a cada vez passa para o próximo da equipe
    m = RODIZIO.search(norm)
    if m:
        e.rodizio = True
        remover.extend([m.group(0), ", " + m.group(0), "em " + m.group(0)])
    # "às 15h", "depois do almoço": lembrete com hora
    e.hora, trecho_hora = achar_hora(norm)
    if trecho_hora:
        remover.append(trecho_hora)
        e.avisar = True

    # "me avisar", "lembrar": pede o balão do Windows no dia do prazo
    m = PEDE_AVISO.search(norm)
    if m:
        e.avisar = True
        remover.append(m.group(0))
        remover.append("e " + m.group(0))
        remover.append(", " + m.group(0))
        # "me avisar a cada 30 min", "lembrar de 2 em 2 horas", "a cada 1:30h"
        mc = re.search(r"\b(?:a cada|de (\d+) em) (\d+)(?:[:h,.](\d{1,2}))? ?(min|minutos|minuto|m|h|hr|hrs|hora|horas)\b", norm)
        if mc:
            inteiro, fracao, unidade = int(mc.group(2)), mc.group(3), mc.group(4)
            if unidade.startswith(("h",)):
                minutos = inteiro * 60 + (int(fracao) if fracao and len(fracao) == 2 else (int(fracao) * 6 if fracao else 0))
            else:
                minutos = inteiro
            if 5 <= minutos <= 12 * 60:
                e.lembrete_cada = minutos
                remover.append(mc.group(0))

    for m in re.finditer(r"#([\w-]+)", bruto):
        e.etiquetas.append(m.group(1).lower())
        remover.append(m.group(0))

    m = re.search(r"(?:->|→|\bno grupo\b|\bgrupo:)\s*([^#\n]+?)\s*$", bruto, flags=re.I)
    if m:
        e.grupo = m.group(1).strip()
        remover.append(m.group(0))

    e.pessoas, trechos_pessoa = achar_pessoas(norm, pessoas)
    e.pessoa = e.pessoas[0] if e.pessoas else ""
    remover.extend(trechos_pessoa)

    for origem, palavras in ORIGENS:
        if any(re.search(r"\b" + re.escape(p) + r"\b", norm) for p in palavras):
            e.origem = origem
            break

    # pressa dita em palavras ("ele pede urgente") some do título; a prioridade já olha para ela
    for m in FRASES_DE_PRESSA.finditer(norm):
        remover.append(m.group(0))

    # recorrência e data
    e.recorrencia, trecho_rec = achar_recorrencia(norm)
    norm_sem_rec = norm
    if trecho_rec:
        remover.append(trecho_rec)
        norm_sem_rec = norm.replace(trecho_rec, " ")
        # "demanda fixa … todo fechamento": tudo que fala de repetição sai do título
        for m in PALAVRAS_RECORRENTE.finditer(norm):
            remover.append(m.group(0))
            remover.append(", " + m.group(0))
            remover.append("e " + m.group(0))
    data, trecho_data, motivo = achar_data(norm_sem_rec, hoje)
    data_obrig, trecho_obrig, motivo_obrig, nome_obrig, desloc = achar_obrigacao_relativa(norm_sem_rec, hoje)
    if data_obrig:
        e.prazo, e.prazo_motivo = data_obrig, motivo_obrig
        remover.append(trecho_obrig)
        if e.recorrencia.startswith("mensal:1:"):
            # "todo mês pós fechamento do simples": a repetição segue a obrigação, não o dia 1
            e.recorrencia = f"obrig:{nome_obrig}:{desloc}"
    elif data:
        e.prazo, e.prazo_motivo = data, motivo
        remover.append(trecho_data)
        remover.append("ate " + trecho_data)
    elif e.recorrencia.startswith("mensal:"):
        _tipo, dia, regra = (e.recorrencia.split(":") + ["depois"])[:3]
        e.prazo = calendario.proxima_mensal(int(dia), regra, hoje, minimo=hoje)
        e.prazo_motivo = f"todo mês dia {dia}" + (f" (ajustado para {e.prazo:%d/%m})" if e.prazo.day != int(dia) else "")
    if data and e.recorrencia.startswith("mensal:1:") and trecho_rec and PALAVRAS_RECORRENTE.search(trecho_rec):
        # "recorrente, até dia 17": repete todo mês no dia que a pessoa deu, não no dia 1
        e.recorrencia = f"mensal:{data.day}:{e.recorrencia.split(':')[2]}"
    elif e.recorrencia.startswith("semanal:"):
        alvo = DIAS_SEMANA.get(e.recorrencia.split(":")[1], 0)
        e.prazo = _proximo_dia_da_semana(hoje, alvo, False)
        e.prazo_motivo = "toda semana"

    # números que viram campos
    e.extraidos, trechos_extra = achar_extraidos(norm_sem_rec, hoje)
    remover.extend(trechos_extra)

    # cliente
    cliente, candidatos, trecho_cliente, motivo_cliente = achar_cliente(norm, indice)
    if not cliente_por_nome and cliente is not None and not motivo_cliente.startswith("código") \
            and normalizar(trecho_cliente).lower() not in indice.apelidos:
        cliente, candidatos, trecho_cliente, motivo_cliente = None, [], "", ""
    e.cliente, e.candidatos_cliente, e.cliente_motivo = cliente, candidatos, motivo_cliente
    e.cliente_trecho = trecho_cliente
    if cliente is None and motivo_cliente.startswith("apelido?"):
        e.cliente_trecho, e.cliente_motivo = motivo_cliente[8:], ""
    if trecho_cliente:
        remover.append(trecho_cliente)

    # tipo: catálogo (sem a parte que já virou prazo/recorrência, senão "pós fechamento do
    # simples" vira Simples em vez de Alíquota), depois o que a equipe ensinou corrigindo tarefas
    norm_tipo = norm_sem_rec.replace(trecho_obrig, " ") if trecho_obrig else norm_sem_rec
    e.tipo, e.tipo_palavra = catalogo.achar(norm_tipo)
    if not e.tipo:
        e.tipo, e.tipo_palavra = catalogo.achar(norm)
    if not e.tipo:
        for palavra, tipo in (aprendizado.get("tipos") or {}).items():
            if re.search(r"\b" + re.escape(palavra) + r"\b", norm) and tipo in catalogo.tipos():
                e.tipo, e.tipo_palavra = tipo, palavra
                break
    if e.tipo and e.prazo is None and not e.e_informacao:
        dias = catalogo.prazo_uteis(e.tipo)
        if dias is not None:
            e.prazo = calendario.somar_uteis(hoje, dias)
            e.prazo_motivo = f"padrão de {catalogo.nome(e.tipo).lower()}: {dias} dia(s) útil(eis)"
    if e.tipo and not e.checklist:
        e.checklist = catalogo.checklist(e.tipo)

    tem_pedido = any(re.search(r"\b" + re.escape(v) + r"\b", norm) for v in VERBOS_PEDIDO)
    tem_info = any(re.search(r"\b" + re.escape(v) + r"\b", norm) for v in VERBOS_INFORMACAO)
    e.e_informacao = tem_info and not tem_pedido and not e.tipo

    # coisa sua? O que você marcou da última vez manda; senão, palavras típicas sem cliente nem tipo
    if not e.pessoal:
        decidido = None
        for palavra, valor in (aprendizado.get("pessoal") or {}).items():
            if palavra and re.search(r"\b" + re.escape(palavra) + r"\b", norm):
                decidido = bool(valor)
                break
        # um cliente chutado por UMA palavra parecida ("café" → CAFE …) não impede: coisa sua ganha do chute
        chute_fraco = e.cliente is not None and not e.cliente_motivo.startswith("código") and len(e.cliente_trecho.split()) < 2
        if decidido is not None:
            e.pessoal, e.pessoal_motivo = decidido, ("como você marcou da última vez" if decidido else "")
        elif (e.cliente is None or chute_fraco) and not e.tipo:
            mp = PALAVRAS_PESSOAIS.search(norm)
            if mp:
                e.pessoal, e.pessoal_motivo = True, f"parece coisa sua: “{mp.group(0)}”"
                if chute_fraco:
                    remover = [r for r in remover if r != trecho_cliente]
                    e.cliente, e.candidatos_cliente, e.cliente_motivo, e.cliente_trecho = None, [], "", ""

    e.normalizado = norm
    e.titulo = _limpar_titulo(bruto, remover, norm)

    if not e.cliente and not e.e_informacao and not e.pessoal:
        e.avisos.append("não achei o cliente — a demanda fica sem cliente até você escolher")
    if e.cliente and getattr(e.cliente, "codigo", "") in indice.repetidos:
        e.avisos.append(f"o código {e.cliente.codigo} aparece mais de uma vez em clientes.json")
    return e


def _limpar_titulo(bruto: str, remover: list, norm: str) -> str:
    """Tira do texto o que já virou campo e deixa o pedido em si."""
    from .clientes import sem_acento
    titulo = bruto
    for trecho in sorted({r for r in remover if r}, key=len, reverse=True):
        padrao = r"\s*" + r"\s+".join(re.escape(p) for p in trecho.split()) + r"\s*"
        # sem_acento preserva o tamanho (normalizar() comprime espaços e desalinha as posições)
        titulo_norm = sem_acento(titulo).lower()
        m = re.search(padrao, titulo_norm)
        if m and len(titulo_norm) == len(titulo):
            titulo = titulo[:m.start()] + " " + titulo[m.end():]
        else:
            titulo = re.sub(padrao, " ", titulo, flags=re.I)
    # conversa que não é o pedido: cumprimento, "aqui é da X", "vocês conseguem", "pra gente"
    titulo = re.sub(r"^\s*(oi|ola|olá|bom dia|boa tarde|boa noite|tudo bem\??|e ai|e aí)[,!. ]*", "", titulo, flags=re.I)
    titulo = re.sub(r"\b(aqui (e|é) (da|do|a|o)( [\w.]+)?,?|voc[eê]s? (conseguem?|pod(em|e)|poderiam?)( me)?|(da|pra|para) gente|por (favor|gentileza)|valeu|obrigad[oa]|ainda)\b", " ", titulo, flags=re.I)
    # frase de cortesia colada no fim ("…12 meses. Pode me mandar") não é parte do pedido
    partes = re.split(r"\.\s+", titulo)
    if len(partes) > 1:
        titulo = partes[0] + "".join(". " + p for p in partes[1:] if catalogo.achar(p)[0] or len(p) > 45)
    titulo = re.sub(r"^\W+|\W+$", "", titulo)
    # "Ana, precisamos do livro…": o vocativo não é o pedido
    titulo = re.sub(r"^[A-Za-zÀ-ÿ]{2,20},\s+(?=\S)", "", titulo)
    # ", vou fazer", ", deixa comigo" no fim: é resposta sua, não parte do pedido
    titulo = re.sub(r"[,;]?\s*\b(vou (fazer|mandar|ver|enviar|providenciar|resolver)|deixa comigo|pode deixar|faco|faço|ja vou|já vou)\s*$", "", titulo, flags=re.I)
    # "vocês ficaram de parametrizar pra gente conseguir emitir…" → "parametrizar para emitir…"
    titulo = re.sub(r"^\s*(?:e a[ií] |ai |aí |ent[ãa]o,? )?(?:voc[eê]s?|vcs?) (?:ficaram|ficou|v[ãa]o|vai|iam|ia) (?:de |que |ter que )?", "", titulo, flags=re.I)
    # (os trechos tirados antes deixam espaço duplo: por isso \s+)
    titulo = re.sub(r"\b(?:pra|para)\s+(?:a\s+)?(?:gente|n[óo]s|mim|eu)\s+(?:conseguir|poder|conseguirmos|podermos)\b", "para", titulo, flags=re.I)
    titulo = re.sub(r"\b(?:pra|para)\s+(?:conseguir|poder)\s+(?=\w+r\b)", "para ", titulo, flags=re.I)
    titulo = re.sub(r"\b(\w+r)\s+(?:conseguir|poder)\s+(?=\w+r\b)", r"\1 para ", titulo, flags=re.I)
    for _ in range(3):
        titulo = titulo.lstrip(" ,.;:-")
        # "poderiam nos enviar o balancete", "pode me mandar a cnd": o pedido é o documento
        titulo = re.sub(r"^(poderiam?|podem?|conseguem?|da pra|dá pra|tem como|teria como|favor|por favor|solicito|solicitamos|gostaria de|gostariamos de|gostaríamos de)"
                        r"( me| nos)?( (enviar|mandar|passar|encaminhar|gerar|fazer|emitir|tirar|puxar|providenciar|verificar|ver|receber|ter))?\s*(o |a |os |as |um |uma )?", "", titulo, flags=re.I).lstrip(" ,.;:-")
        titulo = re.sub(r"^(o cliente |a cliente |cliente |o |a )", "", titulo, flags=re.I).lstrip(" ,.;:-")
        titulo = re.sub(r"^(o |a )?(banco|contador|contadora|contabilidade|gerente|pessoal|financeiro|rh)( d[oa] (banco|cliente|empresa))?[, ]+(?=\w)", "", titulo, flags=re.I)
        titulo = re.sub(r"^(me |nos )?(pediu|pede|quer|precisa|precisam|solicitou|solicita|mandou msg|mandou mensagem|ligou)\b"
                        r"( (pra|para|que|de|uma|um|a|o|as|os|da|do|me|nos))*\s*", "", titulo, flags=re.I).lstrip(" ,.;:-")
        # "tenho que verificar…", "preciso enviar…": o verbo de obrigação é ruído
        titulo = re.sub(r"^((eu |nos |a gente |tambem |também )?(tenho|temos|tem|preciso|precisamos|precisa|precisava|devo|devemos|gostaria|queria|quero) (que |de |da |do )?)+", "", titulo, flags=re.I).lstrip(" ,.;:-")
    titulo = re.sub(r"\s+(,|\.|;|\?)", r"\1", titulo)
    # "balancete, a DRE e o razão": artigo dentro da enumeração só pesa
    titulo = re.sub(r"(,\s*|\s+e\s+)(?:a|o|as|os|da|do|das|dos)\s+(?=\w)", r"\1", titulo, flags=re.I)
    # o cliente saiu e deixou o artigo: "cobrar o pela documentação" → "cobrar pela documentação"
    def _artigo_solto(m):
        # "retificar o DAS de julho": esse "das" é a guia, não artigo pendurado
        antes = titulo[max(0, m.start() - 3):m.start()].lower()
        if m.group(1).lower() == "das" and (m.group(1) == "DAS" or antes.endswith(("o ", "do "))):
            return m.group(0)
        return m.group(2)
    titulo = re.sub(r"\b(o|a|os|as|do|da|dos|das) (pela|pelo|para|pra|com|de|do|da|em|no|na|sobre|até|ate)\b", _artigo_solto, titulo, flags=re.I)
    titulo = re.sub(r",\s*,", ",", titulo)
    pendurada = r"(até|ate|pro|pra|para|do|da|de|no|na|com|em|o|a|os|as|e|é|que|mas)"
    for _ in range(3):
        titulo = re.sub(r"(^|\s)" + pendurada + r"\s*$", "", titulo, flags=re.I).strip(" ,.;:-")
        titulo = re.sub(r"^" + pendurada + r"\s+", "", titulo, flags=re.I).strip(" ,.;:-")
    titulo = re.sub(r"\s{2,}", " ", titulo).strip(" ,.;:-")
    return (titulo[:1].upper() + titulo[1:]) if titulo else bruto.strip()
