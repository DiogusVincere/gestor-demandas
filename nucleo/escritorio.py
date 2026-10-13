"""O escritório: vários departamentos, cada um com a sua pasta de dados.

Modelo B: a segurança é a **permissão da pasta** (no Windows, a ACL que a TI administra), não
senha. `departamentos.json`, ao lado do `catalogo.json`, lista os departamentos e as pastas
(relativas à pasta do app ou absolutas, inclusive de rede):

    [{"nome": "Fiscal",   "pasta": "dados/fiscal"},
     {"nome": "Contábil", "pasta": "//servidor/compartilhado/contabil/demandas"}]

Quem abre o app carrega **só as pastas que o Windows deixa ler**: membro do Fiscal vê o
Fiscal; a gestora, com acesso a todas, vê todas; quem não tem acesso vê o departamento
listado como "sem acesso", e nada mais. Quem pode editar o `departamentos.json` é o admin.

Quando o servidor central (modelo A) chegar, esta classe continua: muda só quem decide o
acesso — hoje o Windows, amanhã o login.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import calendario, catalogo
from .clientes import Indice
from .dados import Area, PRIORIDADES, TIPOS_DE_CAMPO, RAIZ_DADOS

PASTA_FERRAMENTA = Path(os.path.abspath(__file__)).parent.parent
ARQUIVO_DEPARTAMENTOS = PASTA_FERRAMENTA / "departamentos.json"
# o nome do espaço só da pessoa. Não é "Pessoal" porque "Departamento Pessoal" (folha) é um departamento
# real em escritório contábil e o nome bateria.
NOME_PESSOAL = "Meu espaço"


@dataclass
class Departamento:
    nome: str
    pasta: Path
    area: Area | None = None
    erro: str = ""
    cor: str = ""

    @property
    def acessivel(self) -> bool:
        return self.area is not None


class Escritorio:
    def __init__(self, indice: Indice, arquivo: Path = ARQUIVO_DEPARTAMENTOS, pasta_padrao: Path = RAIZ_DADOS):
        self.indice = indice
        self.arquivo = Path(arquivo)
        self.pasta_padrao = Path(pasta_padrao)
        self.departamentos: list = []
        # modelo A: com login ligado, quem enxerga o quê é o usuário da requisição (thread-local),
        # não a permissão da pasta. O servidor define o usuário antes de rotear e limpa depois.
        self.login_ligado = False
        self._contexto = threading.local()
        # o espaço Pessoal de cada pessoa (dados\pessoal\<nome>\ dentro do primeiro departamento dela)
        self._areas_pessoais: dict = {}
        self._tranca_pessoal = threading.Lock()
        # teto de espaços pessoais abertos (None = sem teto). A demonstração pública usa, porque cada
        # nome digitado na página abriria uma pasta nova.
        self.max_pessoais: int | None = None
        self.carregar()

    def definir_usuario(self, usuario: dict | None) -> None:
        self._contexto.usuario = usuario

    def usuario(self) -> dict | None:
        return getattr(self._contexto, "usuario", None)

    def definir_pessoa(self, nome: str) -> None:
        """Quem está na requisição (nome da página ou do login): decide qual espaço Pessoal entra em `acessiveis()`."""
        self._contexto.pessoa = (nome or "").strip()

    def pessoa(self) -> str:
        return getattr(self._contexto, "pessoa", "") or ""

    @staticmethod
    def _chave_pessoa(nome: str) -> str:
        from .clientes import normalizar
        return "-".join(normalizar(nome).lower().split())[:40]

    def area_pessoal(self, nome: str) -> Area | None:
        """O espaço só da pessoa: nasce na primeira vez, na pasta do primeiro departamento que ela acessa."""
        nome = (nome or "").strip()
        chave = self._chave_pessoa(nome)
        if not chave:
            return None
        with self._tranca_pessoal:
            if chave in self._areas_pessoais:
                return self._areas_pessoais[chave]
            if self.max_pessoais is not None and len(self._areas_pessoais) >= self.max_pessoais:
                return None
            abertos = [d for d in self.departamentos if d.acessivel]
            if self.login_ligado:
                u = self.usuario()
                if u and u.get("nome") == nome:
                    abertos = [d for d in abertos if d.nome in (u.get("departamentos") or [])] or abertos
            if not abertos:
                return None
            raiz = abertos[0].pasta / "pessoal" / chave
            try:
                area = Area(self.indice, raiz=raiz, nome="Pessoal", pessoal=True, armazem=("sqlite" if abertos[0].area.armazem.nome == "sqlite" else ""))
            except OSError:
                return None
            area.dono = nome
            area.encaminhar_notificacao = lambda para, de, tipo, t, texto: self._notificar_outra(para, de, tipo, t, texto)
            self._areas_pessoais[chave] = area
            return area

    def _notificar_outra(self, para: str, de: str, tipo: str, t: dict, texto: str) -> None:
        """Avisa alguém no espaço Pessoal dela (quem mandou a demanda pessoal é avisado quando ela conclui)."""
        alvo = self.area_pessoal(para)
        if alvo is not None:
            alvo._notificar(para, de, tipo, t, texto)

    def _departamento_pessoal(self) -> "Departamento | None":
        nome = self.pessoa()
        if not nome:
            return None
        area = self.area_pessoal(nome)
        if area is None:
            return None
        return Departamento(NOME_PESSOAL, area.raiz, area=area, cor="#5E706E")

    # ------------------------------------------------------------ carga
    @staticmethod
    def _pasta(texto: str) -> Path:
        """Caminho relativo no departamentos.json é relativo à pasta do app (dados/fiscal), não ao cwd."""
        p = Path(str(texto).strip())
        return p if p.is_absolute() else (PASTA_FERRAMENTA / p)

    def configuracao(self) -> list:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            lista = dados.get("departamentos", dados) if isinstance(dados, dict) else dados
            saida = []
            for d in lista:
                if isinstance(d, dict) and d.get("nome") and d.get("pasta"):
                    saida.append({"nome": d["nome"].strip(), "pasta": d["pasta"], "cor": d.get("cor", ""),
                                  "armazem": (d.get("armazem") or "").strip().lower()})
            if saida:
                return saida
        except (OSError, ValueError):
            pass
        return [{"nome": "Equipe", "pasta": str(self.pasta_padrao), "cor": ""}]

    def carregar(self) -> None:
        self.departamentos = []
        for d in self.configuracao():
            dep = Departamento(d["nome"], self._pasta(d["pasta"]), cor=d.get("cor", ""))
            try:
                # só a pasta que o Windows deixa ler entra; a dos outros fica "sem acesso"
                pasta = dep.pasta
                if pasta.exists():
                    os.listdir(pasta)
                dep.area = Area(self.indice, raiz=pasta, nome=dep.nome, armazem=d.get("armazem", ""))
            except PermissionError:
                dep.erro = "sem acesso (permissão da pasta)"
            except OSError as erro:
                dep.erro = f"não abriu: {erro.strerror or erro}"
            self.departamentos.append(dep)

    def acessiveis(self) -> list:
        """Com login ligado, só os departamentos que o usuário da requisição pode ver (membro: os seus;
        gestor: os seus + os que gere; admin: todos). Sem login, os que a pasta do Windows deixa ler."""
        abertos = [d for d in self.departamentos if d.acessivel]
        if self.login_ligado:
            u = self.usuario()
            if not u:
                return []
            from .usuarios import Usuarios
            abertos = [d for d in abertos if Usuarios.pode_ver(u, d.nome)]
        # o espaço Pessoal de quem está na requisição entra junto (só o dela; nunca o dos outros)
        pessoal = self._departamento_pessoal() if abertos else None
        return abertos + ([pessoal] if pessoal is not None else [])

    def departamento(self, nome: str) -> Departamento | None:
        alvo = (nome or "").strip().lower()
        if alvo == NOME_PESSOAL.lower():
            return self._departamento_pessoal()
        return next((d for d in self.departamentos if d.nome.lower() == alvo), None)

    def area_padrao(self) -> Area:
        a = self.acessiveis()
        if not a:
            raise PermissionError("você não tem acesso à pasta de nenhum departamento")
        return a[0].area

    # ------------------------------------------------------------ onde mora cada coisa
    def area_de_espaco(self, eid: str) -> Area:
        for d in self.acessiveis():
            if d.area.espaco(eid):
                return d.area
        raise KeyError("espaço não existe")

    def area_de_lista(self, lid: str) -> Area:
        for d in self.acessiveis():
            if d.area.lista(lid):
                return d.area
        raise KeyError("lista não existe")

    def area_de_tarefa(self, tid: str) -> Area:
        for d in self.acessiveis():
            if tid in d.area.tarefas:
                return d.area
        raise KeyError("tarefa não existe")

    def area_de_modelo(self, mid: str) -> Area:
        for d in self.acessiveis():
            if any(m["id"] == mid for m in d.area.modelos):
                return d.area
        raise KeyError("modelo não existe")

    def area_por_nome(self, nome: str) -> Area:
        if not nome:
            return self.area_padrao()
        d = self.departamento(nome)
        if d is None or not d.acessivel:
            raise PermissionError(f"sem acesso ao departamento {nome}")
        return d.area

    def nome_da_area(self, area: Area) -> str:
        if getattr(area, "pessoal", False):
            return NOME_PESSOAL
        return next((d.nome for d in self.departamentos if d.area is area), "")

    # ------------------------------------------------------------ leitura
    def versao(self) -> str:
        partes = []
        for d in self.acessiveis():
            d.area.recarregar_se_mudou()
            partes.append(f"{d.nome}:{d.area.versao}")
        return "|".join(partes)

    def tudo(self, pessoa: str = "") -> dict:
        if pessoa:
            self.definir_pessoa(pessoa)
        espacos, listas, tarefas, modelos, triagens, pessoas, lembretes, avisos = [], [], [], [], {}, set(), [], []
        equipes = {}
        for d in self.acessiveis():
            t = d.area.tudo(pessoa)
            equipes[d.nome] = t.get("equipe", [])
            for e in t["espacos"]:
                espacos.append({**e, "departamento": d.nome})
            for l in t["listas"]:
                listas.append({**l, "departamento": d.nome})
            for x in t["tarefas"]:
                tarefas.append({**x, "departamento": d.nome})
            for m in t["modelos"]:
                modelos.append({**m, "departamento": d.nome})
            triagens[d.nome] = t["triagem"]
            pessoas.update(t["pessoas"])
            lembretes.extend(t["lembretes"])
            avisos.extend(f"{d.nome}: {a}" for a in t["avisos"])
        return {
            "versao": self.versao(), "espacos": espacos, "listas": listas, "tarefas": tarefas, "modelos": modelos,
            "triagem": triagens, "equipe": equipes, "pessoas": sorted(pessoas, key=str.lower), "lembretes": lembretes, "avisos": avisos,
            "tipos": {k: v.get("nome", k) for k, v in catalogo.tipos().items()},
            "prioridades": list(PRIORIDADES), "tipos_de_campo": list(TIPOS_DE_CAMPO),
            "obrigacoes": [o["nome"] for o in calendario.obrigacoes()],
            "departamentos": [{"nome": d.nome, "pasta": str(d.pasta), "acessivel": d in self.acessiveis(),
                               "erro": d.erro or ("" if d in self.acessiveis() else "sem acesso (login)"), "cor": d.cor}
                              for d in self.departamentos],
            "admin": self.e_admin(),
            "login_ligado": self.login_ligado,
            "usuario": ({k: self.usuario()[k] for k in ("login", "nome", "papel", "departamentos", "gere")} if self.usuario() else None),
        }

    # ------------------------------------------------------------ administração
    def e_admin(self) -> bool:
        """Com login: papel admin. Sem login: quem consegue escrever o departamentos.json (permissão da pasta)."""
        if self.login_ligado:
            u = self.usuario()
            return bool(u and u.get("papel") == "admin")
        try:
            alvo = self.arquivo if self.arquivo.exists() else self.arquivo.parent
            return os.access(alvo, os.W_OK)
        except OSError:
            return False

    def editar_departamentos(self, lista: list) -> list:
        """Grava a lista de departamentos. Cria a pasta de dados quando dá; a permissão é da TI."""
        if not self.e_admin():
            raise PermissionError("só quem pode escrever o departamentos.json altera os departamentos")
        saida = []
        for d in lista:
            nome, pasta = (d.get("nome") or "").strip(), (d.get("pasta") or "").strip()
            if not nome or not pasta:
                continue
            saida.append({"nome": nome, "pasta": pasta, "cor": d.get("cor", ""), "armazem": (d.get("armazem") or "").strip().lower()})
            try:
                self._pasta(pasta).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        self.arquivo.write_text(json.dumps({"departamentos": saida}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.carregar()
        return saida
