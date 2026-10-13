"""Avisos: o app lembra sozinho, mesmo com a página fechada.

O servidor fica rodando o dia inteiro nesta máquina, então é ele quem avisa, pelo balão do
Windows (`toast.ps1`, sem instalar nada) e pela página (que mostra o mesmo aviso e, se a
pessoa permitir, a notificação do navegador):

- **resumo do dia** nos horários configurados (padrão 08:30 e 13:30): atrasadas, para hoje,
  aguardando há muito tempo;
- **alerta de amanhã** (padrão 16:30): o que vence amanhã, com as urgentes na frente;
- **lembretes** (`tarefa.lembrete` = hoje): um balão por tarefa, uma vez por dia;
- **urgente para hoje** criada ou mudada depois do resumo: avisa na hora.

Quem recebe é a pessoa que usou a página nesta máquina por último (o servidor é por máquina).
A configuração fica em `%LOCALAPPDATA%\\GestorDemandas\\avisos.json`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

PASTA_FERRAMENTA = Path(os.path.abspath(__file__)).parent.parent
TOAST = PASTA_FERRAMENTA / "toast.ps1"
SEM_JANELA = 0x08000000
PADRAO = {"ligado": True, "horarios_resumo": ["08:30", "13:30"], "hora_amanha": "16:30",
          "pessoa": "", "balao": True}


class Avisos:
    def __init__(self, escritorio, arquivo: Path):
        self.esc = escritorio
        self.arquivo = Path(arquivo)
        self.config = dict(PADRAO)
        self.config.update(self._ler())
        self.feitos: dict = {}            # "2026-10-08 08:30" → True (não repete no mesmo dia)
        self.pendentes: list = []        # avisos que a página ainda não mostrou
        self.tranca = threading.Lock()
        self._parar = threading.Event()

    # ------------------------------------------------------------ configuração
    def _ler(self) -> dict:
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def gravar(self) -> None:
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def editar(self, campos: dict) -> dict:
        for chave in ("ligado", "balao"):
            if chave in campos:
                self.config[chave] = bool(campos[chave])
        if "horarios_resumo" in campos:
            self.config["horarios_resumo"] = [h for h in campos["horarios_resumo"] if _hora_valida(h)][:6]
        if "hora_amanha" in campos:
            self.config["hora_amanha"] = campos["hora_amanha"] if _hora_valida(campos["hora_amanha"]) else ""
        if campos.get("pessoa"):
            self.config["pessoa"] = str(campos["pessoa"]).strip()
        self.gravar()
        return self.config

    def pessoa_viu(self, pessoa: str) -> None:
        """A página desta máquina está sendo usada por `pessoa`: é ela quem recebe os balões."""
        if pessoa and pessoa != self.config.get("pessoa"):
            self.config["pessoa"] = pessoa
            self.gravar()

    # ------------------------------------------------------------ o que avisar
    def _minhas(self, pessoa: str) -> list:
        saida = []
        # o espaço Pessoal da pessoa entra junto (acessiveis() olha quem está no contexto)
        self.esc.definir_pessoa(pessoa)
        try:
            for d in self.esc.acessiveis():
                for t in d.area.tarefas.values():
                    if d.area._feita(t):
                        continue
                    donos = t.get("responsaveis") or ([t["responsavel"]] if t.get("responsavel") else [])
                    if pessoa and donos and pessoa not in donos:
                        continue
                    if pessoa and not donos and t.get("criada_por") not in ("", pessoa):
                        continue
                    saida.append(dict(t, pessoal=bool(getattr(d.area, "pessoal", False))))
        finally:
            self.esc.definir_pessoa("")
        return saida

    def resumo(self, pessoa: str | None = None, hoje: dt.date | None = None) -> dict:
        pessoa = self.config.get("pessoa", "") if pessoa is None else pessoa
        hoje = hoje or dt.date.today()
        amanha = (hoje + dt.timedelta(days=1)).isoformat()
        h = hoje.isoformat()
        minhas = self._minhas(pessoa)
        atrasadas = [t for t in minhas if t.get("prazo") and t["prazo"] < h]
        de_hoje = [t for t in minhas if t.get("prazo") == h]
        de_amanha = [t for t in minhas if t.get("prazo") == amanha]
        urgentes_amanha = [t for t in de_amanha if t.get("prioridade") in ("urgente", "alta")]
        aguardando = [t for t in minhas if t.get("aguardando_desde") and (hoje - dt.date.fromisoformat(t["aguardando_desde"])).days >= 5]
        lembretes = [t for t in minhas if t.get("lembrete") and t["lembrete"] <= h]
        return {"pessoa": pessoa, "atrasadas": _curtas(atrasadas), "hoje": _curtas(de_hoje), "amanha": _curtas(de_amanha),
                "urgentes_amanha": _curtas(urgentes_amanha), "aguardando": _curtas(aguardando), "lembretes": _curtas(lembretes)}

    # ------------------------------------------------------------ o relógio
    def iniciar(self) -> None:
        threading.Thread(target=self._laco, daemon=True).start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        # o primeiro resumo sai logo que o servidor sobe, para quem acabou de chegar
        self._parar.wait(20)
        try:
            self.tique(dt.datetime.now(), primeiro=True)
        except Exception:
            pass
        while not self._parar.wait(30):
            try:
                self.tique(dt.datetime.now())
            except Exception:
                pass

    def tique(self, agora: dt.datetime, primeiro: bool = False) -> list:
        """Decide o que avisar neste instante. Devolve os avisos emitidos (para testes)."""
        if not self.config.get("ligado", True):
            return []
        emitidos = []
        hoje = agora.date()
        hm = agora.strftime("%H:%M")
        pessoa = self.config.get("pessoa", "")
        r = self.resumo(pessoa, hoje)

        def marcar(chave):
            chave = f"{hoje.isoformat()} {chave}"
            if chave in self.feitos:
                return False
            self.feitos[chave] = True
            return True

        horarios = self.config.get("horarios_resumo", [])
        if primeiro or any(h == hm for h in horarios):
            chave = "resumo " + (hm if hm in horarios else "inicio")
            if marcar(chave) and (r["atrasadas"] or r["hoje"] or r["aguardando"]):
                partes = []
                if r["atrasadas"]:
                    partes.append(f"{len(r['atrasadas'])} atrasada(s)")
                if r["hoje"]:
                    partes.append(f"{len(r['hoje'])} para hoje")
                if r["aguardando"]:
                    partes.append(f"{len(r['aguardando'])} aguardando há 5+ dias")
                primeiras = "; ".join(f"{t['chave']} {t['titulo']}" for t in (r["atrasadas"] + r["hoje"])[:3])
                emitidos.append(self._emitir("resumo", f"Gestor de Demandas — {pessoa or 'hoje'}", ", ".join(partes) + ". " + primeiras))

        if self.config.get("hora_amanha") == hm and marcar("amanha") and r["amanha"]:
            urg = r["urgentes_amanha"]
            texto = f"{len(r['amanha'])} tarefa(s) vencem amanhã" + (f" — {len(urg)} URGENTE(S): " + "; ".join(f"{t['chave']} {t['titulo']}" for t in urg[:3]) if urg else ": " + "; ".join(f"{t['chave']} {t['titulo']}" for t in r["amanha"][:3]))
            emitidos.append(self._emitir("amanha", "Gestor de Demandas — amanhã", texto))

        # backup diário de cada departamento (dados\backup\AAAA-MM-DD.json), uma vez por dia às 18h
        if hm == self.config.get("hora_backup", "18:00") and marcar("backup"):
            for d in self.esc.acessiveis():
                try:
                    d.area.exportar_backup()
                except Exception:
                    pass

        for t in r["lembretes"][:5]:
            # lembrete com hora ("ir no RH às 10h") só dispara a partir dessa hora
            if t.get("lembrete_hora") and t.get("lembrete") == hoje.isoformat() and hm < t["lembrete_hora"]:
                continue
            cada = int(t.get("lembrete_cada") or 0)
            if cada > 0 and t.get("lembrete") == hoje.isoformat():
                # "lembrar a cada 30 min": no dia do lembrete, um balão por fatia do relógio, só das 07h às 20h;
                # nos dias seguintes, se ainda estiver aberta, volta a ser uma vez por dia
                if not (7 <= agora.hour < 20):
                    continue
                fatia = (agora.hour * 60 + agora.minute) // cada
                chave = f"lembrete {t['id']} {fatia}"
            else:
                # a hora entra na chave — "me lembra em 10 min" marca outra hora e o balão volta no mesmo dia
                chave = f"lembrete {t['id']} {t.get('lembrete_hora') or ''}".rstrip()
            if marcar(chave):
                motivo = (t.get("lembrete_motivo") or "").strip()
                quem = t["chave"] + (f" {t['cliente']}" if t.get("cliente") else "")
                titulo = f"Lembrete: {motivo} — {quem}" if motivo else f"Lembrete: {t['chave']}"
                texto = t["titulo"] + (f" · {t['cliente_nome'] or t['cliente']}" if t.get("cliente") else "")
                emitidos.append(self._emitir("lembrete", titulo, texto, t["id"]))

        for t in r["hoje"]:
            if t.get("prioridade") == "urgente" and marcar("urgente " + t["id"]):
                emitidos.append(self._emitir("urgente", f"URGENTE hoje: {t['chave']}", t["titulo"], t["id"]))
        return emitidos

    def _emitir(self, tipo: str, titulo: str, texto: str, tarefa_id: str = "") -> dict:
        aviso = {"id": f"{tipo}-{dt.datetime.now().strftime('%H%M%S%f')}", "tipo": tipo, "titulo": titulo,
                 "texto": texto[:220], "tarefa": tarefa_id, "quando": dt.datetime.now().isoformat(timespec="seconds")}
        with self.tranca:
            self.pendentes.append(aviso)
            self.pendentes = self.pendentes[-30:]
        if self.config.get("balao", True):
            self.balao(titulo, texto[:220])
        return aviso

    def balao(self, titulo: str, texto: str) -> bool:
        """O aviso no canto da tela do Windows. Falha em silêncio: a página ainda mostra.

        Só existe no Windows (PowerShell + toast.ps1); em outro sistema devolve False sem tentar —
        `creationflags` nem é aceito fora do Windows."""
        if sys.platform != "win32" or not TOAST.is_file():
            return False
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                              "-File", str(TOAST), "-Titulo", titulo, "-Texto", texto],
                             creationflags=SEM_JANELA, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def para_a_pagina(self, desde: str = "") -> list:
        with self.tranca:
            return [a for a in self.pendentes if a["quando"] > desde] if desde else list(self.pendentes)


def _curtas(tarefas: list) -> list:
    return [{"id": t["id"], "chave": t.get("chave", ""), "titulo": t["titulo"], "cliente": t.get("cliente", ""),
             "cliente_nome": t.get("cliente_nome", ""),
             "prazo": t.get("prazo"), "prioridade": t.get("prioridade", "normal"), "lista": t.get("lista", ""),
             "lembrete": t.get("lembrete"), "lembrete_cada": t.get("lembrete_cada"), "lembrete_hora": t.get("lembrete_hora", ""),
             "lembrete_motivo": t.get("lembrete_motivo", ""),
             "responsaveis": list(t.get("responsaveis") or []), "pessoal": bool(t.get("pessoal")), "rodizio": list(t.get("rodizio") or [])}
            for t in sorted(tarefas, key=lambda x: ({"urgente": 0, "alta": 1, "normal": 2, "baixa": 3}.get(x.get("prioridade"), 2), x.get("prazo") or "9999"))]


def _hora_valida(h) -> bool:
    try:
        dt.datetime.strptime(str(h), "%H:%M")
        return True
    except ValueError:
        return False
