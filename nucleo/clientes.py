"""Clientes: o cadastro de códigos, nomes e apelidos que a caixa de cima reconhece.

Mora em `clientes.json`, na pasta de dados (`dados/clientes.json` por padrão, ou o que vier em
`--clientes`). É um JSON simples, editável à mão, pela tela (⚙ → Clientes) ou por `PUT /api/clientes`:

    [{"codigo": "101", "nome": "Empresa Exemplo Ltda", "apelidos": ["exemplo"]}, ...]

Ao lado dele pode existir `contatos.json`, opcional, que liga e-mail, telefone ou CNPJ a um código.
É como a conversa colada descobre o cliente pelo remetente:

    [{"email": "financeiro@empresa-exemplo.com.br", "codigo": "101"},
     {"telefone": "11999990000", "codigo": "102"},
     {"cnpj": "12345678000190", "codigo": "103"}]

Os dois arquivos são relidos quando mudam no disco. Os apelidos que a equipe ensina corrigindo a
tela (`aprendizado.json` de cada departamento) somam-se aos do arquivo.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover - só sem o rapidfuzz instalado
    _fuzz = None

# Os clientes que nascem com o app, para a primeira abertura já ter o que reconhecer.
SEMENTE = [
    {"codigo": "101", "nome": "Empresa Exemplo Ltda", "apelidos": ["exemplo"]},
    {"codigo": "102", "nome": "Comércio Modelo", "apelidos": ["modelo"]},
    {"codigo": "103", "nome": "Indústria Fictícia", "apelidos": ["ficticia"]},
    {"codigo": "104", "nome": "Padaria Central", "apelidos": ["padaria"]},
    {"codigo": "105", "nome": "Clínica Horizonte", "apelidos": ["horizonte", "clinica"]},
]
# Palavras de razão social que não identificam ninguém ("das" não é a EMPRESA DAS ARTES).
SOCIETARIAS = {"LTDA", "ME", "EPP", "SA", "S/A", "EIRELI", "MEI", "SS", "SOCIEDADE", "INDIVIDUAL", "LIMITADA",
               "DE", "DA", "DO", "DAS", "DOS", "E", "&", "CIA", "COMERCIO", "SERVICOS", "SERVICO", "EMPRESA",
               "GRUPO", "FILIAL", "MATRIZ", "HOLDING", "PARTICIPACOES", "INDUSTRIA", "REPRESENTACOES"}
_INTERVALO_RELEITURA = 2.0   # segundos entre uma olhada e outra no mtime do arquivo


# ---------------------------------------------------------------- texto
def sem_acento(texto: str) -> str:
    """Tira os acentos preservando o tamanho (é → e). Serve para cortar trechos por posição."""
    decomposto = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(ch for ch in decomposto if not unicodedata.combining(ch))


def normalizar(texto: str) -> str:
    """Sem acento, espaços comprimidos, MAIÚSCULAS. Pontuação fica (datas, R$, vírgulas importam)."""
    return re.sub(r"\s+", " ", sem_acento(texto)).strip().upper()


def chave_codigo(texto) -> str:
    """O código como chave: só dígitos, sem zeros à esquerda ("0101" e "101" são o mesmo cliente)."""
    digitos = re.sub(r"\D", "", str(texto or ""))
    if not digitos:
        return ""
    return digitos.lstrip("0") or "0"


def _palavras(nome: str) -> list:
    return [p for p in re.findall(r"[A-Z0-9&]+", normalizar(nome)) if len(p) >= 2 and p not in SOCIETARIAS]


# ---------------------------------------------------------------- parecença (rapidfuzz, com reserva)
def _ratio(a: str, b: str) -> float:
    if _fuzz is not None:
        return float(_fuzz.ratio(a, b))
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio() * 100


def _partial_ratio(a: str, b: str) -> float:
    if _fuzz is not None:
        return float(_fuzz.partial_ratio(a, b))
    curto, longo = (a, b) if len(a) <= len(b) else (b, a)
    if not curto:
        return 0.0
    return max(_ratio(curto, longo[i:i + len(curto)]) for i in range(0, max(1, len(longo) - len(curto) + 1)))


def _token_set_ratio(a: str, b: str) -> float:
    if _fuzz is not None:
        return float(_fuzz.token_set_ratio(a, b))
    ta, tb = set(a.split()), set(b.split())
    comum = " ".join(sorted(ta & tb))
    return max(_ratio(comum, " ".join(sorted(ta))), _ratio(comum, " ".join(sorted(tb)))) if comum else _ratio(a, b)


# ---------------------------------------------------------------- dados
@dataclass
class Cliente:
    codigo: str
    nome: str
    apelidos: list = field(default_factory=list)
    palavras: list = field(default_factory=list)   # o nome sem as palavras societárias, para comparar

    def dict(self) -> dict:
        return {"codigo": self.codigo, "nome": self.nome, "apelidos": list(self.apelidos)}


class Apelidos(dict):
    """{apelido → código} que não liga para acento nem maiúscula: "Padaria", "PADARIA" e "padaria" são a mesma chave."""

    @staticmethod
    def _chave(k) -> str:
        return normalizar(k).lower()

    def __setitem__(self, k, v):
        super().__setitem__(self._chave(k), v)

    def __getitem__(self, k):
        return super().__getitem__(self._chave(k))

    def __contains__(self, k):
        return super().__contains__(self._chave(k))

    def get(self, k, padrao=None):
        return super().get(self._chave(k), padrao)

    def pop(self, k, *padrao):
        return super().pop(self._chave(k), *padrao)

    def update(self, outro=(), **kw):
        for k, v in dict(outro, **kw).items():
            self[k] = v


class Indice:
    """Os clientes em memória, lidos de `clientes.json` (e `contatos.json`, se existir)."""

    def __init__(self, arquivo: Path | str | None = None, clientes: list | None = None):
        self.arquivo = Path(arquivo) if arquivo else None
        self.clientes: dict = {}
        self.apelidos = Apelidos()
        self.repetidos: set = set()
        self.avisos: list = []
        self._contatos: dict = {}
        self._mtime = None
        self._mtime_contatos = None
        self._olhado_em = 0.0
        self._tranca = threading.RLock()
        if clientes is not None:
            self.definir(clientes)
        elif self.arquivo is not None:
            self.recarregar(forcar=True)

    # ---- arquivo
    @property
    def arquivo_contatos(self) -> Path | None:
        return self.arquivo.with_name("contatos.json") if self.arquivo is not None else None

    def _mtime_de(self, caminho: Path | None):
        try:
            return caminho.stat().st_mtime if caminho is not None else None
        except OSError:
            return None

    def recarregar_se_mudou(self) -> bool:
        """Relê os arquivos quando o mtime mudou (olha no máximo a cada 2 s)."""
        if self.arquivo is None:
            return False
        agora = time.monotonic()
        if agora - self._olhado_em < _INTERVALO_RELEITURA:
            return False
        self._olhado_em = agora
        mudou = False
        if self._mtime_de(self.arquivo) != self._mtime:
            self.recarregar(forcar=True)
            mudou = True
        if self._mtime_de(self.arquivo_contatos) != self._mtime_contatos:
            self._ler_contatos()
            mudou = True
        return mudou

    def recarregar(self, forcar: bool = False) -> None:
        with self._tranca:
            if self.arquivo is None:
                return
            if not self.arquivo.is_file():
                # primeira abertura: nasce com os clientes de exemplo, para a tela já reconhecer alguma coisa
                try:
                    self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                    self.arquivo.write_text(json.dumps(SEMENTE, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError as erro:
                    self.avisos.append(f"não consegui criar {self.arquivo}: {erro}")
            try:
                lido = json.loads(self.arquivo.read_text(encoding="utf-8"))
            except (OSError, ValueError) as erro:
                self.avisos.append(f"{self.arquivo.name}: não li ({erro})")
                lido = []
            if isinstance(lido, dict):
                lido = lido.get("clientes", [])
            self.definir(lido if isinstance(lido, list) else [])
            self._mtime = self._mtime_de(self.arquivo)
            self._ler_contatos()

    def _ler_contatos(self) -> None:
        caminho = self.arquivo_contatos
        mapa = {}
        if caminho is not None and caminho.is_file():
            try:
                lido = json.loads(caminho.read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    lido = lido.get("contatos", lido)
                itens = lido.items() if isinstance(lido, dict) else [(None, c) for c in lido]
                for chave, c in itens:
                    if not isinstance(c, dict):
                        continue
                    codigo = chave_codigo(c.get("codigo", ""))
                    if not codigo:
                        continue
                    email = str(c.get("email") or (chave if chave and "@" in str(chave) else "") or "").strip().lower()
                    if email:
                        mapa[email] = codigo
                    telefone = re.sub(r"\D", "", str(c.get("telefone") or ""))[-11:]
                    if len(telefone) >= 10:
                        mapa[telefone] = codigo
                    cnpj = re.sub(r"\D", "", str(c.get("cnpj") or ""))
                    if len(cnpj) == 14:
                        mapa[cnpj] = codigo
            except (OSError, ValueError) as erro:
                self.avisos.append(f"{caminho.name}: não li ({erro})")
        self._contatos = mapa
        self._mtime_contatos = self._mtime_de(caminho)

    def definir(self, lista: list) -> None:
        """Troca o cadastro em memória pela lista dada (dicts com codigo, nome e apelidos)."""
        with self._tranca:
            clientes, repetidos = {}, set()
            fixos = Apelidos()
            for bruto in lista:
                if not isinstance(bruto, dict):
                    continue
                codigo = chave_codigo(bruto.get("codigo", ""))
                nome = re.sub(r"\s+", " ", str(bruto.get("nome") or "")).strip()
                if not codigo or not nome:
                    continue
                if codigo in clientes:
                    repetidos.add(codigo)
                    continue
                apelidos = [str(a).strip() for a in (bruto.get("apelidos") or []) if str(a).strip()]
                clientes[codigo] = Cliente(codigo, nome, apelidos, _palavras(nome))
                for a in apelidos:
                    fixos[a] = codigo
            self.clientes = clientes
            self.repetidos = repetidos
            # os apelidos do arquivo entram sem apagar os aprendidos (que o departamento soma depois)
            self.apelidos.update(fixos)

    def lista(self) -> list:
        self.recarregar_se_mudou()
        return [c.dict() for c in sorted(self.clientes.values(), key=lambda c: (len(c.codigo), c.codigo))]

    def gravar(self, lista: list) -> list:
        """Valida, grava o `clientes.json` e recarrega. É o `PUT /api/clientes`."""
        if self.arquivo is None:
            raise ValueError("este índice não tem arquivo")
        if not isinstance(lista, list):
            raise ValueError("mande uma lista de clientes")
        limpos, vistos = [], set()
        for bruto in lista:
            if not isinstance(bruto, dict):
                continue
            codigo = chave_codigo(bruto.get("codigo", ""))
            nome = re.sub(r"\s+", " ", str(bruto.get("nome") or "")).strip()
            if not codigo and not nome:
                continue
            if not codigo:
                raise ValueError(f"“{nome}” está sem código (só números)")
            if not nome:
                raise ValueError(f"o código {codigo} está sem nome")
            if codigo in vistos:
                raise ValueError(f"o código {codigo} aparece duas vezes")
            vistos.add(codigo)
            apelidos = bruto.get("apelidos") or []
            if isinstance(apelidos, str):
                apelidos = [a for a in re.split(r"[,;\n]+", apelidos)]
            apelidos = [str(a).strip() for a in apelidos if str(a).strip()]
            limpos.append({"codigo": codigo, "nome": nome, "apelidos": apelidos})
        with self._tranca:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.arquivo.with_suffix(".json.tmp")
            temporario.write_text(json.dumps(limpos, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporario, self.arquivo)
            self.recarregar(forcar=True)
        return self.lista()

    # ---- consulta
    def achar(self, codigo) -> Cliente | None:
        self.recarregar_se_mudou()
        return self.clientes.get(chave_codigo(codigo))

    def contatos(self) -> dict:
        """{e-mail | telefone | cnpj → código} do `contatos.json`."""
        self.recarregar_se_mudou()
        return dict(self._contatos)

    def por_nome(self, texto: str, minimo: int = 78) -> list:
        """[(cliente, pontos)] parecidos com o texto, do mais parecido para o menos, só com pontos >= `minimo`.

        Apelido (do arquivo ou aprendido) vale 100. Uma palavra só é comparada com cada palavra do nome
        ("padaria" → PADARIA CENTRAL). Com várias, compara o conjunto e desconta cada palavra do texto
        que não aparece no nome — "indústria modelo" não vira a Indústria Fictícia por causa de uma palavra.
        """
        self.recarregar_se_mudou()
        alvo = normalizar(texto)
        if not alvo:
            return []
        if alvo in self.apelidos:
            c = self.achar(self.apelidos[alvo])
            return [(c, 100)] if c else []
        pa = _palavras(alvo)
        if not pa:
            return []
        alvo_limpo = " ".join(pa)
        saida = []
        for c in self.clientes.values():
            pn = c.palavras
            if not pn:
                continue
            if len(pa) == 1:
                p = pa[0]
                pontos = max(_ratio(p, w) for w in pn)
                if len(p) >= 4 and any(w.startswith(p) for w in pn):
                    pontos = max(pontos, 90.0)
            else:
                nome_limpo = " ".join(pn)
                pontos = max(_token_set_ratio(alvo_limpo, nome_limpo), _partial_ratio(alvo_limpo, nome_limpo))
                faltam = sum(1 for p in pa if not any(_ratio(p, w) >= 80 or (len(p) >= 4 and w.startswith(p)) for w in pn))
                pontos -= 12 * faltam
            if pontos >= minimo:
                saida.append((c, int(round(pontos))))
        saida.sort(key=lambda x: (-x[1], len(x[0].codigo), x[0].codigo))
        return saida


def carregar(arquivo: Path | str) -> Indice:
    """O índice do `clientes.json` dado; o arquivo nasce com os exemplos se não existir."""
    return Indice(arquivo)
