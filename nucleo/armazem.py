"""Onde os dados moram: arquivos JSON (o padrão) ou um banco SQLite (modelo A, servidor central).

A `Area` não sabe qual é: ela pede e grava coleções, tarefas, snapshots, eventos, lixeira,
anexos e notificações por esta interface, e cada armazém faz do seu jeito.

- `ArmazemJSON`: a pasta `dados\\` de sempre — espacos.json, listas.json, uma tarefa por arquivo
  em `tarefas\\`, `historico\\<id>\\` com os snapshots, `lixeira\\`, `eventos.jsonl`, `anexos\\`,
  `notificacoes.json`, `versao.txt`. Várias máquinas podem gravar na mesma pasta (escrita atômica),
  e `versao.txt` é como uma percebe a outra.
- `ArmazemSQLite`: um arquivo `demandas.db` (WAL). **Só um processo grava**: é para o servidor
  central (modelo A), rodando na máquina do escritório com o banco no disco local dela. Em pasta de
  rede com vários servidores, o SQLite corrompe — por isso não é o padrão.

Trocar: `Area(..., armazem="sqlite")`, ou `"armazem": "sqlite"` no departamento em
`departamentos.json`, ou um `demandas.db` já existente na pasta. Na primeira abertura em SQLite,
o que existe em JSON é importado (os JSON ficam lá, intocados, como cópia). `exportar_json()` faz
o caminho de volta a qualquer hora (é o backup diário).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from pathlib import Path

SNAPSHOTS = 20
COLECOES = ("espacos", "listas", "modelos", "aprendizado", "triagem", "equipe", "notificacoes")


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


def escolher(raiz: Path, pedido: str = ""):
    """O armazém certo para a pasta: SQLite se pedido ou se já há um demandas.db; senão JSON."""
    raiz = Path(raiz)
    if pedido == "sqlite" or (not pedido and (raiz / "demandas.db").is_file()):
        return ArmazemSQLite(raiz)
    return ArmazemJSON(raiz)


# ====================================================================== JSON
class ArmazemJSON:
    nome = "json"

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.pasta_tarefas = self.raiz / "tarefas"
        self.pasta_historico = self.raiz / "historico"
        self.pasta_lixeira = self.raiz / "lixeira"
        self.pasta_anexos = self.raiz / "anexos"
        # a pasta tarefas\ nasce na primeira gravação (o SQLite também instancia este armazém para importar)

    # ---- coleções (espacos, listas, modelos, aprendizado, triagem, equipe, notificacoes)
    def ler_colecao(self, nome: str, padrao):
        return _ler_json(self.raiz / f"{nome}.json", padrao)

    def gravar_colecao(self, nome: str, dados) -> None:
        _gravar_json(self.raiz / f"{nome}.json", dados)

    # ---- tarefas
    def ler_tarefas(self) -> tuple:
        """({id: tarefa}, [avisos])."""
        tarefas, avisos = {}, []
        for arquivo in self.pasta_tarefas.glob("*.json"):
            t = _ler_json(arquivo, None)
            if isinstance(t, dict) and t.get("id"):
                tarefas[t["id"]] = t
            else:
                avisos.append(f"{arquivo.name}: não li")
        return tarefas, avisos

    def gravar_tarefa(self, t: dict) -> None:
        _gravar_json(self.pasta_tarefas / f"{t['id']}.json", t)

    def snapshot(self, t: dict) -> None:
        try:
            pasta = self.pasta_historico / t["id"]
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{dt.datetime.now():%Y%m%d-%H%M%S-%f}.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            for velho in sorted(pasta.glob("*.json"))[:-SNAPSHOTS]:
                velho.unlink(missing_ok=True)
        except OSError:
            pass

    def snapshots(self, tid: str) -> list:
        pasta = self.pasta_historico / tid
        if not pasta.is_dir():
            return []
        saida = []
        for arquivo in sorted(pasta.glob("*.json")):
            t = _ler_json(arquivo, None)
            if isinstance(t, dict):
                saida.append(t)
        return saida

    def para_lixeira(self, tid: str) -> None:
        origem = self.pasta_tarefas / f"{tid}.json"
        self.pasta_lixeira.mkdir(parents=True, exist_ok=True)
        if origem.is_file():
            os.replace(origem, self.pasta_lixeira / f"{tid}-{dt.datetime.now():%Y%m%d-%H%M%S}.json")

    def lixeira(self) -> list:
        """[(tarefa, apagada_em ISO)], mais recente primeiro."""
        saida = []
        if not self.pasta_lixeira.is_dir():
            return saida
        for arquivo in sorted(self.pasta_lixeira.glob("*.json"), reverse=True):
            t = _ler_json(arquivo, None)
            if not isinstance(t, dict):
                continue
            carimbo = arquivo.stem.rsplit("-", 2)
            quando = f"{carimbo[-2][:4]}-{carimbo[-2][4:6]}-{carimbo[-2][6:]}T{carimbo[-1][:2]}:{carimbo[-1][2:4]}" if len(carimbo) == 3 else ""
            saida.append((t, quando))
        return saida

    def tirar_da_lixeira(self, tid: str) -> dict | None:
        candidatos = sorted(self.pasta_lixeira.glob(f"{tid}-*.json"), reverse=True) if self.pasta_lixeira.is_dir() else []
        if not candidatos:
            return None
        t = _ler_json(candidatos[0], None)
        if not isinstance(t, dict) or t.get("id") != tid:
            return None
        for c in candidatos:
            try:
                c.unlink()
            except OSError:
                pass
        return t

    # ---- versão (como outra máquina percebe a mudança)
    def versao(self) -> int:
        try:
            return int((self.raiz / "versao.txt").read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def gravar_versao(self, v: int) -> None:
        try:
            (self.raiz / "versao.txt").write_text(str(v), encoding="utf-8")
        except OSError:
            pass

    # ---- eventos
    def evento(self, ev: dict) -> None:
        try:
            with open(self.raiz / "eventos.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def eventos(self):
        """Do mais recente para o mais antigo (gerador de dicts)."""
        caminho = self.raiz / "eventos.jsonl"
        if not caminho.is_file():
            return
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for linha in reversed(linhas):
            try:
                yield json.loads(linha)
            except ValueError:
                continue

    # ---- anexos
    def gravar_anexo(self, tid: str, aid: str, nome: str, conteudo: bytes) -> None:
        pasta = self.pasta_anexos / tid
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"{aid}_{nome}").write_bytes(conteudo)

    def caminho_anexo(self, tid: str, aid: str, nome: str) -> Path | None:
        caminho = self.pasta_anexos / tid / f"{aid}_{nome}"
        return caminho if caminho.is_file() else None

    def apagar_anexo(self, tid: str, aid: str, nome: str) -> None:
        caminho = self.pasta_anexos / tid / f"{aid}_{nome}"
        try:
            caminho.unlink()
        except OSError:
            pass

    def exportar_json(self, destino: Path) -> Path:
        """Um arquivo só com tudo (backup)."""
        tarefas, _a = self.ler_tarefas()
        pacote = {"exportado_em": dt.datetime.now().isoformat(timespec="seconds"), "armazem": self.nome,
                  "colecoes": {n: self.ler_colecao(n, None) for n in COLECOES}, "tarefas": list(tarefas.values())}
        destino = Path(destino)
        _gravar_json(destino, pacote)
        return destino


# ====================================================================== SQLite
class ArmazemSQLite:
    """`demandas.db` na pasta. Tudo em JSON dentro de colunas TEXT — a lógica continua em Python."""
    nome = "sqlite"
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS colecoes (nome TEXT PRIMARY KEY, dados TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tarefas (id TEXT PRIMARY KEY, lista TEXT, status TEXT, chave TEXT, atualizada TEXT, dados TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_tarefas_lista ON tarefas(lista);
    CREATE TABLE IF NOT EXISTS lixeira (n INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, apagada_em TEXT, dados TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS snapshots (n INTEGER PRIMARY KEY AUTOINCREMENT, tarefa TEXT, quando TEXT, dados TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_snap_tarefa ON snapshots(tarefa);
    CREATE TABLE IF NOT EXISTS eventos (n INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT, tarefa TEXT, pessoa TEXT, tipo TEXT, dados TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_ev_tarefa ON eventos(tarefa);
    CREATE TABLE IF NOT EXISTS anexos (tarefa TEXT, id TEXT, nome TEXT, conteudo BLOB, PRIMARY KEY (tarefa, id));
    CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
    """

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.caminho = self.raiz / "demandas.db"
        self.tranca = threading.RLock()
        novo = not self.caminho.is_file()
        self.con = sqlite3.connect(str(self.caminho), check_same_thread=False, isolation_level=None)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(self.ESQUEMA)
        if novo or not self.con.execute("SELECT 1 FROM meta WHERE chave='importado'").fetchone():
            self._importar_json()

    def _importar_json(self) -> None:
        """Primeira abertura: o que houver em JSON na mesma pasta entra no banco (os JSON ficam)."""
        antigo = ArmazemJSON(self.raiz)
        with self.tranca:
            for nome in COLECOES:
                dados = antigo.ler_colecao(nome, None)
                if dados is not None and not self.con.execute("SELECT 1 FROM colecoes WHERE nome=?", (nome,)).fetchone():
                    self.con.execute("INSERT INTO colecoes(nome, dados) VALUES (?, ?)", (nome, json.dumps(dados, ensure_ascii=False)))
            tarefas, _a = antigo.ler_tarefas()
            for t in tarefas.values():
                self.gravar_tarefa(t)
                for s in antigo.snapshots(t["id"]):
                    self.con.execute("INSERT INTO snapshots(tarefa, quando, dados) VALUES (?, ?, ?)", (t["id"], s.get("atualizada", ""), json.dumps(s, ensure_ascii=False)))
            for t, quando in antigo.lixeira():
                self.con.execute("INSERT INTO lixeira(id, apagada_em, dados) VALUES (?, ?, ?)", (t.get("id", ""), quando, json.dumps(t, ensure_ascii=False)))
            for ev in reversed(list(antigo.eventos())):
                self.evento(ev)
            if antigo.pasta_anexos.is_dir():
                for pasta in antigo.pasta_anexos.iterdir():
                    if pasta.is_dir():
                        for arq in pasta.iterdir():
                            aid, _sep, nome = arq.name.partition("_")
                            try:
                                self.gravar_anexo(pasta.name, aid, nome, arq.read_bytes())
                            except OSError:
                                pass
            self.con.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES ('importado', ?)", (dt.datetime.now().isoformat(timespec="seconds"),))
            self.con.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES ('versao', ?)", (str(antigo.versao()),))

    # ---- coleções
    def ler_colecao(self, nome: str, padrao):
        with self.tranca:
            linha = self.con.execute("SELECT dados FROM colecoes WHERE nome=?", (nome,)).fetchone()
        if not linha:
            return padrao
        try:
            return json.loads(linha[0])
        except ValueError:
            return padrao

    def gravar_colecao(self, nome: str, dados) -> None:
        with self.tranca:
            self.con.execute("INSERT OR REPLACE INTO colecoes(nome, dados) VALUES (?, ?)", (nome, json.dumps(dados, ensure_ascii=False)))

    # ---- tarefas
    def ler_tarefas(self) -> tuple:
        tarefas, avisos = {}, []
        with self.tranca:
            for (dados,) in self.con.execute("SELECT dados FROM tarefas"):
                try:
                    t = json.loads(dados)
                    tarefas[t["id"]] = t
                except (ValueError, KeyError, TypeError):
                    avisos.append("uma tarefa do banco não li")
        return tarefas, avisos

    def gravar_tarefa(self, t: dict) -> None:
        with self.tranca:
            self.con.execute("INSERT OR REPLACE INTO tarefas(id, lista, status, chave, atualizada, dados) VALUES (?, ?, ?, ?, ?, ?)",
                             (t["id"], t.get("lista", ""), t.get("status", ""), t.get("chave", ""), t.get("atualizada", ""), json.dumps(t, ensure_ascii=False)))

    def snapshot(self, t: dict) -> None:
        with self.tranca:
            self.con.execute("INSERT INTO snapshots(tarefa, quando, dados) VALUES (?, ?, ?)", (t["id"], t.get("atualizada", ""), json.dumps(t, ensure_ascii=False)))
            self.con.execute("DELETE FROM snapshots WHERE tarefa=? AND n NOT IN (SELECT n FROM snapshots WHERE tarefa=? ORDER BY n DESC LIMIT ?)", (t["id"], t["id"], SNAPSHOTS))

    def snapshots(self, tid: str) -> list:
        with self.tranca:
            linhas = self.con.execute("SELECT dados FROM snapshots WHERE tarefa=? ORDER BY n", (tid,)).fetchall()
        saida = []
        for (dados,) in linhas:
            try:
                saida.append(json.loads(dados))
            except ValueError:
                pass
        return saida

    def para_lixeira(self, tid: str) -> None:
        with self.tranca:
            linha = self.con.execute("SELECT dados FROM tarefas WHERE id=?", (tid,)).fetchone()
            if linha:
                self.con.execute("INSERT INTO lixeira(id, apagada_em, dados) VALUES (?, ?, ?)", (tid, dt.datetime.now().isoformat(timespec="minutes"), linha[0]))
            self.con.execute("DELETE FROM tarefas WHERE id=?", (tid,))

    def lixeira(self) -> list:
        with self.tranca:
            linhas = self.con.execute("SELECT dados, apagada_em FROM lixeira ORDER BY n DESC LIMIT 300").fetchall()
        saida = []
        for dados, quando in linhas:
            try:
                saida.append((json.loads(dados), quando or ""))
            except ValueError:
                pass
        return saida

    def tirar_da_lixeira(self, tid: str) -> dict | None:
        with self.tranca:
            linha = self.con.execute("SELECT dados FROM lixeira WHERE id=? ORDER BY n DESC LIMIT 1", (tid,)).fetchone()
            if not linha:
                return None
            self.con.execute("DELETE FROM lixeira WHERE id=?", (tid,))
        try:
            return json.loads(linha[0])
        except ValueError:
            return None

    # ---- versão
    def versao(self) -> int:
        with self.tranca:
            linha = self.con.execute("SELECT valor FROM meta WHERE chave='versao'").fetchone()
        try:
            return int(linha[0]) if linha else 0
        except (TypeError, ValueError):
            return 0

    def gravar_versao(self, v: int) -> None:
        with self.tranca:
            self.con.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES ('versao', ?)", (str(v),))

    # ---- eventos
    def evento(self, ev: dict) -> None:
        with self.tranca:
            self.con.execute("INSERT INTO eventos(quando, tarefa, pessoa, tipo, dados) VALUES (?, ?, ?, ?, ?)",
                             (ev.get("quando", ""), ev.get("tarefa", ""), ev.get("pessoa", ""), ev.get("tipo", ""), json.dumps(ev, ensure_ascii=False)))

    def eventos(self):
        with self.tranca:
            linhas = self.con.execute("SELECT dados FROM eventos ORDER BY n DESC LIMIT 5000").fetchall()
        for (dados,) in linhas:
            try:
                yield json.loads(dados)
            except ValueError:
                continue

    # ---- anexos (no banco mesmo; o servidor central não tem pasta compartilhada)
    def gravar_anexo(self, tid: str, aid: str, nome: str, conteudo: bytes) -> None:
        with self.tranca:
            self.con.execute("INSERT OR REPLACE INTO anexos(tarefa, id, nome, conteudo) VALUES (?, ?, ?, ?)", (tid, aid, nome, sqlite3.Binary(conteudo)))

    def caminho_anexo(self, tid: str, aid: str, nome: str) -> Path | None:
        """O servidor serve pelo caminho: escreve numa pasta temporária e devolve."""
        with self.tranca:
            linha = self.con.execute("SELECT conteudo FROM anexos WHERE tarefa=? AND id=?", (tid, aid)).fetchone()
        if not linha:
            return None
        pasta = self.raiz / "anexos_cache" / tid
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{aid}_{nome}"
        if not caminho.is_file():
            caminho.write_bytes(bytes(linha[0]))
        return caminho

    def apagar_anexo(self, tid: str, aid: str, nome: str) -> None:
        with self.tranca:
            self.con.execute("DELETE FROM anexos WHERE tarefa=? AND id=?", (tid, aid))
        try:
            (self.raiz / "anexos_cache" / tid / f"{aid}_{nome}").unlink()
        except OSError:
            pass

    def exportar_json(self, destino: Path) -> Path:
        tarefas, _a = self.ler_tarefas()
        pacote = {"exportado_em": dt.datetime.now().isoformat(timespec="seconds"), "armazem": self.nome,
                  "colecoes": {n: self.ler_colecao(n, None) for n in COLECOES}, "tarefas": list(tarefas.values())}
        destino = Path(destino)
        _gravar_json(destino, pacote)
        return destino
