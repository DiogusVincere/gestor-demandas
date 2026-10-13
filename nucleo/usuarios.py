"""Usuários, senhas e sessões — o login do modelo A (servidor central).

`usuarios.json`, ao lado do `departamentos.json`:

    {"usuarios": [
      {"login": "ana", "nome": "Ana Souza", "senha": "pbkdf2$…", "papel": "admin",
       "departamentos": ["Equipe"], "gere": []},
      {"login": "bruno", "nome": "Bruno Martins", "senha": "pbkdf2$…", "papel": "membro",
       "departamentos": ["Equipe"], "gere": []}
    ]}

- **Sem o arquivo (ou vazio), o login fica desligado** e tudo funciona como antes: o nome vem da
  página (`X-Pessoa`) e a segurança é a permissão da pasta (modelo B).
- Com o arquivo, toda rota da API exige sessão (cookie `demandas_sessao`), o nome da pessoa é o
  do cadastro, e o que cada um enxerga é decidido aqui:
  - **membro**: os departamentos em `departamentos`;
  - **gestor**: os seus mais os que `gere`;
  - **admin**: todos, e pode cadastrar usuários e departamentos.
- Senha guardada como PBKDF2-SHA256 (200 mil voltas, sal por usuário). Sessões em
  `sessoes.json` ao lado, válidas por 30 dias; sobrevivem a reiniciar o servidor.

É intranet sem HTTPS: a senha trafega em claro dentro da rede do escritório. Serve para dizer
quem é quem e o que cada um vê; não serve contra quem já está dentro da rede com má intenção.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

PAPEIS = ("membro", "gestor", "admin")
DIAS_SESSAO = 30


def _hash(senha: str, sal: bytes | None = None) -> str:
    sal = sal or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, 200_000)
    return "pbkdf2$" + base64.b64encode(sal).decode() + "$" + base64.b64encode(h).decode()


def _confere(senha: str, guardada: str) -> bool:
    try:
        _p, sal, h = guardada.split("$")
        novo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), base64.b64decode(sal), 200_000)
        return secrets.compare_digest(novo, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


class Usuarios:
    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)
        self.arquivo_sessoes = self.arquivo.with_name("sessoes.json")
        self.tranca = threading.RLock()
        self.usuarios: list = []
        self.sessoes: dict = {}
        self.carregar()

    # ------------------------------------------------------------ carga
    def carregar(self) -> None:
        with self.tranca:
            try:
                dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
                lista = dados.get("usuarios", dados) if isinstance(dados, dict) else dados
                self.usuarios = [self._limpo(u) for u in lista if isinstance(u, dict) and u.get("login")]
            except (OSError, ValueError):
                self.usuarios = []
            # senha escrita em claro no arquivo (primeiro cadastro, à mão): vira hash e o arquivo é regravado
            em_claro = [u for u in self.usuarios if u.get("senha") and not u["senha"].startswith("pbkdf2$")]
            if em_claro:
                for u in em_claro:
                    u["senha"] = _hash(u["senha"])
                try:
                    self.gravar()
                except OSError:
                    pass
            try:
                self.sessoes = json.loads(self.arquivo_sessoes.read_text(encoding="utf-8"))
                if not isinstance(self.sessoes, dict):
                    self.sessoes = {}
            except (OSError, ValueError):
                self.sessoes = {}

    @staticmethod
    def _limpo(u: dict) -> dict:
        return {"login": str(u.get("login", "")).strip().lower(), "nome": str(u.get("nome") or u.get("login", "")).strip(),
                "senha": str(u.get("senha", "")), "papel": u.get("papel") if u.get("papel") in PAPEIS else "membro",
                "departamentos": [str(d).strip() for d in (u.get("departamentos") or []) if str(d).strip()],
                "gere": [str(d).strip() for d in (u.get("gere") or []) if str(d).strip()]}

    def gravar(self) -> None:
        with self.tranca:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps({"usuarios": self.usuarios}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _gravar_sessoes(self) -> None:
        try:
            self.arquivo_sessoes.write_text(json.dumps(self.sessoes), encoding="utf-8")
        except OSError:
            pass

    @property
    def ligado(self) -> bool:
        return bool(self.usuarios)

    # ------------------------------------------------------------ consulta
    def por_login(self, login: str) -> dict | None:
        login = (login or "").strip().lower()
        return next((u for u in self.usuarios if u["login"] == login), None)

    @staticmethod
    def publico(u: dict | None) -> dict | None:
        if not u:
            return None
        return {k: u[k] for k in ("login", "nome", "papel", "departamentos", "gere")}

    def lista(self) -> list:
        return [dict(self.publico(u), tem_senha=bool(u.get("senha"))) for u in self.usuarios]

    @staticmethod
    def pode_ver(u: dict | None, departamento: str) -> bool:
        if not u:
            return False
        if u["papel"] == "admin":
            return True
        return departamento in u["departamentos"] or (u["papel"] == "gestor" and departamento in u["gere"])

    @staticmethod
    def e_admin(u: dict | None) -> bool:
        return bool(u and u["papel"] == "admin")

    # ------------------------------------------------------------ edição (admin)
    def editar(self, lista: list) -> list:
        """A lista inteira. `senha` em claro vira hash; em branco mantém a que tinha."""
        with self.tranca:
            antigos = {u["login"]: u for u in self.usuarios}
            novos = []
            for bruto in lista or []:
                if not isinstance(bruto, dict) or not str(bruto.get("login", "")).strip():
                    continue
                u = self._limpo(bruto)
                senha = str(bruto.get("senha") or "")
                if senha.startswith("pbkdf2$"):
                    u["senha"] = senha
                elif senha:
                    u["senha"] = _hash(senha)
                else:
                    u["senha"] = antigos.get(u["login"], {}).get("senha", "")
                if any(x["login"] == u["login"] for x in novos):
                    continue
                novos.append(u)
            if novos and not any(u["papel"] == "admin" for u in novos):
                raise ValueError("precisa ficar pelo menos um administrador")
            self.usuarios = novos
            self.gravar()
            # quem saiu do cadastro perde a sessão
            vivos = {u["login"] for u in novos}
            self.sessoes = {t: s for t, s in self.sessoes.items() if s.get("login") in vivos}
            self._gravar_sessoes()
            return self.lista()

    def definir_senha(self, login: str, senha: str) -> bool:
        with self.tranca:
            u = self.por_login(login)
            if not u or not senha:
                return False
            u["senha"] = _hash(senha)
            self.gravar()
            return True

    # ------------------------------------------------------------ sessões
    def autenticar(self, login: str, senha: str) -> dict | None:
        u = self.por_login(login)
        if not u or not u.get("senha") or not _confere(senha or "", u["senha"]):
            return None
        return u

    def criar_sessao(self, login: str) -> str:
        with self.tranca:
            token = secrets.token_urlsafe(32)
            agora = dt.datetime.now()
            self.sessoes[token] = {"login": login, "criada": agora.isoformat(timespec="seconds"),
                                   "expira": (agora + dt.timedelta(days=DIAS_SESSAO)).isoformat(timespec="seconds")}
            # limpa as vencidas
            limite = agora.isoformat(timespec="seconds")
            self.sessoes = {t: s for t, s in self.sessoes.items() if s.get("expira", "") > limite}
            self._gravar_sessoes()
            return token

    def sessao(self, token: str) -> dict | None:
        if not token:
            return None
        s = self.sessoes.get(token)
        if not s or s.get("expira", "") <= dt.datetime.now().isoformat(timespec="seconds"):
            return None
        return self.por_login(s.get("login", ""))

    def encerrar_sessao(self, token: str) -> None:
        with self.tranca:
            if token in self.sessoes:
                del self.sessoes[token]
                self._gravar_sessoes()
