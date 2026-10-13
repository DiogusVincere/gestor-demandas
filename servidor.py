"""Gestor de Demandas — o servidor. Serve a página (web/) e a API em JSON.

    pythonw servidor.py                                 abre o navegador em http://127.0.0.1:8731
    python servidor.py --sem-navegador --porta 8731 --dados <pasta>   (testes)
    python servidor.py --host 0.0.0.0 --sem-navegador   servidor central (modelo A), todos abrem pelo nome da máquina

Sem internet, sem serviço de fora: o Python desta máquina lê e grava os arquivos da pasta de dados.
Se a porta já estiver em uso, é porque o app já está aberto: só abre o navegador.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PASTA = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(PASTA))

from nucleo import clientes, dados  # noqa: E402
from nucleo.escritorio import Escritorio, NOME_PESSOAL  # noqa: E402
from nucleo.usuarios import Usuarios  # noqa: E402

COOKIE_SESSAO = "demandas_sessao"
# rotas que funcionam sem sessão quando o login está ligado
SEM_LOGIN = (["login"], ["eu"], ["versao"], ["encerrar"])

PORTA_PADRAO = 8731
# Sobe a cada mudança no código. Um servidor antigo que ainda esteja no ar é encerrado pelo novo
# (é o que acontece quando alguém atualiza a pasta e abre o .bat de novo).
VERSAO_CODIGO = "1.0"
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GestorDemandas"
WEB = PASTA / "web"


class Api:
    """As rotas. Cada método recebe (partes da url, query, corpo, pessoa) e devolve (código, json).

    Cada coisa mora na pasta de um departamento: a rota acha a `Area` certa pelo id do que está
    sendo mexido (espaço, lista, tarefa, modelo) — quem não tem acesso à pasta nem enxerga o id.
    """

    def __init__(self, escritorio: Escritorio, avisos=None, usuarios: Usuarios | None = None):
        self.esc = escritorio
        self.avisos = avisos
        self.usuarios = usuarios
        self.servidor = None
        self.esc.login_ligado = bool(usuarios and usuarios.ligado)

    def encerrar(self) -> None:
        if self.servidor is not None:
            self.servidor.shutdown()

    def _area_do_corpo(self, corpo: dict, query: dict):
        """A área a usar quando a rota não tem id: pela lista, pelo espaço ou pelo departamento."""
        if corpo.get("lista"):
            return self.esc.area_de_lista(corpo["lista"])
        if corpo.get("espaco"):
            return self.esc.area_de_espaco(corpo["espaco"])
        nome = corpo.get("departamento") or query.get("departamento", [""])[0]
        return self.esc.area_por_nome(nome)

    def rotear(self, metodo: str, caminho: str, query: dict, corpo: dict, pessoa: str, token: str = ""):
        """Devolve (código, json) — ou (código, json, cookie) nas rotas de login/sair."""
        p = [x for x in caminho.split("/") if x][1:]  # tira "api"
        esc = self.esc
        login_ligado = bool(self.usuarios and self.usuarios.ligado)
        usuario = self.usuarios.sessao(token) if login_ligado else None
        if login_ligado:
            if usuario:
                pessoa = usuario["nome"]        # com login, o nome é o do cadastro, não o que a página mandou
            elif p[:1] not in SEM_LOGIN:
                return 401, {"erro": "faça login", "login_ligado": True}
        esc.definir_usuario(usuario)
        esc.definir_pessoa(pessoa)        # o espaço Pessoal de quem está pedindo entra em acessiveis()
        if self.avisos is not None and pessoa and p[:1] in (["tudo"], ["versao"]):
            self.avisos.pessoa_viu(pessoa)   # quem usa a página nesta máquina recebe os balões
        try:
            # ---- modelo A: login, sessão, usuários
            if metodo == "POST" and p == ["login"]:
                if not login_ligado:
                    return 200, {"login_ligado": False}
                u = self.usuarios.autenticar(corpo.get("login", ""), corpo.get("senha", ""))
                if not u:
                    return 401, {"erro": "login ou senha errados"}
                novo = self.usuarios.criar_sessao(u["login"])
                return 200, {"usuario": Usuarios.publico(u)}, f"{COOKIE_SESSAO}={novo}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            if metodo == "POST" and p == ["sair"]:
                if self.usuarios:
                    self.usuarios.encerrar_sessao(token)
                return 200, {"ok": True}, f"{COOKIE_SESSAO}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            if metodo == "GET" and p == ["eu"]:
                return 200, {"login_ligado": login_ligado, "usuario": Usuarios.publico(usuario), "codigo": VERSAO_CODIGO}
            if p == ["usuarios"]:
                if not login_ligado:
                    return 400, {"erro": "o login está desligado: crie o usuarios.json ao lado do departamentos.json (ou peça ao admin)"}
                if not esc.e_admin():
                    return 403, {"erro": "só o administrador mexe nos usuários"}
                if metodo == "GET":
                    return 200, {"usuarios": self.usuarios.lista(), "papeis": ["membro", "gestor", "admin"],
                                 "departamentos": [d.nome for d in esc.departamentos]}
                if metodo == "PATCH":
                    return 200, {"usuarios": self.usuarios.editar(corpo.get("usuarios") or [])}
            if metodo == "POST" and p == ["senha"] and usuario:
                if not self.usuarios.autenticar(usuario["login"], corpo.get("atual", "")):
                    return 400, {"erro": "a senha atual não confere"}
                if len(corpo.get("nova", "")) < 4:
                    return 400, {"erro": "a senha nova precisa ter pelo menos 4 caracteres"}
                self.usuarios.definir_senha(usuario["login"], corpo["nova"])
                return 200, {"ok": True}
            if metodo == "GET" and p == ["tudo"]:
                return 200, esc.tudo(pessoa)
            if p[:1] == ["avisos"] and self.avisos is not None:
                if metodo == "GET" and len(p) == 1:
                    return 200, {"pendentes": self.avisos.para_a_pagina(query.get("desde", [""])[0]),
                                 "resumo": self.avisos.resumo(pessoa or None), "config": self.avisos.config}
                if metodo == "PATCH" and p == ["avisos", "config"]:
                    return 200, self.avisos.editar(corpo)
                if metodo == "POST" and p == ["avisos", "testar"]:
                    ok = self.avisos.balao("Gestor de Demandas — teste", "Se você viu este balão, os avisos do Windows funcionam.")
                    return 200, {"ok": ok}
            if p[:1] == ["equipe"]:
                a = self._area_do_corpo(corpo, query)
                if metodo == "GET":
                    return 200, {"equipe": a.equipe, "pessoas": a.pessoas()}
                if metodo == "PATCH":
                    return 200, {"equipe": a.editar_equipe(corpo.get("equipe") or [])}
            if metodo == "GET" and p == ["versao"]:
                return 200, {"versao": esc.versao(), "codigo": VERSAO_CODIGO}
            if metodo == "POST" and p == ["backup"]:
                # tudo de cada departamento num JSON em dados\backup\AAAA-MM-DD.json (JSON ou SQLite)
                saida = {}
                for d in esc.acessiveis():
                    saida[esc.nome_da_area(d.area)] = str(d.area.exportar_backup())
                return 200, {"arquivos": saida}
            if metodo == "POST" and p == ["encerrar"]:
                # só quem está nesta máquina chega aqui (o servidor escuta em 127.0.0.1)
                threading.Thread(target=self.encerrar, daemon=True).start()
                return 200, {"ok": True, "codigo": VERSAO_CODIGO}
            if metodo == "GET" and p == ["departamentos"]:
                return 200, esc.tudo(pessoa)["departamentos"]
            if metodo == "PATCH" and p == ["departamentos"]:
                return 200, esc.editar_departamentos(corpo.get("departamentos") or [])
            if p == ["clientes"]:
                # com ?q= é a busca da tela; sem, é o cadastro inteiro (clientes.json), que o PUT substitui
                if metodo == "GET" and query.get("q", [""])[0].strip():
                    return 200, esc.area_padrao().procurar_clientes(query.get("q", [""])[0])
                if metodo == "GET":
                    return 200, {"clientes": esc.indice.lista(), "arquivo": str(esc.indice.arquivo or ""), "avisos": list(esc.indice.avisos)}
                if metodo == "PUT":
                    if login_ligado and not esc.e_admin():
                        return 403, {"erro": "só o administrador altera o cadastro de clientes"}
                    return 200, {"clientes": esc.indice.gravar(corpo.get("clientes") if isinstance(corpo, dict) else corpo)}
            if metodo == "GET" and p == ["calendario"]:
                ano, mes = int(query.get("ano", ["0"])[0]), int(query.get("mes", ["0"])[0])
                return 200, esc.area_padrao().calendario_do_mes(ano, mes)
            if metodo == "POST" and p == ["entender"]:
                a = self._area_do_corpo(corpo, query)
                return 200, a.entender_texto(corpo.get("texto", ""), pessoas=a.pessoas())
            if metodo == "POST" and p == ["colar"]:
                a = self._area_do_corpo(corpo, query)
                juntar = corpo.get("juntar")
                return 200, a.entender_mensagem(corpo.get("texto", ""), pessoas=a.pessoas(), pessoa=pessoa,
                                                lados=corpo.get("lados") or None,
                                                juntar=juntar if isinstance(juntar, bool) else None)
            if metodo == "GET" and p == ["eventos"]:
                # o histórico do escritório: o que aconteceu, quem fez, quando (mais recente primeiro)
                desde = query.get("desde", [""])[0]
                quem = query.get("pessoa", [""])[0]
                limite = int(query.get("limite", ["300"])[0] or 300)
                saida = []
                for d in esc.acessiveis():
                    for ev in d.area.eventos(desde=desde, pessoa=quem, limite=limite):
                        saida.append(dict(ev, departamento=esc.nome_da_area(d.area)))
                saida.sort(key=lambda ev: ev.get("quando", ""), reverse=True)
                return 200, {"eventos": saida[:limite]}
            if metodo == "GET" and p == ["triagem"]:
                return 200, {esc.nome_da_area(d.area): d.area.triagem for d in esc.acessiveis()}
            if metodo == "PATCH" and p == ["triagem"]:
                return 200, self._area_do_corpo(corpo, query).editar_triagem(corpo)
            if metodo == "GET" and len(p) == 3 and p[0] == "tarefas" and p[2] == "historico":
                return 200, esc.area_de_tarefa(p[1]).historico(p[1])

            if p[:1] == ["modelos"]:
                if metodo == "POST" and len(p) == 1:
                    return 201, esc.area_de_lista(corpo.get("lista", "")).salvar_modelo(corpo.get("lista", ""), corpo.get("nome", ""))
                if metodo == "PATCH" and len(p) == 2:
                    return 200, esc.area_de_modelo(p[1]).editar_modelo(p[1], corpo)
                if metodo == "DELETE" and len(p) == 2:
                    esc.area_de_modelo(p[1]).apagar_modelo(p[1])
                    return 200, {"ok": True}
            if metodo == "POST" and p == ["listas", "de-modelo"]:
                a = esc.area_de_modelo(corpo.get("modelo", ""))
                if not a.espaco(corpo.get("espaco", "")):
                    return 400, {"erro": "o espaço precisa ser do mesmo departamento do modelo"}
                return 201, a.criar_lista_de_modelo(corpo.get("modelo", ""), corpo.get("espaco", ""),
                                                    corpo.get("nome", ""), corpo.get("competencia", ""),
                                                    corpo.get("clientes") or [], pessoa)
            if p[:1] == ["espacos"]:
                if metodo == "POST" and len(p) == 1:
                    a = esc.area_por_nome(corpo.get("departamento", ""))
                    return 201, a.criar_espaco(corpo.get("nome", ""), corpo.get("cor", ""), corpo.get("prefixo", ""))
                if metodo == "PATCH" and len(p) == 2:
                    return 200, esc.area_de_espaco(p[1]).editar_espaco(p[1], corpo)
                if metodo == "DELETE" and len(p) == 2:
                    esc.area_de_espaco(p[1]).apagar_espaco(p[1])
                    return 200, {"ok": True}
            if p[:1] == ["listas"]:
                if metodo == "POST" and len(p) == 1:
                    return 201, esc.area_de_espaco(corpo.get("espaco", "")).criar_lista(corpo.get("espaco", ""), corpo.get("nome", ""))
                if metodo == "PATCH" and len(p) == 2:
                    a = esc.area_de_lista(p[1])
                    if corpo.get("espaco") and not a.espaco(corpo["espaco"]):
                        return 400, {"erro": "uma lista não muda de departamento"}
                    return 200, a.editar_lista(p[1], corpo)
                if metodo == "DELETE" and len(p) == 2:
                    esc.area_de_lista(p[1]).apagar_lista(p[1])
                    return 200, {"ok": True}
            # ---- notificações pessoais, lixeira, lote, comentários e anexos
            if p[:1] == ["notificacoes"]:
                if metodo == "GET" and len(p) == 1:
                    saida = []
                    for d in esc.acessiveis():
                        saida.extend(dict(n, departamento=esc.nome_da_area(d.area)) for n in d.area.notificacoes(pessoa))
                    saida.sort(key=lambda n: n.get("quando", ""), reverse=True)
                    return 200, {"notificacoes": saida[:100], "nao_lidas": sum(1 for n in saida if not n.get("lida"))}
                if metodo == "POST" and p == ["notificacoes", "lidas"]:
                    ids = corpo.get("ids")
                    n = sum(d.area.marcar_lidas(pessoa, None if ids in (None, "todas") else set(ids)) for d in esc.acessiveis())
                    return 200, {"marcadas": n}
            if p[:1] == ["lixeira"]:
                if metodo == "GET" and len(p) == 1:
                    saida = []
                    for d in esc.acessiveis():
                        saida.extend(dict(x, departamento=esc.nome_da_area(d.area)) for x in d.area.lixeira())
                    saida.sort(key=lambda x: x.get("apagada_em", ""), reverse=True)
                    return 200, {"lixeira": saida}
                if metodo == "POST" and len(p) == 3 and p[2] == "restaurar":
                    for d in esc.acessiveis():
                        if any(x["id"] == p[1] for x in d.area.lixeira()):
                            return 200, d.area.restaurar(p[1], pessoa)
                    return 404, {"erro": "não está na lixeira"}
            if metodo == "PATCH" and p == ["tarefas", "lote"]:
                ids = [x for x in (corpo.get("ids") or []) if isinstance(x, str)]
                saida = []
                for d in esc.acessiveis():
                    meus = [x for x in ids if x in d.area.tarefas]
                    if meus:
                        if corpo.get("campos", {}).get("lista") and not d.area.lista(corpo["campos"]["lista"]):
                            return 400, {"erro": "uma tarefa não muda de departamento"}
                        saida.extend(d.area.editar_lote(meus, corpo.get("campos") or {}, pessoa))
                return 200, {"tarefas": saida}
            if p[:1] == ["tarefas"] and len(p) >= 3 and p[2] == "comentarios":
                a = esc.area_de_tarefa(p[1])
                if metodo == "POST" and len(p) == 3:
                    return 201, a.comentar(p[1], corpo.get("texto", ""), pessoa)
                if metodo == "DELETE" and len(p) == 4:
                    return 200, a.apagar_comentario(p[1], p[3], pessoa)
            if p[:1] == ["tarefas"] and len(p) >= 3 and p[2] == "anexos":
                a = esc.area_de_tarefa(p[1])
                if metodo == "POST" and len(p) == 3:
                    return 201, a.anexar(p[1], corpo.get("tipo", "link"), corpo.get("nome", ""), corpo.get("url", ""), corpo.get("dados", ""), pessoa)
                if metodo == "DELETE" and len(p) == 4:
                    return 200, a.apagar_anexo(p[1], p[3])
            if metodo == "GET" and len(p) == 2 and p[0] == "tarefas":
                a = esc.area_de_tarefa(p[1])
                t = a.tarefas[p[1]]
                lista = a.lista(t.get("lista", "")) or {}
                return 200, dict(t, departamento=esc.nome_da_area(a), lista_nome=lista.get("nome", ""),
                                 status_nome=(a._status(t.get("lista", ""), t.get("status", "")) or {}).get("nome", ""),
                                 # a bolha mostra os botões de status da lista (Fazendo / Aguardando cliente / Concluída)
                                 status_lista=[{"id": st["id"], "nome": st["nome"], "tipo": st.get("tipo", "aberto")} for st in lista.get("status", [])])
            if metodo == "POST" and len(p) == 3 and p[0] == "tarefas" and p[2] == "concluir":
                # o tique da linha e da bolha: status "feito" da lista (reabrir=true volta para aberto)
                return 200, esc.area_de_tarefa(p[1]).concluir(p[1], pessoa, reabrir=bool(corpo.get("reabrir")))
            if metodo == "POST" and len(p) == 3 and p[0] == "tarefas" and p[2] == "adiar":
                # "me lembra em 10 min" / "lembrar de cobrar o cliente em 2 dias úteis"
                try:
                    return 200, esc.area_de_tarefa(p[1]).adiar_lembrete(
                        p[1], pessoa, minutos=int(corpo.get("minutos") or 0), dias_uteis=int(corpo.get("dias_uteis") or 0),
                        data=str(corpo.get("data") or ""), hora=str(corpo.get("hora") or ""), motivo=corpo.get("motivo"))
                except (TypeError, ValueError) as erro:
                    return 400, {"erro": str(erro)}
            if p[:1] == ["tarefas"]:
                if metodo == "POST" and len(p) == 1:
                    ajustes = corpo.get("ajustes") or {}
                    lista_pedida = corpo.get("lista", "")
                    if "pessoal" not in ajustes and corpo.get("modo", "linha") == "linha" and corpo.get("texto", "").strip():
                        # ninguém marcou: vale o que o entendedor achou ("eu: …", "minha vez de lavar a máquina")
                        try:
                            from nucleo.entender import entender as _entender
                            origem_tmp = esc.area_de_lista(lista_pedida) if lista_pedida and any(d.area.lista(lista_pedida) for d in esc.acessiveis()) else esc.area_padrao()
                            if _entender(corpo.get("texto", ""), esc.indice, pessoas=origem_tmp.pessoas(), aprendizado=origem_tmp.aprendizado).pessoal:
                                ajustes = dict(ajustes, pessoal=True)
                        except Exception:
                            pass
                    if ajustes.get("pessoal"):
                        # coisa pessoal vai para o espaço Pessoal de quem vai fazer (você, ou quem você indicou:
                        # "Ana, tira o lixo hoje" / a coordenadora criando "ir ao RH às 10h" para alguém)
                        origem = esc.area_de_lista(lista_pedida) if lista_pedida and any(d.area.lista(lista_pedida) for d in esc.acessiveis()) else esc.area_padrao()
                        alvo = ""
                        if ajustes.get("responsaveis"):
                            alvo = ajustes["responsaveis"][0]
                        elif ajustes.get("responsavel"):
                            alvo = ajustes["responsavel"]
                        else:
                            from nucleo.entender import entender as _entender
                            e_tmp = _entender(corpo.get("texto", ""), esc.indice, pessoas=origem.pessoas(), aprendizado=origem.aprendizado)
                            alvo = e_tmp.pessoas[0] if e_tmp.pessoas else ""
                        dono = alvo or pessoa
                        a = esc.area_pessoal(dono)
                        if a is None:
                            return 400, {"erro": "não achei o espaço Pessoal"}
                        lista_pessoal = next((l for l in a.listas if l["nome"] == ("Rotinas" if ajustes.get("recorrencia") else "Lembretes")), a.listas[0])
                        aj = dict(ajustes, triar=False, responsaveis=[dono])
                        aj.pop("pessoal", None)
                        aj.pop("responsavel", None)
                        # "é pessoal" marcado pela pessoa contra o palpite: a área de origem (do departamento) aprende
                        try:
                            from nucleo.entender import entender as _entender
                            e_tmp = _entender(corpo.get("texto", ""), esc.indice, pessoas=origem.pessoas(), aprendizado=origem.aprendizado)
                            if not e_tmp.pessoal:
                                origem.aprender_pessoal(e_tmp.titulo or corpo.get("texto", ""), True)
                        except Exception:
                            pass
                        criadas = [a.criar_tarefa(lista_pessoal["id"], corpo.get("texto", ""), pessoa, aj, pessoas=a.pessoas())]
                        if dono != pessoa:
                            a._notificar(dono, pessoa, "atribuida", criadas[0], f"{pessoa or 'alguém'} deixou um lembrete para você: {criadas[0]['titulo'][:60]}")
                        t = dict(criadas[0])
                        t["criadas"] = [{"id": x["id"], "chave": x.get("chave", ""), "titulo": x["titulo"], "lista": x["lista"], "pessoal": True} for x in criadas]
                        t["departamento"] = NOME_PESSOAL
                        return 201, t
                    a = esc.area_de_lista(lista_pedida)
                    modo = corpo.get("modo", "linha")
                    if modo == "colar":
                        criadas = a.criar_de_mensagem(corpo.get("lista", ""), corpo.get("texto", ""), pessoa,
                                                      corpo.get("ajustes") or {}, pessoas=a.pessoas())
                    else:
                        criadas = a.criar_varias(corpo.get("lista", ""), corpo.get("texto", ""), pessoa,
                                                 corpo.get("ajustes") or {}, pessoas=a.pessoas())
                    t = dict(criadas[0])
                    t["criadas"] = [{"id": x["id"], "chave": x.get("chave", ""), "titulo": x["titulo"], "lista": x["lista"]} for x in criadas]
                    t["departamento"] = esc.nome_da_area(a)
                    return 201, t
                if metodo == "PATCH" and len(p) == 2:
                    a = esc.area_de_tarefa(p[1])
                    if corpo.get("lista") and not a.lista(corpo["lista"]):
                        return 400, {"erro": "uma tarefa não muda de departamento"}
                    return 200, a.editar_tarefa(p[1], corpo, pessoa)
                if metodo == "POST" and len(p) == 3 and p[2] == "mover":
                    return 200, esc.area_de_tarefa(p[1]).mover_tarefa(p[1], corpo.get("status"), corpo.get("antes_de", ""),
                                                                      corpo.get("depois_de", ""), corpo.get("lista"), pessoa=pessoa)
                if metodo == "DELETE" and len(p) == 2:
                    esc.area_de_tarefa(p[1]).apagar_tarefa(p[1], com_filhas=query.get("com_filhas", ["0"])[0] == "1")
                    return 200, {"ok": True}
            return 404, {"erro": f"não existe {metodo} {caminho}"}
        except PermissionError as erro:
            return 403, {"erro": str(erro)}
        except KeyError as erro:
            return 404, {"erro": str(erro).strip("'")}
        except ValueError as erro:
            return 400, {"erro": str(erro)}
        except Exception:
            registrar(traceback.format_exc())
            return 500, {"erro": "deu erro no servidor; veja erros.log"}
        finally:
            esc.definir_usuario(None)
            esc.definir_pessoa("")


def registrar(texto: str) -> None:
    try:
        with (PASTA / "erros.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except OSError:
        pass


def fazer_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # silencia o console
            pass

        def _json(self, codigo: int, dados_, cookie: str = "") -> None:
            corpo = json.dumps(dados_, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(corpo)

        def _token(self) -> str:
            """O cookie da sessão (modelo A). Sem login ligado, ninguém olha para ele."""
            for parte in (self.headers.get("Cookie") or "").split(";"):
                nome, _s, valor = parte.strip().partition("=")
                if nome == COOKIE_SESSAO:
                    return valor.strip()
            return ""

        def _api(self, metodo: str) -> None:
            url = urlparse(self.path)
            if url.path == "/api/encerrar" and self.client_address[0] not in ("127.0.0.1", "::1"):
                self._json(403, {"erro": "só desta máquina"})   # com --host 0.0.0.0, ninguém de fora derruba o servidor
                return
            tamanho = int(self.headers.get("Content-Length") or 0)
            bruto = self.rfile.read(tamanho) if tamanho else b""
            try:
                corpo = json.loads(bruto.decode("utf-8")) if bruto else {}
            except ValueError:
                self._json(400, {"erro": "corpo não é JSON"})
                return
            # o navegador manda o nome codificado (cabeçalho não aceita acento cru)
            pessoa = unquote(self.headers.get("X-Pessoa", ""))
            resultado = api.rotear(metodo, url.path, parse_qs(url.query), corpo, pessoa.strip(), self._token())
            codigo, resposta = resultado[0], resultado[1]
            self._json(codigo, resposta, resultado[2] if len(resultado) > 2 else "")

        def _estatico(self) -> None:
            url = urlparse(self.path)
            caminho = url.path if url.path not in ("", "/") else "/index.html"
            alvo = (WEB / caminho.lstrip("/")).resolve()
            if WEB.resolve() not in alvo.parents or not alvo.is_file():
                self.send_response(404)
                self.end_headers()
                return
            tipo = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
                tipo += "; charset=utf-8"
            corpo = alvo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def _anexo(self) -> None:
            """GET /api/anexos/<tarefa>/<anexo>: o arquivo guardado em dados\\anexos, para abrir no navegador."""
            partes = [x for x in urlparse(self.path).path.split("/") if x]
            if len(partes) != 4:
                self._json(404, {"erro": "anexo não existe"})
                return
            try:
                area = api.esc.area_de_tarefa(partes[2])
            except KeyError:
                self._json(404, {"erro": "tarefa não existe"})
                return
            caminho = area.caminho_do_anexo(partes[2], partes[3])
            if caminho is None:
                self._json(404, {"erro": "anexo não existe"})
                return
            tipo = mimetypes.guess_type(str(caminho))[0] or "application/octet-stream"
            corpo = caminho.read_bytes()
            nome = caminho.name.split("_", 1)[-1]
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + urllib.request.quote(nome))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path.startswith("/api/anexos/"):
                self._anexo()
            elif self.path.startswith("/api/"):
                self._api("GET")
            else:
                self._estatico()

        def do_POST(self):
            self._api("POST")

        def do_PATCH(self):
            self._api("PATCH")

        def do_DELETE(self):
            self._api("DELETE")

        def do_PUT(self):
            self._api("PUT")

    return Handler


def porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def versao_no_ar(porta: int) -> str:
    """A versão do código do servidor que está respondendo na porta ('' se não for o Gestor de Demandas)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/versao", timeout=3) as r:
            return str(json.loads(r.read().decode("utf-8")).get("codigo", "") or "")
    except Exception:
        return ""


def encerrar_antigo(porta: int) -> None:
    """Pede ao servidor antigo para sair; se ele não responder à rota, derruba pelo PID."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/encerrar", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3):
            return
    except Exception:
        pass
    try:
        saida = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=10).stdout
        for linha in saida.splitlines():
            partes = linha.split()
            if len(partes) >= 5 and partes[1].endswith(f":{porta}") and partes[3] == "LISTENING":
                pid = int(partes[4])
                if pid != os.getpid():
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
    except Exception as erro:
        registrar(f"não consegui encerrar o servidor antigo: {erro}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Servidor do Gestor de Demandas.")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = só esta máquina (padrão); 0.0.0.0 = servidor central, todo mundo abre pelo nome da máquina")
    ap.add_argument("--dados", default=str(dados.RAIZ_DADOS),
                    help="pasta dos dados quando não há departamentos.json (padrão: dados/ ao lado do servidor.py)")
    ap.add_argument("--departamentos", default="", help="outro departamentos.json (testes)")
    ap.add_argument("--usuarios", default="", help="outro usuarios.json (testes); '-' desliga o login mesmo que exista")
    ap.add_argument("--clientes", default="", help="o clientes.json (padrão: <dados>/clientes.json; nasce com cinco clientes de exemplo)")
    ap.add_argument("--local", default=str(LOCAL), help="pasta de configuração desta máquina (avisos.json); padrão %%LOCALAPPDATA%%\\GestorDemandas")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--sem-avisos", action="store_true", help="não dispara balões do Windows (testes)")
    args = ap.parse_args()

    endereco = f"http://127.0.0.1:{args.porta}/"
    if not porta_livre(args.porta):
        if versao_no_ar(args.porta) == VERSAO_CODIGO:
            # já está rodando esta mesma versão: só mostra a página
            if not args.sem_navegador:
                webbrowser.open(endereco)
            return 0
        # é um servidor de versão antiga (ou de antes de existir versão): pede para ele sair
        encerrar_antigo(args.porta)
        for _ in range(40):
            if porta_livre(args.porta):
                break
            time.sleep(0.25)
        else:
            print("a porta continua ocupada por um servidor antigo; feche-o e abra de novo")
            if not args.sem_navegador:
                webbrowser.open(endereco)
            return 1

    arquivo_clientes = Path(args.clientes) if args.clientes else Path(args.dados) / "clientes.json"
    indice = clientes.carregar(arquivo_clientes)
    for aviso in indice.avisos:
        registrar(f"clientes: {aviso}")
    from nucleo import escritorio as mod_esc
    arquivo_dep = Path(args.departamentos) if args.departamentos else mod_esc.ARQUIVO_DEPARTAMENTOS
    if args.departamentos == "-":  # testes: ignora o departamentos.json do app
        arquivo_dep = Path(args.dados) / "_sem_departamentos.json"
    esc = Escritorio(indice, arquivo=arquivo_dep, pasta_padrao=Path(args.dados))
    if not esc.acessiveis():
        registrar("nenhum departamento acessível: " + "; ".join(f"{d.nome}: {d.erro}" for d in esc.departamentos))
    from nucleo.avisos import Avisos
    avisos = Avisos(esc, Path(args.local) / ("avisos.json" if not args.departamentos else f"avisos-{args.porta}.json"))
    if not args.sem_avisos:
        avisos.iniciar()
    # login (modelo A): usuarios.json ao lado do departamentos.json; sem o arquivo, fica desligado
    usuarios = None
    if args.usuarios != "-":
        arquivo_usuarios = Path(args.usuarios) if args.usuarios else arquivo_dep.with_name("usuarios.json")
        usuarios = Usuarios(arquivo_usuarios)
        if usuarios.ligado:
            print(f"login ligado: {len(usuarios.usuarios)} usuário(s) em {arquivo_usuarios}")
    api = Api(esc, avisos, usuarios)
    servidor = ThreadingHTTPServer((args.host, args.porta), fazer_handler(api))
    api.servidor = servidor
    servidor.daemon_threads = True
    if not args.sem_navegador:
        threading.Timer(0.6, lambda: webbrowser.open(endereco)).start()
    print(f"Gestor de Demandas em {endereco}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
