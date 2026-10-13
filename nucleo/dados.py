"""A área de trabalho: espaços → listas → tarefas, em arquivos JSON na pasta `dados\\`.

    dados\\espacos.json            os espaços (com prefixo do ID e o contador), e a ordem
    dados\\listas.json             as listas: status, campos personalizados, visões salvas, automações
    dados\\modelos.json            os modelos de lista (status + campos + tarefas prontas)
    dados\\tarefas\\<id>.json      uma tarefa por arquivo (escrita atômica)
    dados\\historico\\<id>\\       os últimos 20 snapshots de cada tarefa
    dados\\lixeira\\               o que foi apagado
    dados\\versao.txt              sobe a cada gravação; é como outra máquina percebe a mudança

Cada tarefa tem uma **chave** legível, `EQP-12`: prefixo do espaço + número que só cresce. Cada
departamento tem o seu espaço e o seu prefixo, e a numeração não se mistura.

Área só, da equipe: cada tarefa tem responsável e "Minhas tarefas" filtra por pessoa.
Nada de banco em compartilhamento de rede: tudo em memória, recarregado quando `versao.txt` muda.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

from . import calendario, catalogo
from . import armazem as mod_armazem
from . import conversa as mod_conversa
from . import importancia as mod_importancia
from . import mensagem as mod_mensagem
from .clientes import Indice, chave_codigo, normalizar
from .entender import entender, separar

# Palavras que não ensinam tipo nenhum quando a pessoa corrige o tipo de uma tarefa.
PALAVRAS_SEM_LICAO = {"para", "pelo", "pela", "com", "sem", "uma", "das", "dos", "que", "cliente", "pediu",
                      "enviar", "mandar", "fazer", "conferir", "verificar", "hoje", "amanha", "urgente",
                      "mes", "ano", "dia", "todo", "toda", "sobre", "tenho", "preciso"}

PASTA_FERRAMENTA = Path(os.path.abspath(__file__)).parent.parent
RAIZ_DADOS = PASTA_FERRAMENTA / "dados"
SNAPSHOTS = 20

PRIORIDADES = ("urgente", "alta", "normal", "baixa")
STATUS_PADRAO = [
    {"id": "afazer", "nome": "A fazer", "cor": "#B4B2A9", "tipo": "aberto"},
    {"id": "fazendo", "nome": "Fazendo", "cor": "#378ADD", "tipo": "aberto"},
    {"id": "aguardando", "nome": "Aguardando cliente", "cor": "#EF9F27", "tipo": "aguardando"},
    {"id": "feito", "nome": "Concluído", "cor": "#639922", "tipo": "feito"},
]
TIPOS_DE_STATUS = ("aberto", "aguardando", "feito")
TIPOS_DE_CAMPO = ("texto", "numero", "dinheiro", "data", "selecao", "simnao", "pessoa")
CORES_ESPACO = ("#2F5D8A", "#7F77DD", "#D85A30", "#D4537E", "#378ADD", "#639922", "#BA7517")
# prefixos de ID mais legíveis que as três primeiras letras ("Equipe" → EQP, não EQU)
PREFIXOS_SUGERIDOS = {"EQUIPE": "EQP", "FISCAL": "FIS", "CONTABIL": "CON", "PESSOAL": "DP", "JURIDICO": "JUR",
                      "SOCIETARIO": "SOC", "FINANCEIRO": "FIN", "ADMINISTRATIVO": "ADM", "COMERCIAL": "COM"}
EVENTOS = ("status", "criada", "prazo_passou", "checklist_completo", "prioridade", "liberada")
ACOES = ("status", "prioridade", "responsavel", "lembrar", "mover_lista", "prazo_mais")


def agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def novo_id(prefixo: str = "") -> str:
    return prefixo + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporario, caminho)


def _ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _id_curto(texto: str, prefixo: str = "c") -> str:
    base = re.sub(r"[^a-z0-9]", "", normalizar(texto).lower())[:24]
    return base or novo_id(prefixo)


class Area:
    def __init__(self, indice: Indice, raiz: Path = RAIZ_DADOS, nome: str = "Equipe", armazem: str = "", pessoal: bool = False):
        self.indice = indice
        self.nome = nome or "Equipe"          # o departamento dono desta pasta
        self.pessoal = pessoal                # o espaço de uma pessoa só (dados\pessoal\<nome>\)
        self.encaminhar_notificacao = None    # o Escritório põe aqui como avisar alguém que não é dono deste espaço
        self.raiz = Path(raiz)
        # JSON (pasta compartilhada, várias máquinas) ou SQLite (servidor central, um processo só)
        self.armazem = mod_armazem.escolher(self.raiz, armazem)
        self.pasta_tarefas = self.raiz / "tarefas"
        self.pasta_historico = self.raiz / "historico"
        self.pasta_lixeira = self.raiz / "lixeira"
        self.tranca = threading.RLock()
        self.espacos: list = []
        self.listas: list = []
        self.modelos: list = []
        self.equipe: list = []
        self.tarefas: dict = {}
        self.aprendizado: dict = {"apelidos": {}, "padroes": {}, "tipos": {}, "responsaveis": {},
                                  "listas": {}, "remetentes": {}, "lados": {}, "pessoal": {}}
        self.triagem: dict = {"caixa_entrada": "", "regras": []}
        self.versao = 0
        self.avisos: list = []
        self.carregar()

    # ------------------------------------------------------------ carga
    def carregar(self) -> None:
        with self.tranca:
            arm = self.armazem
            self.espacos = arm.ler_colecao("espacos", [])
            self.listas = arm.ler_colecao("listas", [])
            self.modelos = arm.ler_colecao("modelos", [])
            lido = arm.ler_colecao("aprendizado", {})
            if not isinstance(lido, dict):
                lido = {}
            for chave in self.aprendizado:
                self.aprendizado[chave] = dict(lido.get(chave, {})) if isinstance(lido.get(chave, {}), dict) else {}
            self.indice.apelidos.update(self.aprendizado.get("apelidos", {}))
            self.triagem = arm.ler_colecao("triagem", self.triagem)
            if not isinstance(self.triagem, dict):
                self.triagem = {"caixa_entrada": "", "regras": []}
            self.triagem.setdefault("caixa_entrada", "")
            self.triagem.setdefault("regras", [])
            equipe = arm.ler_colecao("equipe", [])
            self.equipe = [str(n).strip() for n in equipe if str(n).strip()] if isinstance(equipe, list) else []
            self.tarefas, self.avisos = arm.ler_tarefas()
            self.versao = self._versao_em_disco()
            if not self.espacos:
                self._semear()
            self._migrar()

    def _migrar(self) -> None:
        """Dados de versões anteriores ganham o que faltava, uma vez só."""
        mudou_espacos = mudou_listas = False
        for e in self.espacos:
            if not e.get("prefixo"):
                e["prefixo"] = self._prefixo_livre(e["nome"])
                mudou_espacos = True
            e.setdefault("contador", 0)
        for l in self.listas:
            for chave, padrao in (("campos", []), ("visoes", []), ("automacoes", [])):
                if chave not in l:
                    l[chave] = padrao
                    mudou_listas = True
        ids_listas = {l["id"] for l in self.listas}
        por_espaco = {l["id"]: l["espaco"] for l in self.listas}
        for t in sorted(self.tarefas.values(), key=lambda x: x.get("criada", "")):
            gravar = False
            if t.get("lista") not in ids_listas and ids_listas:
                t["lista"] = self.listas[0]["id"]
                gravar = True
            if not t.get("chave"):
                e = self.espaco(por_espaco.get(t["lista"], ""))
                if e is not None:
                    e["contador"] = int(e.get("contador", 0)) + 1
                    t["chave"] = f"{e['prefixo']}-{e['contador']}"
                    mudou_espacos = gravar = True
            for chave, padrao in (("campos", {}), ("lembrete", None), ("atrasou_em", None), ("lembrete_cada", None),
                                  ("comentarios", []), ("anexos", []), ("lembrete_hora", ""), ("rodizio", []), ("lembrete_motivo", "")):
                if chave not in t:
                    t[chave] = padrao
                    gravar = True
            if "responsaveis" not in t:
                # uma tarefa pode ser de várias pessoas; `responsavel` continua sendo a primeira
                t["responsaveis"] = [t["responsavel"]] if t.get("responsavel") else []
                gravar = True
            if gravar:
                self._gravar_tarefa(t, snapshot=False, subir=False)
        if mudou_espacos:
            self._gravar_espacos(subir=False)
        if mudou_listas:
            self._gravar_listas(subir=False)
        # dados antigos sem Caixa de entrada ganham uma (o espaço Pessoal não tem)
        if not self.pessoal and not self.lista(self.triagem.get("caixa_entrada", "")) and self.espacos:
            existente = next((l for l in self.listas if normalizar(l["nome"]) == "CAIXA DE ENTRADA"), None)
            if existente is None:
                existente = self.criar_lista(self.espacos[0]["id"], "Caixa de entrada")
            self.triagem["caixa_entrada"] = existente["id"]
            self._gravar_triagem()

    def _prefixo_livre(self, nome: str) -> str:
        chave = re.sub(r"[^A-Z]", "", normalizar(nome))
        letras = PREFIXOS_SUGERIDOS.get(chave, chave)
        base = (letras[:3] or "ESP").ljust(3, "X")
        usados = {e.get("prefixo") for e in self.espacos}
        candidato, n = base, 2
        while candidato in usados:
            candidato, n = f"{base}{n}", n + 1
        return candidato

    def _versao_em_disco(self) -> int:
        return self.armazem.versao()

    def _subir_versao(self) -> None:
        self.versao = max(self.versao, self._versao_em_disco()) + 1
        self.armazem.gravar_versao(self.versao)

    def recarregar_se_mudou(self) -> bool:
        if self._versao_em_disco() != self.versao:
            self.carregar()
            return True
        return False

    def _semear(self) -> None:
        if self.pessoal:
            # o espaço de uma pessoa só — lembretes e rotinas dela; sem Caixa de entrada nem triagem
            e = self.criar_espaco("Meu espaço", prefixo="EU")
            self.criar_lista(e["id"], "Lembretes", status=[{"id": "afazer", "nome": "A fazer", "cor": "#B4B2A9", "tipo": "aberto"},
                                                          {"id": "feito", "nome": "Feito", "cor": "#1B7A4B", "tipo": "feito"}])
            self.criar_lista(e["id"], "Rotinas", status=[{"id": "afazer", "nome": "A fazer", "cor": "#B4B2A9", "tipo": "aberto"},
                                                        {"id": "feito", "nome": "Feito", "cor": "#1B7A4B", "tipo": "feito"}])
            return
        # o primeiro espaço leva o nome do departamento dono da pasta (e o prefixo sai dele)
        e = self.criar_espaco(self.nome)
        caixa = self.criar_lista(e["id"], "Caixa de entrada")
        self.criar_lista(e["id"], "Demandas de clientes")
        self.criar_lista(e["id"], "Pendências internas")
        self.triagem["caixa_entrada"] = caixa["id"]
        self._gravar_triagem()
        if not self.equipe:
            self.armazem.gravar_colecao("equipe", [])      # a Equipe nasce vazia: cada um cadastra os nomes

    # ------------------------------------------------------------ triagem
    def _gravar_triagem(self) -> None:
        self.armazem.gravar_colecao("triagem", self.triagem)
        self._subir_versao()

    def editar_triagem(self, campos: dict) -> dict:
        """`caixa_entrada` = id da lista para o que não tem regra; `regras` = [{se:{tipo, cliente,
        palavra}, entao:{lista, responsavel, prioridade}}]."""
        with self.tranca:
            if "caixa_entrada" in campos:
                self.triagem["caixa_entrada"] = campos["caixa_entrada"] if self.lista(campos["caixa_entrada"]) else ""
            if "regras" in campos:
                regras = []
                for r in campos["regras"]:
                    se = {k: str(v).strip() for k, v in (r.get("se") or {}).items() if k in ("tipo", "cliente", "palavra") and str(v).strip()}
                    entao = {k: str(v).strip() for k, v in (r.get("entao") or {}).items() if k in ("lista", "responsavel", "prioridade") and str(v).strip()}
                    if se and entao:
                        regras.append({"id": r.get("id") or novo_id("r"), "se": se, "entao": entao})
                self.triagem["regras"] = regras
            self._gravar_triagem()
            return self.triagem

    def triar(self, t: dict, lista_pedida: str, explicita: bool) -> None:
        """Decide a lista e o responsável de uma tarefa nova.

        Ordem: regra de triagem que bate → lista aprendida para cliente+tipo → a lista pedida
        (quando a pessoa estava nela) → Caixa de entrada → a lista pedida.
        """
        norm_titulo = normalizar(t.get("titulo", "")).lower()
        for r in self.triagem.get("regras", []):
            se = r["se"]
            if se.get("tipo") and se["tipo"] != t.get("tipo"):
                continue
            if se.get("cliente") and chave_codigo(se["cliente"]) != t.get("cliente"):
                continue
            if se.get("palavra") and not re.search(r"\b" + re.escape(normalizar(se["palavra"]).lower()) + r"\b", norm_titulo):
                continue
            entao = r["entao"]
            if entao.get("lista") and self.lista(entao["lista"]):
                t["lista"] = entao["lista"]
            if entao.get("responsavel") and not t.get("responsavel_explicito"):
                try:
                    self._definir_responsaveis(t, [entao["responsavel"]])
                except ValueError:
                    pass          # regra aponta alguém que saiu da Equipe: a tarefa fica com quem tinha
            if entao.get("prioridade") in PRIORIDADES:
                t["prioridade"], t["motivo_prioridade"] = entao["prioridade"], "regra de triagem"
            t["triada_por"] = r.get("id", "")
            return
        aprendida = self.aprendizado.get("listas", {}).get(f"{t.get('cliente', '')}|{t.get('tipo', '')}")
        if aprendida and self.lista(aprendida) and not explicita:
            t["lista"], t["triada_por"] = aprendida, "aprendido"
            return
        if explicita and self.lista(lista_pedida):
            t["lista"] = lista_pedida
            return
        caixa = self.triagem.get("caixa_entrada")
        if caixa and self.lista(caixa):
            t["lista"], t["triada_por"] = caixa, "caixa"
        elif self.lista(lista_pedida):
            t["lista"] = lista_pedida

    # ------------------------------------------------------------ duplicatas
    def duplicatas(self, cliente: str, tipo: str, titulo: str, dias: int = 60) -> list:
        """Tarefas abertas do mesmo cliente que parecem o mesmo pedido."""
        if not cliente:
            return []
        limite = (dt.datetime.now() - dt.timedelta(days=dias)).isoformat()
        palavras = {p for p in normalizar(titulo).lower().split() if len(p) > 3 and p not in PALAVRAS_SEM_LICAO}
        achadas = []
        for t in self.tarefas.values():
            if t.get("cliente") != cliente or self._feita(t) or t.get("criada", "") < limite:
                continue
            mesmo_tipo = bool(tipo) and t.get("tipo") == tipo
            outras = {p for p in normalizar(t.get("titulo", "")).lower().split() if len(p) > 3 and p not in PALAVRAS_SEM_LICAO}
            parecido = bool(palavras) and len(palavras & outras) / max(len(palavras), 1) >= 0.6
            if mesmo_tipo or parecido:
                achadas.append(t)
        return sorted(achadas, key=lambda t: t.get("criada", ""), reverse=True)[:3]

    # ------------------------------------------------------------ aprender com as correções
    def _aprender_tipo(self, titulo: str, tipo: str) -> None:
        """A pessoa trocou o tipo: as palavras do título passam a puxar aquele tipo."""
        if not tipo or tipo not in catalogo.tipos():
            return
        palavras = [p for p in normalizar(titulo).lower().split() if len(p) >= 4 and p not in PALAVRAS_SEM_LICAO]
        for p in palavras[:4]:
            if not catalogo.achar(p)[0]:
                self.aprendizado.setdefault("tipos", {})[p] = tipo
        self._gravar_aprendizado()

    def _aprender_responsavel(self, cliente: str, responsavel: str) -> None:
        if cliente and responsavel:
            self.aprendizado.setdefault("responsaveis", {})[cliente] = responsavel
            self._gravar_aprendizado()

    def _aprender_lista(self, cliente: str, tipo: str, lista_id: str) -> None:
        if (cliente or tipo) and self.lista(lista_id):
            self.aprendizado.setdefault("listas", {})[f"{cliente}|{tipo}"] = lista_id
            self._gravar_aprendizado()

    def aprender_remetente(self, chave: str, codigo: str) -> None:
        chave, codigo = (chave or "").strip().lower(), chave_codigo(codigo)
        if chave and codigo:
            self.aprendizado.setdefault("remetentes", {})[chave] = codigo
            self._gravar_aprendizado()

    # ------------------------------------------------------------ espaços
    def espaco(self, eid: str) -> dict | None:
        return next((e for e in self.espacos if e["id"] == eid), None)

    def criar_espaco(self, nome: str, cor: str = "", prefixo: str = "") -> dict:
        with self.tranca:
            e = {"id": novo_id("e"), "nome": nome.strip() or "Novo espaço",
                 "cor": cor or CORES_ESPACO[len(self.espacos) % len(CORES_ESPACO)],
                 "ordem": len(self.espacos) + 1, "contador": 0}
            e["prefixo"] = self._validar_prefixo(prefixo) or self._prefixo_livre(e["nome"])
            self.espacos.append(e)
            self._gravar_espacos()
            return e

    def _validar_prefixo(self, prefixo: str, ignorar: str = "") -> str:
        p = re.sub(r"[^A-Z0-9]", "", normalizar(prefixo or ""))[:6]
        if not p:
            return ""
        if any(e.get("prefixo") == p and e["id"] != ignorar for e in self.espacos):
            raise ValueError(f"o prefixo {p} já é de outro espaço")
        return p

    def editar_espaco(self, eid: str, campos: dict) -> dict:
        with self.tranca:
            e = self.espaco(eid)
            if not e:
                raise KeyError("espaço não existe")
            for chave in ("nome", "cor", "ordem"):
                if chave in campos:
                    e[chave] = campos[chave]
            if campos.get("prefixo"):
                novo = self._validar_prefixo(campos["prefixo"], ignorar=eid)
                if novo and novo != e["prefixo"]:
                    velho = e["prefixo"]
                    e["prefixo"] = novo
                    # as chaves antigas acompanham: EQP-12 vira FIS-12
                    minhas = {l["id"] for l in self.listas if l["espaco"] == eid}
                    for t in self.tarefas.values():
                        if t["lista"] in minhas and t.get("chave", "").startswith(velho + "-"):
                            t["chave"] = novo + t["chave"][len(velho):]
                            self._gravar_tarefa(t, snapshot=False, subir=False)
            self._gravar_espacos()
            return e

    def apagar_espaco(self, eid: str) -> None:
        with self.tranca:
            if any(l["espaco"] == eid for l in self.listas):
                raise ValueError("o espaço ainda tem listas; apague ou mova as listas antes")
            self.espacos = [e for e in self.espacos if e["id"] != eid]
            self._gravar_espacos()

    def _gravar_espacos(self, subir: bool = True) -> None:
        self.espacos.sort(key=lambda e: e.get("ordem", 0))
        self.armazem.gravar_colecao("espacos", self.espacos)
        if subir:
            self._subir_versao()

    def _proxima_chave(self, lista_id: str) -> str:
        l = self.lista(lista_id)
        e = self.espaco(l["espaco"]) if l else None
        if e is None:
            return ""
        e["contador"] = int(e.get("contador", 0)) + 1
        self._gravar_espacos(subir=False)
        return f"{e['prefixo']}-{e['contador']}"

    # ------------------------------------------------------------ listas
    def lista(self, lid: str) -> dict | None:
        return next((l for l in self.listas if l["id"] == lid), None)

    def criar_lista(self, espaco_id: str, nome: str, status=None, campos=None, automacoes=None) -> dict:
        with self.tranca:
            if not self.espaco(espaco_id):
                raise KeyError("espaço não existe")
            l = {"id": novo_id("l"), "espaco": espaco_id, "nome": nome.strip() or "Nova lista",
                 "ordem": len([x for x in self.listas if x["espaco"] == espaco_id]) + 1,
                 "status": [dict(s) for s in (status or STATUS_PADRAO)],
                 "campos": [dict(c) for c in (campos or [])], "visoes": [],
                 "automacoes": [dict(a) for a in (automacoes or [])]}
            self.listas.append(l)
            self._gravar_listas()
            return l

    def editar_lista(self, lid: str, campos: dict) -> dict:
        with self.tranca:
            l = self.lista(lid)
            if not l:
                raise KeyError("lista não existe")
            for chave in ("nome", "ordem", "espaco"):
                if chave in campos:
                    l[chave] = campos[chave]
            if "status" in campos:
                self._trocar_status(l, campos["status"])
            if "campos" in campos:
                l["campos"] = self._validar_campos(campos["campos"])
            if "visoes" in campos:
                l["visoes"] = [self._validar_visao(v) for v in campos["visoes"]]
            if "automacoes" in campos:
                l["automacoes"] = [self._validar_automacao(a) for a in campos["automacoes"]]
            self._gravar_listas()
            return l

    def _trocar_status(self, l: dict, novos_brutos: list) -> None:
        novos = []
        for s in novos_brutos:
            sid = s.get("id") or _id_curto(s.get("nome", ""), "s")
            novos.append({"id": sid, "nome": s.get("nome", sid), "cor": s.get("cor", "#B4B2A9"),
                          "tipo": s.get("tipo") if s.get("tipo") in TIPOS_DE_STATUS else "aberto"})
        if not any(s["tipo"] == "feito" for s in novos):
            raise ValueError("a lista precisa de pelo menos um status do tipo 'feito'")
        ids_antigos = {s["id"] for s in l["status"]}
        ids_novos = {s["id"] for s in novos}
        primeiro = novos[0]["id"]
        for t in self.tarefas.values():
            if t["lista"] == l["id"] and t["status"] in ids_antigos - ids_novos:
                t["status"] = primeiro
                self._gravar_tarefa(t)
        l["status"] = novos

    def _validar_campos(self, brutos: list) -> list:
        saida, vistos = [], set()
        for c in brutos:
            cid = c.get("id") or _id_curto(c.get("nome", ""), "c")
            if cid in vistos:
                cid = cid + novo_id()[-3:]
            vistos.add(cid)
            tipo = c.get("tipo") if c.get("tipo") in TIPOS_DE_CAMPO else "texto"
            campo = {"id": cid, "nome": c.get("nome", cid).strip() or cid, "tipo": tipo}
            if tipo == "selecao":
                campo["opcoes"] = [str(o).strip() for o in c.get("opcoes", []) if str(o).strip()]
            if c.get("no_cartao"):
                campo["no_cartao"] = True
            saida.append(campo)
        return saida

    def _validar_visao(self, v: dict) -> dict:
        return {"id": v.get("id") or novo_id("v"), "nome": (v.get("nome") or "Visão").strip(),
                "tipo": v.get("tipo") if v.get("tipo") in ("lista", "quadro", "calendario") else "lista",
                "agrupar": v.get("agrupar", "status"), "filtro": v.get("filtro", ""),
                "ordenar": v.get("ordenar"), "mostrar_feitas": bool(v.get("mostrar_feitas")),
                "colunas_ocultas": list(v.get("colunas_ocultas", []))}

    def _validar_automacao(self, a: dict) -> dict:
        quando = a.get("quando") or {}
        entao = [x for x in (a.get("entao") or []) if x.get("acao") in ACOES]
        if quando.get("evento") not in EVENTOS or not entao:
            raise ValueError("automação precisa de um 'quando' conhecido e pelo menos um 'então'")
        return {"id": a.get("id") or novo_id("a"), "nome": a.get("nome", ""),
                "quando": {"evento": quando["evento"], "valor": quando.get("valor", "")},
                "entao": [{"acao": x["acao"], "valor": x.get("valor", "")} for x in entao],
                "ligada": a.get("ligada", True) is not False}

    def apagar_lista(self, lid: str) -> None:
        with self.tranca:
            for t in [t for t in self.tarefas.values() if t["lista"] == lid]:
                self._lixeira(t["id"])
            self.listas = [l for l in self.listas if l["id"] != lid]
            self._gravar_listas()

    def _gravar_listas(self, subir: bool = True) -> None:
        self.listas.sort(key=lambda l: (l.get("espaco", ""), l.get("ordem", 0)))
        self.armazem.gravar_colecao("listas", self.listas)
        if subir:
            self._subir_versao()

    def _status(self, lista_id: str, status_id: str) -> dict | None:
        l = self.lista(lista_id)
        if not l:
            return None
        return next((s for s in l["status"] if s["id"] == status_id), None)

    # ------------------------------------------------------------ modelos de lista
    def salvar_modelo(self, lista_id: str, nome: str) -> dict:
        """A lista vira modelo: status, campos, automações e as tarefas como esqueleto."""
        with self.tranca:
            l = self.lista(lista_id)
            if not l:
                raise KeyError("lista não existe")
            tarefas = []
            for t in sorted((t for t in self.tarefas.values() if t["lista"] == lista_id and not t.get("pai")),
                            key=lambda x: (x["status"], x["ordem"])):
                item = {"titulo": t["titulo"], "tipo": t.get("tipo", ""), "prioridade": t.get("prioridade", "normal"),
                        "responsavel": t.get("responsavel", ""), "checklist": [c["texto"] for c in t.get("checklist", [])],
                        "campos": dict(t.get("campos", {})), "por_cliente": False, "depende_da_anterior": False}
                if t.get("cliente"):
                    item["por_cliente"] = True
                if t.get("prazo"):
                    item["prazo"] = {"dia": int(t["prazo"][8:10])}
                tarefas.append(item)
            m = {"id": novo_id("m"), "nome": nome.strip() or l["nome"], "status": [dict(s) for s in l["status"]],
                 "campos": [dict(c) for c in l.get("campos", [])], "automacoes": [dict(a) for a in l.get("automacoes", [])],
                 "tarefas": tarefas, "criado": agora()}
            self.modelos.append(m)
            self._gravar_modelos()
            return m

    def editar_modelo(self, mid: str, campos: dict) -> dict:
        with self.tranca:
            m = next((x for x in self.modelos if x["id"] == mid), None)
            if not m:
                raise KeyError("modelo não existe")
            for chave in ("nome", "status", "campos", "automacoes", "tarefas"):
                if chave in campos:
                    m[chave] = campos[chave]
            self._gravar_modelos()
            return m

    def apagar_modelo(self, mid: str) -> None:
        with self.tranca:
            self.modelos = [x for x in self.modelos if x["id"] != mid]
            self._gravar_modelos()

    def _gravar_modelos(self) -> None:
        self.armazem.gravar_colecao("modelos", self.modelos)
        self._subir_versao()

    def criar_lista_de_modelo(self, mid: str, espaco_id: str, nome: str, competencia: str = "",
                              clientes: list | None = None, pessoa: str = "") -> dict:
        """Nova lista a partir do modelo. `competencia` = MM-AAAA dá o prazo das tarefas mensais;
        `clientes` = códigos para as tarefas marcadas 'por cliente' (uma por cliente)."""
        with self.tranca:
            m = next((x for x in self.modelos if x["id"] == mid), None)
            if not m:
                raise KeyError("modelo não existe")
            l = self.criar_lista(espaco_id, nome or m["nome"], m.get("status"), m.get("campos"), m.get("automacoes"))
            ano, mes = self._competencia(competencia)
            anterior_por_grupo: dict = {}
            for item in m.get("tarefas", []):
                alvos = [self.indice.achar(c) for c in (clientes or [])] if item.get("por_cliente") else [None]
                alvos = [c for c in alvos if c is not None] if item.get("por_cliente") else alvos
                for c in alvos:
                    t = self._tarefa_do_modelo(l, item, c, ano, mes, pessoa)
                    grupo = c.codigo if c else "_"
                    if item.get("depende_da_anterior") and anterior_por_grupo.get(grupo):
                        t["ligacoes"] = [{"tipo": "depende", "alvo": anterior_por_grupo[grupo]}]
                    anterior_por_grupo[grupo] = t["id"]
                    self.tarefas[t["id"]] = t
                    self._gravar_tarefa(t, snapshot=False, subir=False)
            self._subir_versao()
            return l

    def _competencia(self, texto: str) -> tuple:
        numeros = re.sub(r"[^0-9]", "", texto or "")
        hoje = dt.date.today()
        if len(numeros) == 6:
            a, b = int(numeros[:2]), int(numeros[2:])
            return (b, a) if 1 <= a <= 12 else (int(numeros[:4]), int(numeros[4:]))
        return hoje.year, hoje.month

    def _tarefa_do_modelo(self, l: dict, item: dict, c, ano: int, mes: int, pessoa: str) -> dict:
        prazo = None
        regra = item.get("prazo") or {}
        if regra.get("obrigacao"):
            o = next((x for x in calendario.obrigacoes() if normalizar(x["nome"]) == normalizar(regra["obrigacao"])), None)
            if o:
                prazo = calendario.vencimento(o, ano, mes).isoformat()
        elif regra.get("dia"):
            ultimo = (dt.date(ano + (mes == 12), (mes % 12) + 1, 1) - dt.timedelta(days=1)).day
            prazo = calendario.util_anterior(dt.date(ano, mes, min(int(regra["dia"]), ultimo))).isoformat()
        elif regra.get("uteis_apos") is not None:
            prazo = calendario.somar_uteis(dt.date.today(), int(regra["uteis_apos"])).isoformat()
        titulo = item["titulo"]
        if c is not None and "{cliente}" not in titulo:
            titulo = f"{c.codigo} {c.nome.split(' ')[0].title()} — {titulo}"
        titulo = titulo.replace("{cliente}", c.nome if c else "").replace("{mes}", f"{mes:02d}/{ano}")
        t = {
            "id": novo_id(), "chave": self._proxima_chave(l["id"]), "lista": l["id"], "titulo": titulo,
            "status": l["status"][0]["id"], "prioridade": item.get("prioridade", "normal"),
            "motivo_prioridade": "do modelo", "prazo": prazo, "cliente": c.codigo if c else "",
            "cliente_nome": c.nome if c else "", "tipo": item.get("tipo", ""),
            "responsavel": item.get("responsavel") or pessoa, "responsaveis": [item.get("responsavel") or pessoa] if (item.get("responsavel") or pessoa) else [],
            "criada_por": pessoa, "criada": agora(),
            "atualizada": agora(), "pai": "", "ordem": self._proxima_ordem(l["id"], l["status"][0]["id"]),
            "descricao": item.get("descricao", ""), "checklist": [{"texto": x, "feito": False} for x in item.get("checklist", [])],
            "etiquetas": [], "ligacoes": [], "aguardando_desde": None, "concluida_em": None,
            "texto_original": "", "origem": "", "recorrencia": item.get("recorrencia", ""),
            "campos": dict(item.get("campos", {})), "lembrete": None,
        }
        return t

    # ------------------------------------------------------------ tarefas
    def _previa(self, e) -> dict:
        prioridade, motivo = self._prioridade(e)
        cliente = e.cliente.codigo if e.cliente else ""
        return {
            "titulo": e.titulo,
            "cliente": {"codigo": e.cliente.codigo, "nome": e.cliente.nome} if e.cliente else None,
            "candidatos": [{"codigo": c.codigo, "nome": c.nome} for c in e.candidatos_cliente],
            "cliente_trecho": e.cliente_trecho, "cliente_motivo": e.cliente_motivo,
            "tipo": e.tipo, "tipo_nome": catalogo.nome(e.tipo) if e.tipo else "",
            "prazo": e.prazo.isoformat() if e.prazo else None, "prazo_motivo": e.prazo_motivo,
            "prioridade": prioridade, "motivo_prioridade": motivo,
            "pessoa": e.pessoa or self.aprendizado.get("responsaveis", {}).get(cliente, ""),
            "pessoas": list(e.pessoas) if e.pessoas else ([self.aprendizado["responsaveis"][cliente]] if self.aprendizado.get("responsaveis", {}).get(cliente) else []),
            "etiquetas": e.etiquetas, "checklist": e.checklist,
            "origem": e.origem, "e_informacao": e.e_informacao, "recorrencia": e.recorrencia,
            "avisar": e.avisar, "extraidos": e.extraidos, "avisos": e.avisos,
            "hora": e.hora, "pessoal": e.pessoal, "pessoal_motivo": e.pessoal_motivo, "rodizio": e.rodizio,
            "duplicatas": [{"id": t["id"], "chave": t.get("chave", ""), "titulo": t["titulo"], "status": t["status"],
                            "criada": t.get("criada", "")} for t in self.duplicatas(cliente, e.tipo, e.titulo)],
        }

    def entender_texto(self, texto: str, pessoas=()) -> dict:
        """A prévia das fichas. Linha que são várias demandas devolve as outras em `outras`."""
        pedacos = separar(texto, self.indice)
        previas = [self._previa(entender(p, self.indice, pessoas=pessoas, aprendizado=self.aprendizado)) for p in pedacos]
        saida = dict(previas[0])
        saida["outras"] = previas[1:]
        saida["pedacos"] = pedacos
        return saida

    def _conversa(self, texto: str, pessoas=(), pessoa: str = "", lados: dict | None = None, juntar: bool | None = None):
        return mod_conversa.interpretar(texto, self.indice, pessoas=pessoas, aprendizado=self.aprendizado, eu=pessoa,
                                        equipe=getattr(self, "equipe", []), lados=lados, juntar=juntar)

    def entender_mensagem(self, texto: str, pessoas=(), pessoa: str = "", lados: dict | None = None,
                          juntar: bool | None = None) -> dict:
        """A prévia de uma conversa colada: quem falou, o que pediu, o que você combinou, as tarefas."""
        c = self._conversa(texto, pessoas, pessoa, lados, juntar)
        pedidos = []
        for ta in c.tarefas:
            p = self._previa(ta.entendimento)
            p["titulo"] = ta.titulo or p["titulo"]
            p["texto"] = ta.texto
            p["checklist"] = [{"texto": it.texto, "feito": it.feito, "origem": it.origem, "motivo": it.motivo} for it in ta.itens]
            p["status_tipo"], p["status_motivo"] = c.status_tipo, c.status_motivo
            p["prioridade_conversa"] = c.prioridade          # só quando alguém pediu com urgência; senão o app decide
            if c.prioridade:
                p["prioridade"], p["motivo_prioridade"] = c.prioridade, c.prioridade_motivo
            p["pessoa_motivo"] = c.pessoa_motivo if ta.entendimento.pessoa == c.pessoa else ""
            pedidos.append(p)
        return {
            "formato": c.formato, "remetente": c.remetente_nome, "email": c.remetente_email,
            "telefone": c.remetente_telefone, "quando": c.quando, "assunto": c.assunto,
            "cliente": {"codigo": c.cliente.codigo, "nome": c.cliente.nome} if c.cliente else None,
            "cliente_motivo": c.cliente_motivo,
            "candidatos": [{"codigo": x.codigo, "nome": x.nome} for x in c.candidatos],
            "turnos": [{"nome": t.nome, "lado": t.lado, "lado_motivo": t.lado_motivo, "quando": t.quando,
                        "texto": t.texto or ("(anexo)" if t.anexo else ""), "anexo": t.anexo} for t in c.turnos],
            "so_minha": c.so_minha,
            "status_tipo": c.status_tipo, "status_motivo": c.status_motivo,
            "prazo": c.prazo.isoformat() if c.prazo else None, "prazo_motivo": c.prazo_motivo,
            "pessoa": c.pessoa, "pessoa_motivo": c.pessoa_motivo,
            "prioridade": c.prioridade, "prioridade_motivo": c.prioridade_motivo,
            "recorrencia": c.recorrencia, "avisar": c.avisar,
            "juntar": c.juntar, "pode_juntar": c.pode_juntar, "pode_separar": c.pode_separar,
            "pedidos": pedidos,
            "descricao": mod_conversa.descricao(c),
            "avisos": c.avisos,
        }

    def aprender_lado(self, nome: str, lado: str) -> None:
        """"Maria é cliente", "Bruno é da equipe": vale na próxima conversa colada."""
        chave = normalizar(nome).lower()
        if chave and lado in ("cliente", "equipe"):
            self.aprendizado.setdefault("lados", {})[chave] = lado
            self._gravar_aprendizado()

    def _prioridade(self, e) -> tuple:
        codigo = e.cliente.codigo if e.cliente else ""
        abertas = sum(1 for t in self.tarefas.values() if t.get("cliente") == codigo and not self._feita(t))
        aprendido = self.aprendizado.get("padroes", {}).get(f"{codigo}|{e.tipo}", {}).get("prioridade", "")
        if aprendido in PRIORIDADES:
            return aprendido, "como você escolheu da última vez"
        nivel, motivo = mod_importancia.avaliar(e.normalizado, e.tipo, e.prazo, abertas)
        alvo = " " + e.normalizado + " "
        if any(p in alvo for p in (" urgente ", " pra ontem ", " para ontem ", " fiscalizacao ", " intimacao ")) \
                and nivel == "alta":
            return "urgente", motivo
        return {"alta": "alta", "media": "normal", "baixa": "baixa"}[nivel], motivo

    def criar_varias(self, lista_id: str, texto: str, pessoa: str = "", ajustes: dict | None = None,
                     pessoas=()) -> list:
        """A linha única, que pode ser várias demandas. Os ajustes valem para a primeira."""
        ajustes = ajustes or {}
        pedacos = [texto] if ajustes.get("varias") is False else separar(texto, self.indice)
        criadas = [self.criar_tarefa(lista_id, pedacos[0], pessoa, ajustes, pessoas)]
        for p in pedacos[1:]:
            herdados = {k: v for k, v in ajustes.items() if k in ("cliente", "responsavel", "status", "triar", "pai")}
            criadas.append(self.criar_tarefa(lista_id, p, pessoa, herdados, pessoas))
        if len(criadas) > 1:
            for t in criadas[1:]:
                self.editar_tarefa(t["id"], {"ligacoes": [{"tipo": "relacionada", "alvo": criadas[0]["id"]}]})
        return criadas

    def criar_de_mensagem(self, lista_id: str, texto: str, pessoa: str = "", ajustes: dict | None = None,
                          pessoas=()) -> list:
        """Conversa colada → uma tarefa por pedido (com checklist, status e prazo combinados), a conversa na descrição.

        `ajustes.pedidos`: o que a prévia mostrou e a pessoa confirmou — cada um é um dict
        {titulo, texto, checklist, status_tipo, prazo, responsavel, prioridade, tipo} ou só o título.
        `ajustes.lados`: {nome: "cliente"|"equipe"} corrigido na tela (e aprendido). `ajustes.juntar`: True/False.
        """
        ajustes = dict(ajustes or {})
        lados = ajustes.pop("lados", None) or {}
        for nome, lado in lados.items():
            if not str(nome).startswith("#"):          # "#2" é fala sem nome, marcada pela posição: não há o que aprender
                self.aprender_lado(nome, lado)
        c = self._conversa(texto, pessoas, pessoa, lados, ajustes.pop("juntar", None))
        cliente = ajustes.get("cliente") or (c.cliente.codigo if c.cliente else "")
        if ajustes.get("cliente"):
            # e-mail, telefone, CNPJ e o nome como aparece no chat ("Daniel"): da próxima vez já sabe quem é
            for chave in (c.remetente_email, c.remetente_telefone, c.cnpj, normalizar(c.remetente_nome).lower()):
                if chave and chave not in ("cliente", "voce", "eu"):
                    self.aprender_remetente(chave, ajustes["cliente"])
        descricao = mod_conversa.descricao(c)
        pedidos = ajustes.pop("pedidos", None)
        if not pedidos:
            pedidos = [{"titulo": ta.titulo, "texto": ta.texto,
                        "cliente": ta.entendimento.cliente.codigo if ta.entendimento.cliente else "",
                        "extraidos": dict(ta.entendimento.extraidos or {}),
                        "checklist": [{"texto": it.texto, "feito": it.feito} for it in ta.itens],
                        "status_tipo": c.status_tipo, "prazo": ta.entendimento.prazo.isoformat() if ta.entendimento.prazo else None,
                        "responsavel": ta.entendimento.pessoa, "prioridade": c.prioridade, "tipo": ta.entendimento.tipo,
                        "recorrencia": ta.entendimento.recorrencia, "avisar": ta.entendimento.avisar}
                       for ta in c.tarefas] or [{"titulo": "", "texto": texto.strip()[:200]}]
        por_titulo = {ta.titulo: ta for ta in c.tarefas}
        criadas = []
        for i, pedido in enumerate(pedidos):
            if isinstance(pedido, str):
                ta = por_titulo.get(pedido)
                pedido = {"titulo": pedido, "texto": ta.texto if ta else pedido,
                          "checklist": [{"texto": it.texto, "feito": it.feito} for it in ta.itens] if ta else None,
                          "status_tipo": c.status_tipo if ta else None}
            aj = dict(ajustes) if i == 0 else {k: v for k, v in ajustes.items() if k in ("cliente", "responsavel", "status", "triar")}
            # o cliente: o que a pessoa escolheu > o da linha (só você falou: cada linha tem o seu) > o da conversa.
            # Sem nenhum, fica explicitamente vazio — a linha do pedido não pode chutar cliente por palavra solta.
            aj["cliente"] = ajustes.get("cliente") or pedido.get("cliente") or cliente or ""
            aj.setdefault("triar", True)
            aj["origem"] = c.formato if c.formato in ("whatsapp", "email", "chat") else aj.get("origem", "")
            if pedido.get("extraidos"):
                aj["extraidos"] = pedido["extraidos"]           # valor somado das fichas de nota, competência…
            aj["descricao"] = descricao
            if pedido.get("titulo"):
                aj["titulo"] = pedido["titulo"]
            if pedido.get("checklist") is not None:
                aj["checklist"] = pedido["checklist"]
            if pedido.get("status_tipo") and "status" not in aj:
                aj["status_tipo"] = pedido["status_tipo"]
            for chave in ("prazo", "responsavel", "tipo", "recorrencia", "lembrete"):
                if chave in pedido and pedido[chave] not in (None, "") and chave not in aj:
                    aj[chave] = pedido[chave]
            if pedido.get("prioridade_escolhida"):
                aj["prioridade"] = pedido["prioridade_escolhida"]        # escolha sua: o app aprende
            elif pedido.get("prioridade"):
                aj["prioridade_sugerida"] = pedido["prioridade"]        # sugestão da conversa: não aprende
            if pedido.get("avisar"):
                aj["avisar"] = True
            linha = pedido.get("texto") or pedido.get("titulo") or texto.strip()[:200]
            if cliente and not re.search(r"\b" + re.escape(cliente) + r"\b", normalizar(linha)):
                linha = f"{cliente} {linha}"
            criadas.append(self.criar_tarefa(lista_id, linha, pessoa, aj, pessoas))
        for t in criadas[1:]:
            self.editar_tarefa(t["id"], {"ligacoes": [{"tipo": "relacionada", "alvo": criadas[0]["id"]}]})
        return criadas

    def criar_tarefa(self, lista_id: str, texto: str, pessoa: str = "", ajustes: dict | None = None,
                     pessoas=()) -> dict:
        ajustes = ajustes or {}
        with self.tranca:
            l = self.lista(lista_id)
            if not l:
                raise KeyError("lista não existe")
            e = entender(texto, self.indice, pessoas=pessoas, aprendizado=self.aprendizado)
            if ajustes.get("cliente") and e.cliente is None and e.cliente_trecho:
                self.aprender_apelido(e.cliente_trecho, ajustes["cliente"])
                e = entender(texto, self.indice, pessoas=pessoas, aprendizado=self.aprendizado)
            prioridade, motivo = self._prioridade(e)
            cliente = self.indice.achar(ajustes["cliente"]) if ajustes.get("cliente") else e.cliente
            if "cliente" in ajustes and not ajustes["cliente"]:
                cliente = None
            tipo = ajustes.get("tipo", e.tipo) if "tipo" in ajustes else e.tipo
            prazo = ajustes.get("prazo") if "prazo" in ajustes else (e.prazo.isoformat() if e.prazo else None)
            checklist = e.checklist if (e.checklist and e.checklist != catalogo.checklist(e.tipo)) \
                else catalogo.checklist(tipo)
            feitos = set()
            if ajustes.get("checklist") is not None:
                # a conversa colada já traz o checklist destrinchado (e o que o cliente já mandou vem marcado)
                checklist = []
                for item in ajustes["checklist"]:
                    txt = (item.get("texto") if isinstance(item, dict) else str(item)).strip()
                    if txt:
                        checklist.append(txt)
                        if isinstance(item, dict) and item.get("feito"):
                            feitos.add(txt)
            if "prioridade" in ajustes and ajustes["prioridade"] in PRIORIDADES:
                prioridade, motivo = ajustes["prioridade"], "você escolheu"
                if cliente or tipo:
                    self.aprendizado.setdefault("padroes", {})[f"{cliente.codigo if cliente else ''}|{tipo}"] = \
                        {"prioridade": prioridade}
                    self._gravar_aprendizado()
            elif ajustes.get("prioridade_sugerida") in PRIORIDADES and motivo != "como você escolheu da última vez":
                prioridade, motivo = ajustes["prioridade_sugerida"], "pela conversa (alguém pediu com urgência)"
            status = ajustes.get("status") or l["status"][0]["id"]
            pai = ajustes.get("pai") if ajustes.get("pai") in self.tarefas else ""
            codigo_cliente = cliente.codigo if cliente else ""
            if "responsaveis" in ajustes:
                responsaveis = self._nomes_da_equipe(ajustes["responsaveis"])
            elif "responsavel" in ajustes:
                responsaveis = self._nomes_da_equipe([ajustes["responsavel"]] if ajustes["responsavel"] else [])
            else:
                try:
                    responsaveis = self._nomes_da_equipe(e.pessoas or [self.aprendizado.get("responsaveis", {}).get(codigo_cliente) or pessoa])
                except ValueError:
                    responsaveis = self._nomes_da_equipe([pessoa]) if pessoa in getattr(self, "equipe", []) or not getattr(self, "equipe", []) else []
            responsavel = responsaveis[0] if responsaveis else ""
            campos = dict(ajustes.get("campos") or {})
            extraidos_tarefa = dict(e.extraidos or {})
            extraidos_tarefa.update(ajustes.get("extraidos") or {})      # a conversa colada soma os valores das notas
            for chave_campo, valor in extraidos_tarefa.items():
                # o que a linha trouxe cai no campo da lista de mesmo id, se ele existir
                if any(c["id"] == chave_campo for c in l.get("campos", [])) and chave_campo not in campos:
                    campos[chave_campo] = valor
            t = {
                "id": novo_id(), "chave": "", "lista": lista_id, "titulo": (ajustes.get("titulo") or "").strip()[:160] or e.titulo or texto.strip()[:120],
                "status": status, "prioridade": prioridade, "motivo_prioridade": motivo,
                "prazo": prazo, "cliente": codigo_cliente,
                "cliente_nome": cliente.nome if cliente else "", "tipo": tipo,
                "responsavel": responsavel, "responsaveis": responsaveis, "criada_por": pessoa,
                "criada": agora(), "atualizada": agora(), "pai": pai,
                "ordem": 1.0,
                "descricao": ajustes.get("descricao") or e.notas, "checklist": [{"texto": c, "feito": c in feitos} for c in checklist],
                "etiquetas": sorted(set(list(e.etiquetas) + [str(x).strip().lstrip("#").lower() for x in (ajustes.get("etiquetas") or []) if str(x).strip()])),
                "ligacoes": [], "aguardando_desde": None, "atrasou_em": None, "comentarios": [], "anexos": [],
                "concluida_em": None, "texto_original": texto, "origem": ajustes.get("origem") or e.origem,
                "recorrencia": ajustes.get("recorrencia", e.recorrencia), "campos": campos,
                "lembrete": None, "extraidos": extraidos_tarefa,
            }
            if ajustes.get("lembrete"):
                t["lembrete"] = ajustes["lembrete"]
            elif e.avisar or ajustes.get("avisar"):
                # "me avisar": balão no dia do prazo (ou amanhã, se não há prazo)
                t["lembrete"] = prazo or (dt.date.today() + dt.timedelta(days=1)).isoformat()
            # "me avisar a cada 30 min": no dia do lembrete, repete nessa cadência
            cada = ajustes.get("lembrete_cada") if "lembrete_cada" in ajustes else e.lembrete_cada
            try:
                t["lembrete_cada"] = int(cada) if cada else None
            except (TypeError, ValueError):
                t["lembrete_cada"] = None
            # "às 15h" → lembrete com hora; "rodízio" → a ordem de quem faz a cada vez
            hora = ajustes.get("lembrete_hora") if "lembrete_hora" in ajustes else e.hora
            t["lembrete_hora"] = hora if re.fullmatch(r"\d{2}:\d{2}", str(hora or "")) else ""
            if t["lembrete_hora"] and not t["lembrete"]:
                t["lembrete"] = prazo or dt.date.today().isoformat()
            # o motivo do lembrete ("cobrar o cliente") vai no balão
            t["lembrete_motivo"] = str(ajustes.get("lembrete_motivo") or "")[:80]
            rodizio = ajustes.get("rodizio") if "rodizio" in ajustes else (list(getattr(self, "equipe", [])) if e.rodizio else [])
            if rodizio is True:
                rodizio = list(getattr(self, "equipe", []))
            try:
                t["rodizio"] = self._nomes_da_equipe(rodizio or [])
            except ValueError:
                t["rodizio"] = []
            if t["rodizio"] and not responsaveis:
                t["responsaveis"], t["responsavel"] = [t["rodizio"][0]], t["rodizio"][0]
            # "é pessoal" marcado diferente do que o app adivinhou: aprende as palavras do título
            if "pessoal" in ajustes and bool(ajustes["pessoal"]) != bool(e.pessoal):
                self.aprender_pessoal(e.titulo or texto, bool(ajustes["pessoal"]))
            if "responsavel" in ajustes or "responsaveis" in ajustes:
                t["responsavel_explicito"] = True
            if not pai:
                # a lista: regra de triagem, lista aprendida, a lista em que a pessoa está, ou a Caixa de entrada
                self.triar(t, lista_id, explicita=not ajustes.get("triar"))
                for chave_campo, valor in extraidos_tarefa.items():
                    if any(c["id"] == chave_campo for c in self.lista(t["lista"]).get("campos", [])) and chave_campo not in t["campos"]:
                        t["campos"][chave_campo] = valor
                if not self._status(t["lista"], t["status"]):
                    t["status"] = self.lista(t["lista"])["status"][0]["id"]
            if ajustes.get("status_tipo") in ("aguardando", "feito") and not ajustes.get("status"):
                # a conversa disse: "você pediu ao cliente e ele não mandou" / "você já enviou"
                alvo = next((s for s in self.lista(t["lista"])["status"] if s["tipo"] == ajustes["status_tipo"]), None)
                if alvo:
                    self._aplicar_status(t, alvo["id"])
            t.pop("responsavel_explicito", None)
            t["ordem"] = self._proxima_ordem(t["lista"], t["status"], pai)
            if pai:
                mae = self.tarefas[pai]
                t["lista"] = mae["lista"]
                if not t["cliente"] and mae.get("cliente"):
                    t["cliente"], t["cliente_nome"] = mae["cliente"], mae.get("cliente_nome", "")
                if not t["prazo"]:
                    t["prazo"] = mae.get("prazo")
            t["chave"] = self._proxima_chave(t["lista"])
            self._aplicar_status(t, t["status"])      # t["status"] já passou pela triagem e pelo status sugerido
            # "depende de" / "relacionada" vindos da tela de criação manual
            for lig in (ajustes.get("ligacoes") or []):
                if isinstance(lig, dict) and lig.get("alvo") in self.tarefas and lig.get("tipo") in ("depende", "relacionada"):
                    t["ligacoes"].append({"tipo": lig["tipo"], "alvo": lig["alvo"]})
            self.tarefas[t["id"]] = t
            self._gravar_tarefa(t)
            self._evento(t, "criada", pessoa, para=t["responsaveis"], texto=ajustes.get("origem") or e.origem or "")
            for n in t["responsaveis"]:
                if n != pessoa:
                    self._notificar(n, pessoa, "atribuida", t, f"{pessoa or 'alguém'} te atribuiu {t['chave']}: {t['titulo'][:60]}")
            if self._feita(t):
                self._evento(t, "concluida", pessoa)
            self._automatizar(t, "criada")
            return t

    def _proxima_ordem(self, lista_id: str, status: str, pai: str = "") -> float:
        irmas = [t["ordem"] for t in self.tarefas.values()
                 if t["lista"] == lista_id and t["status"] == status and (t.get("pai") or "") == (pai or "")]
        return (max(irmas) + 1.0) if irmas else 1.0

    def _feita(self, t: dict) -> bool:
        s = self._status(t["lista"], t["status"])
        return bool(s and s["tipo"] == "feito")

    def _aplicar_status(self, t: dict, status_id: str) -> None:
        s = self._status(t["lista"], status_id) or {"tipo": "aberto"}
        t["status"] = status_id
        hoje = dt.date.today().isoformat()
        if s["tipo"] == "aguardando":
            t["aguardando_desde"] = t.get("aguardando_desde") or hoje
        else:
            t["aguardando_desde"] = None
        if s["tipo"] == "feito":
            if not t.get("concluida_em"):
                t["concluida_em"] = agora()
        else:
            t["concluida_em"] = None

    def _depois_de_concluir(self, t: dict) -> None:
        """Feita: recorrente gera a próxima; quem dependia dela e ficou livre é avisado."""
        if t.get("recorrencia"):
            self._renovar(t)
        for outra in list(self.tarefas.values()):
            if any(l.get("tipo") == "depende" and l.get("alvo") == t["id"] for l in outra.get("ligacoes", [])):
                if not self.bloqueios(outra["id"]) and not self._feita(outra):
                    outra["liberada_em"] = agora()
                    self._gravar_tarefa(outra, snapshot=False)
                    self._automatizar(outra, "liberada")

    # ------------------------------------------------------------ responsáveis (vários por tarefa)
    def _nomes_da_equipe(self, nomes) -> list:
        """Nomes limpos e como estão na Equipe. Com Equipe cadastrada, só quem é dela pode receber
        tarefa ("ana" vale por "Ana Souza"); fora dela é erro, para não nascer nome errado."""
        if isinstance(nomes, str):
            nomes = [nomes]
        equipe = list(getattr(self, "equipe", []))
        por_chave = {normalizar(n).lower(): n for n in equipe}
        por_primeiro = {}
        for chave, n in por_chave.items():
            por_primeiro.setdefault(chave.split()[0], n)
        saida = []
        for bruto in nomes or []:
            n = str(bruto or "").strip()
            if not n:
                continue
            chave = normalizar(n).lower()
            if equipe:
                canonico = por_chave.get(chave) or por_primeiro.get(chave.split()[0]) if chave.split() else None
                if not canonico or (chave not in por_chave and len(chave.split()) > 1):
                    raise ValueError(f"“{n}” não está na Equipe do departamento {self.nome} — cadastre em Equipe ⋯ antes de atribuir")
                n = canonico
            if n not in saida:
                saida.append(n)
        return saida

    def _definir_responsaveis(self, t: dict, nomes, explicito: bool = False) -> None:
        t["responsaveis"] = self._nomes_da_equipe(nomes)
        t["responsavel"] = t["responsaveis"][0] if t["responsaveis"] else ""
        if explicito:
            t["responsavel_explicito"] = True

    # ------------------------------------------------------------ eventos (o que aconteceu, quem fez, quando)
    def _evento(self, t: dict, tipo: str, pessoa: str = "", de=None, para=None, texto: str = "") -> None:
        """Uma linha em `eventos.jsonl`: é daqui que saem a Atividade da tarefa e o Histórico do departamento."""
        ev = {"quando": agora(), "tarefa": t.get("id", ""), "chave": t.get("chave", ""), "titulo": t.get("titulo", "")[:80],
              "pessoa": pessoa or "", "tipo": tipo, "de": de, "para": para, "texto": texto}
        self.armazem.evento(ev)

    def eventos(self, desde: str = "", pessoa: str = "", tarefa: str = "", limite: int = 300) -> list:
        """Os eventos mais recentes primeiro. `desde` é data ISO; `pessoa` casa quem fez ou quem é responsável."""
        saida = []
        for ev in self.armazem.eventos():
            if desde and ev.get("quando", "") < desde:
                continue
            if tarefa and ev.get("tarefa") != tarefa:
                continue
            if pessoa:
                t = self.tarefas.get(ev.get("tarefa", ""), {})
                if ev.get("pessoa") != pessoa and pessoa not in (t.get("responsaveis") or []) and ev.get("para") != pessoa:
                    continue
            saida.append(ev)
            if len(saida) >= limite:
                break
        return saida

    # ------------------------------------------------------------ concluir num passo; "é pessoal" aprendido
    def concluir(self, tid: str, pessoa: str = "", reabrir: bool = False) -> dict:
        """Marca com o status 'feito' da lista (ou volta para o primeiro aberto). É o tique da bolha e da linha."""
        t = self.tarefas.get(tid)
        if not t:
            raise KeyError("tarefa não existe")
        l = self.lista(t["lista"]) or {"status": []}
        alvo = next((s for s in l["status"] if s["tipo"] == ("aberto" if reabrir else "feito")), None) or (l["status"][0] if l["status"] else None)
        if not alvo:
            raise ValueError("a lista não tem status de concluído")
        return self.editar_tarefa(tid, {"status": alvo["id"]}, pessoa)

    def adiar_lembrete(self, tid: str, pessoa: str = "", minutos: int = 0, dias_uteis: int = 0, data: str = "",
                       hora: str = "", motivo: str | None = None) -> dict:
        """O "me lembra depois" do balão e o "lembrar de cobrar o cliente": muda a data/hora do lembrete.

        minutos=N → hoje, daqui a N minutos (passa para amanhã 08:30 se estourar 20h);
        dias_uteis=N → N dias úteis a partir de hoje; data/hora explícitas; motivo = "cobrar o cliente"…
        """
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            agora_dt = dt.datetime.now()
            if minutos:
                alvo = agora_dt + dt.timedelta(minutes=int(minutos))
                if alvo.hour >= 20:
                    alvo = dt.datetime.combine(alvo.date() + dt.timedelta(days=1), dt.time(8, 30))
                t["lembrete"], t["lembrete_hora"] = alvo.date().isoformat(), alvo.strftime("%H:%M")
            elif dias_uteis:
                t["lembrete"] = calendario.somar_uteis(agora_dt.date(), int(dias_uteis)).isoformat()
                t["lembrete_hora"] = hora if re.fullmatch(r"\d{2}:\d{2}", str(hora or "")) else ""
            elif data:
                t["lembrete"] = data
                t["lembrete_hora"] = hora if re.fullmatch(r"\d{2}:\d{2}", str(hora or "")) else ""
            else:
                raise ValueError("diga em quantos minutos, dias úteis ou que dia")
            if motivo is not None:
                t["lembrete_motivo"] = str(motivo)[:80]
            self._gravar_tarefa(t, snapshot=False)
            self._evento(t, "lembrete", pessoa, para=f"{t['lembrete']} {t['lembrete_hora']}".strip(), texto=t.get("lembrete_motivo", ""))
            return t

    def aprender_pessoal(self, titulo: str, valor: bool) -> None:
        """As palavras do título (sem as vazias) passam a dizer "é pessoal" / "não é" na próxima vez."""
        from .entender import PALAVRAS_VAZIAS
        palavras = [p for p in normalizar(titulo).lower().split() if len(p) >= 4 and p not in PALAVRAS_VAZIAS and not p.isdigit()]
        if not palavras:
            return
        mapa = self.aprendizado.setdefault("pessoal", {})
        for p in palavras[:4]:
            mapa[p] = bool(valor)
        self._gravar_aprendizado()

    def bloqueios(self, tid: str) -> list:
        t = self.tarefas.get(tid)
        if not t:
            return []
        return [self.tarefas[l["alvo"]] for l in t.get("ligacoes", [])
                if l.get("tipo") == "depende" and l.get("alvo") in self.tarefas and not self._feita(self.tarefas[l["alvo"]])]

    def editar_tarefa(self, tid: str, campos: dict, pessoa: str = "") -> dict:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            antes = {k: t.get(k) for k in ("titulo", "prazo", "responsaveis", "lista", "prioridade", "cliente", "status", "tipo")}
            antes["responsaveis"] = list(antes.get("responsaveis") or [])
            # correções que ensinam: tipo, responsável e lista
            if campos.get("tipo") and campos["tipo"] != t.get("tipo"):
                self._aprender_tipo(t.get("titulo", ""), campos["tipo"])
            if "responsaveis" in campos or "responsavel" in campos:
                novos = campos["responsaveis"] if "responsaveis" in campos else ([campos["responsavel"]] if campos.get("responsavel") else [])
                self._definir_responsaveis(t, novos)
                if t["responsaveis"] and t["responsaveis"] != antes["responsaveis"]:
                    self._aprender_responsavel(t.get("cliente", ""), t["responsavel"])
            if campos.get("lista") and campos["lista"] != t.get("lista"):
                self._aprender_lista(t.get("cliente", ""), t.get("tipo", ""), campos["lista"])
            for chave in ("titulo", "prazo", "tipo", "descricao", "etiquetas",
                          "checklist", "ligacoes", "texto_original", "recorrencia", "pai", "lembrete", "lembrete_cada", "lembrete_hora", "lembrete_motivo"):
                if chave in campos:
                    t[chave] = campos[chave]
            if "lembrete_hora" in campos:
                t["lembrete_hora"] = campos["lembrete_hora"] if re.fullmatch(r"\d{2}:\d{2}", str(campos["lembrete_hora"] or "")) else ""
            if "lembrete_motivo" in campos:
                t["lembrete_motivo"] = str(campos["lembrete_motivo"] or "")[:80]
            if "lembrete" in campos and not campos["lembrete"]:
                t["lembrete_motivo"] = ""          # sem lembrete, não há o que cobrar
            if "rodizio" in campos:
                # a ordem do rodízio: nomes da Equipe (ou qualquer nome, no Pessoal); vazio desliga
                try:
                    t["rodizio"] = self._nomes_da_equipe(campos["rodizio"] or [])
                except ValueError as erro:
                    raise ValueError(f"rodízio: {erro}")
            if "lembrete_cada" in campos:
                try:
                    t["lembrete_cada"] = int(campos["lembrete_cada"]) if campos["lembrete_cada"] else None
                except (TypeError, ValueError):
                    t["lembrete_cada"] = None
            if "campos" in campos and isinstance(campos["campos"], dict):
                t.setdefault("campos", {}).update(campos["campos"])
                t["campos"] = {k: v for k, v in t["campos"].items() if v not in (None, "")}
            if "cliente" in campos:
                c = self.indice.achar(campos["cliente"]) if campos["cliente"] else None
                t["cliente"], t["cliente_nome"] = (c.codigo, c.nome) if c else ("", "")
            if "prioridade" in campos and campos["prioridade"] in PRIORIDADES and campos["prioridade"] != t["prioridade"]:
                t["prioridade"], t["motivo_prioridade"] = campos["prioridade"], "você escolheu"
                self.aprendizado.setdefault("padroes", {})[f"{t.get('cliente', '')}|{t.get('tipo', '')}"] = \
                    {"prioridade": t["prioridade"]}
                self._gravar_aprendizado()
                self._automatizar(t, "prioridade")
            if "lista" in campos and campos["lista"] != t["lista"] and self.lista(campos["lista"]):
                t["lista"] = campos["lista"]
                destino = self.lista(campos["lista"])
                if not self._status(t["lista"], t["status"]):
                    t["status"] = destino["status"][0]["id"]
                t["ordem"] = self._proxima_ordem(t["lista"], t["status"], t.get("pai", ""))
                t["chave"] = self._proxima_chave(t["lista"]) if not t.get("chave", "").startswith(
                    (self.espaco(destino["espaco"]) or {}).get("prefixo", "?") + "-") else t["chave"]
            mudou_status = "status" in campos and campos["status"] != t["status"]
            if mudou_status:
                self._aplicar_status(t, campos["status"])
                t["ordem"] = self._proxima_ordem(t["lista"], t["status"], t.get("pai", ""))
            if "checklist" in campos and t["checklist"] and all(c.get("feito") for c in t["checklist"]):
                self._automatizar(t, "checklist_completo")
            self._gravar_tarefa(t)
            # o que mudou vira evento (é daqui que saem Atividade, Histórico, Concluídas e Atrasadas)
            rotulos = {"titulo": "titulo", "prazo": "prazo", "responsaveis": "responsaveis", "lista": "lista",
                       "prioridade": "prioridade", "cliente": "cliente", "tipo": "tipo"}
            for chave, tipo_ev in rotulos.items():
                if antes.get(chave) != t.get(chave):
                    de, para = antes.get(chave), t.get(chave)
                    if chave == "lista":
                        de, para = (self.lista(de) or {}).get("nome", de), (self.lista(para) or {}).get("nome", para)
                    self._evento(t, tipo_ev, pessoa, de=de, para=para)
                    if chave == "responsaveis":
                        for n in t["responsaveis"]:
                            if n not in antes["responsaveis"] and n != pessoa:
                                self._notificar(n, pessoa, "atribuida", t, f"{pessoa or 'alguém'} te atribuiu {t['chave']}: {t['titulo'][:60]}")
                    elif chave == "prazo":
                        for n in self._interessados(t):
                            if n != pessoa:
                                self._notificar(n, pessoa, "prazo", t, f"{pessoa or 'alguém'} mudou o prazo de {t['chave']} para {para or 'sem prazo'}")
            if mudou_status:
                s_de, s_para = self._status(t["lista"], antes["status"] or ""), self._status(t["lista"], t["status"])
                self._evento(t, "status", pessoa, de=(s_de or {}).get("nome", antes["status"]), para=(s_para or {}).get("nome", t["status"]))
                for n in self._interessados(t):
                    if n != pessoa:
                        self._notificar(n, pessoa, "status", t, f"{pessoa or 'alguém'} moveu {t['chave']} para {(s_para or {}).get('nome', t['status'])}")
                if self._feita(t):
                    self._evento(t, "concluida", pessoa, texto=("no prazo" if not t.get("prazo") or t["prazo"] >= dt.date.today().isoformat() else f"atrasada, prazo era {t['prazo']}"))
                elif (s_de or {}).get("tipo") == "feito":
                    self._evento(t, "reaberta", pessoa)
                self._automatizar(t, "status")
                if self._feita(t):
                    self._depois_de_concluir(t)
            return t

    def mover_tarefa(self, tid: str, status: str | None = None, antes_de: str = "", depois_de: str = "",
                     lista: str | None = None, pessoa: str = "") -> dict:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            if lista and lista != t["lista"] and self.lista(lista):
                self._evento(t, "lista", pessoa, de=(self.lista(t["lista"]) or {}).get("nome"), para=self.lista(lista).get("nome"))
                t["lista"] = lista
            mudou_status = bool(status and status != t["status"])
            if mudou_status:
                s_de = self._status(t["lista"], t["status"])
                era_feita = self._feita(t)
                self._aplicar_status(t, status)
                s_para = self._status(t["lista"], status)
                self._evento(t, "status", pessoa, de=(s_de or {}).get("nome", t["status"]), para=(s_para or {}).get("nome", status))
                for n in self._interessados(t):
                    if n != pessoa:
                        self._notificar(n, pessoa, "status", t, f"{pessoa or 'alguém'} moveu {t['chave']} para {(s_para or {}).get('nome', status)}")
                if self._feita(t):
                    self._evento(t, "concluida", pessoa, texto=("no prazo" if not t.get("prazo") or t["prazo"] >= dt.date.today().isoformat() else f"atrasada, prazo era {t['prazo']}"))
                elif era_feita:
                    self._evento(t, "reaberta", pessoa)
            irmas = sorted((x for x in self.tarefas.values()
                            if x["lista"] == t["lista"] and x["status"] == t["status"]
                            and (x.get("pai") or "") == (t.get("pai") or "") and x["id"] != tid),
                           key=lambda x: x["ordem"])
            ids = [x["id"] for x in irmas]
            pos = len(irmas)
            if antes_de in ids:
                pos = ids.index(antes_de)
            elif depois_de in ids:
                pos = ids.index(depois_de) + 1
            irmas.insert(pos, t)
            for i, x in enumerate(irmas, start=1):
                if x["ordem"] != float(i):
                    x["ordem"] = float(i)
                    if x["id"] != tid:
                        self._gravar_tarefa(x, snapshot=False)
            self._gravar_tarefa(t)
            if mudou_status:
                self._automatizar(t, "status")
                if self._feita(t):
                    self._depois_de_concluir(t)
            return t

    # ------------------------------------------------------------ automações
    def _automatizar(self, t: dict, evento: str, profundidade: int = 0) -> None:
        """Roda as regras da lista para este evento. Três níveis, para regra não chamar regra sem fim."""
        if profundidade > 2:
            return
        l = self.lista(t["lista"])
        if not l:
            return
        for a in l.get("automacoes", []):
            if a.get("ligada") is False or a["quando"]["evento"] != evento:
                continue
            valor = str(a["quando"].get("valor", ""))
            if evento == "status" and valor and valor != t["status"]:
                continue
            if evento == "prioridade" and valor and valor != t["prioridade"]:
                continue
            for acao in a["entao"]:
                self._agir(t, acao, profundidade)

    def _agir(self, t: dict, acao: dict, profundidade: int) -> None:
        tipo, valor = acao["acao"], acao.get("valor", "")
        if tipo == "status" and valor and valor != t["status"] and self._status(t["lista"], valor):
            self._aplicar_status(t, valor)
            self._gravar_tarefa(t, snapshot=False)
            self._automatizar(t, "status", profundidade + 1)
            if self._feita(t):
                self._depois_de_concluir(t)
        elif tipo == "prioridade" and valor in PRIORIDADES and valor != t["prioridade"]:
            t["prioridade"], t["motivo_prioridade"] = valor, "por automação da lista"
            self._gravar_tarefa(t, snapshot=False)
        elif tipo == "responsavel":
            try:
                self._definir_responsaveis(t, [valor])
            except ValueError:
                return
            self._gravar_tarefa(t, snapshot=False)
        elif tipo == "lembrar":
            try:
                dias = int(valor or 0)
            except ValueError:
                dias = 0
            t["lembrete"] = (dt.date.today() + dt.timedelta(days=dias)).isoformat()
            self._gravar_tarefa(t, snapshot=False)
        elif tipo == "mover_lista" and self.lista(valor) and valor != t["lista"]:
            t["lista"] = valor
            if not self._status(valor, t["status"]):
                t["status"] = self.lista(valor)["status"][0]["id"]
            self._gravar_tarefa(t, snapshot=False)
        elif tipo == "prazo_mais":
            try:
                dias = int(valor or 0)
            except ValueError:
                dias = 0
            base = dt.date.fromisoformat(t["prazo"]) if t.get("prazo") else dt.date.today()
            t["prazo"] = (base + dt.timedelta(days=dias)).isoformat()
            self._gravar_tarefa(t, snapshot=False)

    def rodar_prazos(self) -> int:
        """Uma vez por dia por tarefa: dispara 'prazo_passou' nas atrasadas. Chamado no /api/tudo."""
        hoje = dt.date.today().isoformat()
        disparos = 0
        with self.tranca:
            for t in list(self.tarefas.values()):
                if t.get("prazo") and t["prazo"] < hoje and not self._feita(t) and t.get("avisada_atraso") != hoje:
                    t["avisada_atraso"] = hoje
                    if not t.get("atrasou_em"):
                        # a primeira vez que o prazo passou fica guardada: é a visão Atrasadas e o histórico
                        t["atrasou_em"] = hoje
                        self._evento(t, "atrasou", "", de=t["prazo"], para=t["responsaveis"] if t.get("responsaveis") else None)
                        for n in self._interessados(t):
                            self._notificar(n, "", "atrasou", t, f"{t['chave']} passou do prazo ({t['prazo']}): {t['titulo'][:60]}")
                    self._gravar_tarefa(t, snapshot=False, subir=False)
                    self._automatizar(t, "prazo_passou")
                    disparos += 1
        return disparos

    def lembretes(self, pessoa: str = "") -> list:
        hoje = dt.date.today().isoformat()
        return sorted((t for t in self.tarefas.values()
                       if t.get("lembrete") and t["lembrete"] <= hoje and not self._feita(t)
                       and (not pessoa or not t.get("responsaveis") or pessoa in t["responsaveis"])),
                      key=lambda t: t["lembrete"])

    # ------------------------------------------------------------ recorrência
    def _renovar(self, t: dict) -> None:
        """Feita e recorrente: nasce a próxima com o prazo seguinte.

        Formatos: mensal:N (dia N, puxado para o útil anterior), semanal:seg..dom, dias:N (a cada N
        dias a partir do prazo), uteis:N (N dias úteis a partir de hoje).
        """
        partes = (t.get("recorrencia") or "").split(":")
        tipo, valor = partes[0], (partes[1] if len(partes) > 1 else "")
        regra = partes[2] if len(partes) > 2 and partes[2] in ("antes", "depois", "exato") else "antes"
        hoje = dt.date.today()
        base = dt.date.fromisoformat(t["prazo"]) if t.get("prazo") else hoje
        if tipo == "mensal":
            # a próxima é a do mês seguinte ao mês NOMINAL da atual (ou ao de hoje, se ficou para trás)
            dia = int(valor or 1)
            inicio = calendario.mes_seguinte_da_ocorrencia(max(base, hoje) if base < hoje else base, dia, regra)
            prazo = calendario.proxima_mensal(dia, regra, inicio)
        elif tipo == "obrig":
            # "todo mês pós fechamento do simples": a próxima segue o vencimento do mês seguinte
            nome, desloc = valor, int(partes[2]) if len(partes) > 2 and partes[2].lstrip("-").isdigit() else 0
            o = next((x for x in calendario.obrigacoes() if normalizar(x["nome"]) == normalizar(nome)), None)
            ref = max(base, hoje)
            ano, mes = (ref.year + 1, 1) if ref.month == 12 else (ref.year, ref.month + 1)
            venc = calendario.vencimento(o, ano, mes) if o else dt.date(ano, mes, 20)
            prazo = calendario.somar_uteis(venc, desloc) if desloc else venc
        elif tipo == "semanal":
            dias = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}
            alvo = dias.get(valor[:3], 0)
            prazo = max(base, hoje) + dt.timedelta(days=((alvo - max(base, hoje).weekday()) % 7) or 7)
        elif tipo == "uteis":
            prazo = calendario.somar_uteis(hoje, int(valor or 1))
        else:
            prazo = max(base, hoje) + dt.timedelta(days=int(valor or 7))
        l = self.lista(t["lista"])
        primeiro = l["status"][0]["id"] if l else t["status"]
        nova = dict(t, id=novo_id(), chave=self._proxima_chave(t["lista"]), status=primeiro,
                    prazo=prazo.isoformat(), criada=agora(), atualizada=agora(), aguardando_desde=None,
                    concluida_em=None, ligacoes=[], lembrete=None, liberada_em=None, avisada_atraso=None,
                    atrasou_em=None, comentarios=[], anexos=[],
                    checklist=[{"texto": c["texto"], "feito": False} for c in t.get("checklist", [])],
                    motivo_prioridade=f"recorrência de {t.get('chave', '')}")
        if t.get("lembrete") or t.get("lembrete_hora"):
            nova["lembrete"] = prazo.isoformat()        # o lembrete acompanha o prazo novo
        # rodízio — a próxima vez é do próximo da lista ("lavar a máquina de café": Ana → Bruno → Carla → Ana)
        ordem = list(t.get("rodizio") or [])
        if ordem:
            atual = (t.get("responsaveis") or [""])[0]
            i = ordem.index(atual) if atual in ordem else -1
            proximo = ordem[(i + 1) % len(ordem)]
            nova["responsaveis"], nova["responsavel"] = [proximo], proximo
            nova["motivo_prioridade"] = f"rodízio: vez de {proximo} (depois de {atual or '—'})"
        nova["ordem"] = self._proxima_ordem(nova["lista"], primeiro, nova.get("pai", ""))
        self.tarefas[nova["id"]] = nova
        self._gravar_tarefa(nova)
        self._evento(nova, "criada", "", para=nova.get("responsaveis"), texto=f"gerada pela repetição de {t.get('chave', '')}")
        if ordem:
            for n in nova["responsaveis"]:
                self._notificar(n, "", "atribuida", nova, f"Rodízio: é a sua vez de {nova['titulo'][:60]} ({nova['chave']})")

    # ------------------------------------------------------------ apagar e gravar
    def apagar_tarefa(self, tid: str, com_filhas: bool = False) -> None:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                return
            filhas = [x for x in self.tarefas.values() if x.get("pai") == tid]
            for f in filhas:
                if com_filhas:
                    self._lixeira(f["id"])
                else:
                    f["pai"] = t.get("pai", "")
                    self._gravar_tarefa(f, snapshot=False)
            self._lixeira(tid)

    # ------------------------------------------------------------ comentários, anexos, notificações, lixeira, lote
    def _mencoes(self, texto: str) -> list:
        """@nome no comentário → nomes da Equipe (primeiro nome basta)."""
        nomes = []
        for m in re.finditer(r"@([\wÀ-ÿ]+)", texto or ""):
            try:
                for n in self._nomes_da_equipe([m.group(1)]):
                    if n not in nomes:
                        nomes.append(n)
            except ValueError:
                continue
        return nomes

    def comentar(self, tid: str, texto: str, pessoa: str = "") -> dict:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            texto = (texto or "").strip()
            if not texto:
                raise ValueError("escreva alguma coisa")
            mencoes = self._mencoes(texto)
            c = {"id": novo_id(), "quando": agora(), "pessoa": pessoa, "texto": texto[:4000], "mencoes": mencoes}
            t.setdefault("comentarios", []).append(c)
            self._gravar_tarefa(t, snapshot=False)
            self._evento(t, "comentario", pessoa, texto=texto[:120])
            for n in mencoes:
                if n != pessoa:
                    self._notificar(n, pessoa, "mencao", t, f"{pessoa or 'alguém'} te mencionou: “{texto[:80]}”")
            for n in self._interessados(t):
                if n != pessoa and n not in mencoes:
                    self._notificar(n, pessoa, "comentario", t, f"{pessoa or 'alguém'} comentou: “{texto[:80]}”")
            return t

    def apagar_comentario(self, tid: str, cid: str, pessoa: str = "") -> dict:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            c = next((x for x in t.get("comentarios", []) if x["id"] == cid), None)
            if c is None:
                raise KeyError("comentário não existe")
            if pessoa and c.get("pessoa") and c["pessoa"] != pessoa:
                raise PermissionError("só quem escreveu apaga o comentário")
            t["comentarios"] = [x for x in t["comentarios"] if x["id"] != cid]
            self._gravar_tarefa(t, snapshot=False)
            return t

    def anexar(self, tid: str, tipo: str, nome: str, url: str = "", dados_b64: str = "", pessoa: str = "") -> dict:
        """Link (url) ou arquivo (base64, até 20 MB) guardado em dados\\anexos\\<tarefa>\\."""
        import base64
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            nome = re.sub(r"[\\/:*?\"<>|]+", "_", (nome or "").strip())[:120]
            a = {"id": novo_id(), "tipo": "link" if tipo == "link" else "arquivo", "nome": nome, "quando": agora(), "pessoa": pessoa}
            if a["tipo"] == "link":
                url = (url or "").strip()
                if not url:
                    raise ValueError("falta o endereço do link")
                a["url"] = url
                a["nome"] = a["nome"] or url[:80]
            else:
                if not nome:
                    raise ValueError("falta o nome do arquivo")
                try:
                    conteudo = base64.b64decode((dados_b64 or "").split(",")[-1], validate=False)
                except (ValueError, TypeError):
                    raise ValueError("arquivo inválido")
                if len(conteudo) > 20 * 1024 * 1024:
                    raise ValueError("arquivo maior que 20 MB — guarde na pasta do cliente e anexe o link")
                self.armazem.gravar_anexo(tid, a["id"], nome, conteudo)
                a["tamanho"] = len(conteudo)
            t.setdefault("anexos", []).append(a)
            self._gravar_tarefa(t, snapshot=False)
            self._evento(t, "anexo", pessoa, texto=a["nome"])
            return t

    def caminho_do_anexo(self, tid: str, aid: str) -> Path | None:
        t = self.tarefas.get(tid)
        a = next((x for x in (t or {}).get("anexos", []) if x["id"] == aid and x["tipo"] == "arquivo"), None)
        if not a:
            return None
        return self.armazem.caminho_anexo(tid, aid, a["nome"])

    def apagar_anexo(self, tid: str, aid: str) -> dict:
        with self.tranca:
            t = self.tarefas.get(tid)
            if not t:
                raise KeyError("tarefa não existe")
            a = next((x for x in t.get("anexos", []) if x["id"] == aid), None)
            t["anexos"] = [x for x in t.get("anexos", []) if x["id"] != aid]
            if a and a.get("tipo") == "arquivo":
                self.armazem.apagar_anexo(tid, aid, a.get("nome", ""))
            self._gravar_tarefa(t, snapshot=False)
            return t

    def _interessados(self, t: dict) -> list:
        nomes = list(t.get("responsaveis") or [])
        if t.get("criada_por") and t["criada_por"] not in nomes:
            nomes.append(t["criada_por"])
        return nomes

    def _notificar(self, para: str, de: str, tipo: str, t: dict, texto: str) -> None:
        """Uma notificação pessoal em `notificacoes.json` ({pessoa: [...]}, as 200 últimas por pessoa)."""
        if not para:
            return
        if self.pessoal and para != getattr(self, "dono", "") and self.encaminhar_notificacao:
            # espaço Pessoal de outra pessoa: quem mandou a demanda é avisado no espaço DELE
            try:
                self.encaminhar_notificacao(para, de, tipo, t, texto)
            except Exception:
                pass
            return
        try:
            todas = self.armazem.ler_colecao("notificacoes", {})
            if not isinstance(todas, dict):
                todas = {}
            fila = todas.setdefault(para, [])
            fila.append({"id": novo_id(), "quando": agora(), "de": de or "", "tipo": tipo, "tarefa": t.get("id", ""),
                         "chave": t.get("chave", ""), "titulo": (t.get("titulo") or "")[:80], "texto": texto[:200], "lida": False})
            todas[para] = fila[-200:]
            self.armazem.gravar_colecao("notificacoes", todas)
        except OSError:
            pass

    def notificacoes(self, pessoa: str) -> list:
        todas = self.armazem.ler_colecao("notificacoes", {})
        fila = todas.get(pessoa, []) if isinstance(todas, dict) else []
        return list(reversed(fila))

    def marcar_lidas(self, pessoa: str, ids=None) -> int:
        with self.tranca:
            todas = self.armazem.ler_colecao("notificacoes", {})
            if not isinstance(todas, dict) or pessoa not in todas:
                return 0
            n = 0
            for x in todas[pessoa]:
                if not x.get("lida") and (ids is None or x["id"] in ids):
                    x["lida"] = True
                    n += 1
            self.armazem.gravar_colecao("notificacoes", todas)
            return n

    def lixeira(self) -> list:
        """O que está na lixeira, mais recente primeiro: [{id, chave, titulo, lista, apagada_em, arquivo}]."""
        saida = []
        for t, quando in self.armazem.lixeira():
            l = self.lista(t.get("lista", ""))
            saida.append({"id": t.get("id", ""), "chave": t.get("chave", ""), "titulo": t.get("titulo", ""), "cliente": t.get("cliente", ""),
                          "lista": (l or {}).get("nome", ""), "apagada_em": quando})
        return saida[:200]

    def restaurar(self, tid: str, pessoa: str = "") -> dict:
        """Tira da lixeira o apagado mais recente com esse id e põe de volta na lista (ou na primeira)."""
        with self.tranca:
            if tid in self.tarefas:
                raise ValueError("essa tarefa já está de volta")
            t = self.armazem.tirar_da_lixeira(tid)
            if not isinstance(t, dict) or t.get("id") != tid:
                raise KeyError("não está na lixeira")
            if not self.lista(t.get("lista", "")) and self.listas:
                t["lista"] = self.listas[0]["id"]
                t["status"] = self.listas[0]["status"][0]["id"]
            if not self._status(t["lista"], t.get("status", "")):
                t["status"] = self.lista(t["lista"])["status"][0]["id"]
            if t.get("pai") and t["pai"] not in self.tarefas:
                t["pai"] = ""
            self.tarefas[tid] = t
            self._gravar_tarefa(t, snapshot=False)
            self._evento(t, "restaurada", pessoa)
            return t

    def editar_lote(self, ids: list, campos: dict, pessoa: str = "") -> list:
        """Vários de uma vez: status, responsáveis, prioridade, prazo, lista — o que vier em `campos`."""
        permitidos = {k: v for k, v in (campos or {}).items() if k in ("status", "responsaveis", "prioridade", "prazo", "lista", "tipo", "cliente")}
        saida = []
        for tid in ids or []:
            if tid in self.tarefas:
                saida.append(self.editar_tarefa(tid, dict(permitidos), pessoa))
        return saida

    def _lixeira(self, tid: str) -> None:
        t = self.tarefas.pop(tid, None)
        if not t:
            return
        self._evento(t, "apagada", "")
        self.armazem.para_lixeira(tid)
        for outra in self.tarefas.values():
            if any(l.get("alvo") == tid for l in outra.get("ligacoes", [])):
                outra["ligacoes"] = [l for l in outra["ligacoes"] if l.get("alvo") != tid]
                self._gravar_tarefa(outra, snapshot=False)
        self._subir_versao()

    def _gravar_tarefa(self, t: dict, snapshot: bool = True, subir: bool = True) -> None:
        t["atualizada"] = agora()
        self.armazem.gravar_tarefa(t)
        if snapshot:
            self.armazem.snapshot(t)
        if subir:
            self._subir_versao()

    def exportar_backup(self, pasta: Path | None = None) -> Path:
        """Tudo num JSON só, em dados\\backup\\AAAA-MM-DD.json (guarda os 30 últimos). Vale para JSON e SQLite."""
        pasta = Path(pasta) if pasta else self.raiz / "backup"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = self.armazem.exportar_json(pasta / f"{dt.date.today().isoformat()}.json")
        for velho in sorted(pasta.glob("*.json"))[:-30]:
            try:
                velho.unlink()
            except OSError:
                pass
        return destino

    def _gravar_aprendizado(self) -> None:
        self.armazem.gravar_colecao("aprendizado", self.aprendizado)

    def aprender_apelido(self, texto: str, codigo: str) -> None:
        alvo = normalizar(texto)
        codigo = chave_codigo(codigo)
        if alvo and codigo:
            self.aprendizado.setdefault("apelidos", {})[alvo] = codigo
            self.indice.apelidos[alvo] = codigo
            self._gravar_aprendizado()

    # ------------------------------------------------------------ leitura
    def pessoas(self) -> list:
        """A equipe cadastrada mais quem já aparece nas tarefas."""
        nomes = set(getattr(self, "equipe", []))
        for t in self.tarefas.values():
            for chave in ("responsavel", "criada_por"):
                if t.get(chave):
                    nomes.add(t[chave])
        return sorted(nomes, key=lambda n: n.lower())

    def editar_equipe(self, nomes: list) -> list:
        """A lista de quem trabalha no departamento: é o que a linha "pra Ana" reconhece."""
        with self.tranca:
            vistos, limpos = set(), []
            for n in nomes:
                n = str(n).strip()
                if n and n.lower() not in vistos:
                    vistos.add(n.lower())
                    limpos.append(n)
            self.equipe = limpos
            self.armazem.gravar_colecao("equipe", limpos)
            self._subir_versao()
            return limpos

    def historico(self, tid: str) -> list:
        """A atividade da tarefa: os eventos registrados e, para tarefas de antes do registro, os snapshots."""
        eventos = list(reversed(self.eventos(tarefa=tid, limite=200)))
        if eventos:
            rotulos = {"criada": "criada", "status": "status", "concluida": "concluída", "reaberta": "reaberta", "prazo": "prazo",
                       "responsaveis": "responsáveis", "lista": "lista", "prioridade": "prioridade", "cliente": "cliente",
                       "tipo": "tipo", "titulo": "título", "atrasou": "atrasou", "apagada": "apagada", "comentario": "comentário",
                       "lembrete": "lembrete"}
            saida = []
            for ev in eventos:
                rot = rotulos.get(ev["tipo"], ev["tipo"])
                de, para = ev.get("de"), ev.get("para")
                fmt = lambda v: ", ".join(v) if isinstance(v, list) else (str(v) if v not in (None, "") else "—")
                if ev["tipo"] == "criada":
                    texto = "criada" + (f" para {fmt(para)}" if para else "") + (f" ({ev['texto']})" if ev.get("texto") else "")
                elif ev["tipo"] in ("concluida", "reaberta", "apagada"):
                    texto = rot + (f" — {ev['texto']}" if ev.get("texto") else "")
                elif ev["tipo"] == "atrasou":
                    texto = f"atrasou (prazo era {fmt(de)})"
                elif ev["tipo"] == "comentario":
                    texto = ev.get("texto", "")
                elif ev["tipo"] == "lembrete":
                    texto = f"lembrete para {fmt(para)}" + (f" — {ev['texto']}" if ev.get("texto") else "")
                else:
                    texto = f"{rot}: {fmt(de)} → {fmt(para)}"
                if ev.get("pessoa"):
                    texto += f" · {ev['pessoa']}"
                saida.append({"quando": ev["quando"], "texto": texto, "tipo": ev["tipo"]})
            return saida[-60:]
        fotos = self.armazem.snapshots(tid)
        if not fotos:
            return []
        anteriores, saida = None, []
        rotulos = {"status": "status", "prioridade": "prioridade", "prazo": "prazo", "responsavel": "responsável",
                   "titulo": "título", "lista": "lista", "descricao": "descrição", "cliente": "cliente"}
        for atual in fotos:
            if not isinstance(atual, dict):
                continue
            quando = atual.get("atualizada", "")
            if anteriores is None:
                saida.append({"quando": quando, "texto": f"criada" + (f" por {atual.get('criada_por')}" if atual.get("criada_por") else "")})
            else:
                mudancas = []
                for chave, rotulo in rotulos.items():
                    if anteriores.get(chave) != atual.get(chave):
                        de, para = anteriores.get(chave), atual.get(chave)
                        if chave == "status":
                            s_de, s_para = self._status(atual["lista"], de or ""), self._status(atual["lista"], para or "")
                            de, para = (s_de or {}).get("nome", de), (s_para or {}).get("nome", para)
                        if chave == "descricao":
                            mudancas.append("descrição alterada")
                        else:
                            mudancas.append(f"{rotulo}: {de or '—'} → {para or '—'}")
                feitos_antes = sum(1 for c in anteriores.get("checklist", []) if c.get("feito"))
                feitos_agora = sum(1 for c in atual.get("checklist", []) if c.get("feito"))
                if feitos_agora != feitos_antes:
                    mudancas.append(f"checklist {feitos_agora}/{len(atual.get('checklist', []))}")
                if mudancas:
                    saida.append({"quando": quando, "texto": "; ".join(mudancas)})
            anteriores = atual
        return saida[-40:]

    def tudo(self, pessoa: str = "") -> dict:
        self.recarregar_se_mudou()
        self.rodar_prazos()
        return {"versao": self.versao, "espacos": self.espacos, "listas": self.listas, "modelos": self.modelos,
                "triagem": self.triagem, "equipe": list(getattr(self, "equipe", [])),
                "tarefas": list(self.tarefas.values()), "pessoas": self.pessoas(),
                "tipos": {k: v.get("nome", k) for k, v in catalogo.tipos().items()},
                "prioridades": list(PRIORIDADES), "tipos_de_campo": list(TIPOS_DE_CAMPO),
                "obrigacoes": [o["nome"] for o in calendario.obrigacoes()],
                "lembretes": [t["id"] for t in self.lembretes(pessoa)], "avisos": self.avisos}

    def calendario_do_mes(self, ano: int, mes: int) -> dict:
        feriados = {d.isoformat(): n for d, n in calendario.feriados(ano).items() if d.month == mes}
        obrigacoes = []
        for o in calendario.obrigacoes():
            v = calendario.vencimento(o, ano, mes)
            obrigacoes.append({"data": v.isoformat(), "nome": o["nome"]})
        return {"feriados": feriados, "obrigacoes": obrigacoes}

    def procurar_clientes(self, texto: str) -> list:
        texto = (texto or "").strip()
        if not texto:
            return []
        if texto.isdigit():
            c = self.indice.achar(texto)
            achados = [(c, 100)] if c else []
            achados += [(x, 90) for x in self.indice.clientes.values()
                        if x.codigo.startswith(texto) and (not c or x.codigo != c.codigo)][:8]
        else:
            alvo = normalizar(texto)
            contem = [(c, 100) for c in self.indice.clientes.values() if alvo in normalizar(c.nome)]
            contem.sort(key=lambda x: (normalizar(x[0].nome).find(alvo), x[0].nome))
            vistos = {c.codigo for c, _p in contem}
            parecidos = [(c, p) for c, p in self.indice.por_nome(texto, minimo=55) if c.codigo not in vistos]
            achados = contem + parecidos
        return [{"codigo": c.codigo, "nome": c.nome} for c, _p in achados[:10]]
