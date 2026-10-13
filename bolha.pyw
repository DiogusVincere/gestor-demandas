"""A bolha do Gestor de Demandas: uma janela pequena, sem moldura, sempre por cima, no canto da tela.

    pythonw bolha.pyw

- Recolhida, é um pino redondo com o número de tarefas de hoje. Clique (ou **Ctrl+Shift+D** de
  qualquer programa) abre a caixa de registrar demanda — a mesma inteligência da página, sem navegador.
- "⤢ tudo" abre o app completo numa janela própria. "esconder" some da tela; o atalho traz de volta.
- Arrasta pelo cabeçalho; lembra a posição. Abrir de novo com a bolha já aberta só a mostra.
- Sobe o servidor local se ele não estiver no ar (o mesmo `servidor.py` da página).

Precisa de `pywebview` (pip install pywebview) e do WebView2 do Windows, que já vem com o Edge.
Sem pywebview, abre a página da bolha no navegador — pior, mas funciona.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PASTA = Path(os.path.abspath(__file__)).parent
PORTA = 8731
ENDERECO = f"http://127.0.0.1:{PORTA}"
PORTA_SINAL = 8732                       # uma segunda bolha só avisa a primeira: "mostra"
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GestorDemandas"
CONFIG = LOCAL / "bolha.json"
TAM_BOLHA = (200, 60)                    # o WebView2 não fica transparente nem menor que isso: a bolha é uma barrinha
TAM_CAIXA = (540, 470)                   # cabe a linha, as fichas e a lista do dia
MARGEM = 14

try:
    import webview
except ImportError:
    webview = None


def registrar(texto: str) -> None:
    try:
        LOCAL.mkdir(parents=True, exist_ok=True)
        with (LOCAL / "bolha.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def servidor_no_ar() -> bool:
    try:
        with urllib.request.urlopen(ENDERECO + "/api/versao", timeout=2):
            return True
    except Exception:
        return False


def subir_servidor() -> bool:
    if servidor_no_ar():
        return True
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.name.lower().startswith("python") else exe
    try:
        subprocess.Popen([str(pyw if pyw.exists() else exe), str(PASTA / "servidor.py"), "--sem-navegador"], cwd=str(PASTA),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as erro:
        registrar(f"não subiu o servidor: {erro}")
        return False
    for _ in range(80):
        if servidor_no_ar():
            return True
        time.sleep(0.25)
    return False


def area_de_trabalho() -> tuple:
    """(esquerda, topo, direita, base) da tela sem a barra de tarefas."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return 0, 0, 1366, 728


class Api:
    """O que a página chama por `window.pywebview.api`."""

    def __init__(self):
        self._janela = None
        self._completa = None
        self._config = {"x": None, "y": None}
        try:
            self._config.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.aberta = False

    def _gravar(self) -> None:
        try:
            LOCAL.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps(self._config), encoding="utf-8")
        except OSError:
            pass

    def _canto(self) -> tuple:
        """Onde a bolha fica recolhida: o que foi guardado, ou o canto inferior direito."""
        e, t, d, b = area_de_trabalho()
        x = self._config.get("x")
        y = self._config.get("y")
        if x is None or y is None:
            x, y = d - TAM_BOLHA[0] - MARGEM, b - TAM_BOLHA[1] - MARGEM
        x = max(e, min(int(x), d - TAM_BOLHA[0]))
        y = max(t, min(int(y), b - TAM_BOLHA[1]))
        return x, y

    # ---- chamadas da página
    def abrir(self):
        self.aberta = True
        self.redimensionar(*TAM_CAIXA)
        return True

    def redimensionar(self, largura: int, altura: int):
        if self._janela is None:
            return False
        e, t, d, b = area_de_trabalho()
        bx, by = self._canto()
        # a caixa cresce a partir do canto da bolha, sem sair da tela
        x = bx + TAM_BOLHA[0] - largura if bx + TAM_BOLHA[0] - largura >= e else e
        y = by + TAM_BOLHA[1] - altura if by + TAM_BOLHA[1] - altura >= t else t
        self._janela.resize(largura, altura)
        self._janela.move(x, y)
        return True

    def recolher(self):
        self.aberta = False
        if self._janela is None:
            return False
        x, y = self._canto()
        self._janela.resize(*TAM_BOLHA)
        self._janela.move(x, y)
        return True

    def abrir_tudo(self, tarefa_id: str = ""):
        """O app completo numa janela própria; com `tarefa_id`, já abre o painel daquela tarefa."""
        url = ENDERECO + "/" + (f"?tarefa={tarefa_id}" if tarefa_id else "")
        if webview is None:
            webbrowser.open(url)
            return True
        if self._completa is not None:
            try:
                if tarefa_id:
                    self._completa.load_url(url)
                self._completa.show()
                self._completa.restore()
                return True
            except Exception:
                self._completa = None
        e, t, d, b = area_de_trabalho()
        largura, altura = min(1320, d - e - 40), min(860, b - t - 40)
        self._completa = webview.create_window("Gestor de Demandas", url, width=largura, height=altura,
                                              x=e + (d - e - largura) // 2, y=t + (b - t - altura) // 2, min_size=(900, 560))
        self._completa.events.closed += self._fechou_completa
        return True

    def _fechou_completa(self):
        self._completa = None

    def esconder(self):
        if self._janela is not None:
            self.recolher()
            self._janela.hide()
        return True

    def mostrar(self):
        if self._janela is not None:
            self._janela.show()
        return True

    def mostrar_balao(self):
        """Um aviso chegou com a bolha recolhida: a página mostra o balão; aqui só garante que está visível."""
        if self._janela is not None:
            self._janela.show()
        return True

    def mover(self, dx: int, dy: int):
        """Arrasto feito pela página (mousedown/mousemove): desloca a janela, sem sair da tela."""
        if self._janela is None:
            return False
        try:
            e, t, d, b = area_de_trabalho()
            x = max(e, min(int(self._janela.x) + int(dx), d - int(self._janela.width)))
            y = max(t, min(int(self._janela.y) + int(dy), b - int(self._janela.height)))
            self._janela.move(x, y)
        except Exception as erro:
            registrar(f"mover: {erro!r}")
            return False
        return True

    def guardar_posicao(self):
        """Depois de arrastar: o canto inferior direito da janela vira o canto da barrinha (recolhida ou aberta)."""
        if self._janela is None:
            return False
        try:
            self._config["x"] = int(self._janela.x) + int(self._janela.width) - TAM_BOLHA[0]
            self._config["y"] = int(self._janela.y) + int(self._janela.height) - TAM_BOLHA[1]
            self._gravar()
        except Exception as erro:
            registrar(f"guardar_posicao: {erro!r}")
        return True

    # ---- abrir com o Windows: um .bat na pasta Inicializar do usuário
    def _atalho_inicio(self) -> Path:
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Gestor de Demandas - bolha.bat"

    def inicio_instalado(self) -> bool:
        return self._atalho_inicio().is_file()

    def instalar_inicio(self) -> bool:
        try:
            exe = Path(sys.executable)
            pyw = exe.with_name("pythonw.exe") if exe.name.lower().startswith("python") else exe
            atalho = self._atalho_inicio()
            atalho.parent.mkdir(parents=True, exist_ok=True)
            atalho.write_text("@echo off\r\n" f'start "" "{pyw}" "{PASTA / "bolha.pyw"}"\r\n', encoding="cp1252", errors="replace")
            return True
        except OSError as erro:
            registrar(f"não instalou no início do Windows: {erro}")
            return False

    def desinstalar_inicio(self) -> bool:
        try:
            self._atalho_inicio().unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def sair(self):
        try:
            if self._completa is not None:
                self._completa.destroy()
            if self._janela is not None:
                self._janela.destroy()
        finally:
            os._exit(0)


def escutar_sinal(api: Api) -> None:
    """Uma bolha já aberta recebe 'mostra' da que tentou abrir depois."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", PORTA_SINAL))
        s.listen(2)
    except OSError:
        return
    while True:
        try:
            c, _ = s.accept()
            c.close()
            api.mostrar()
            if api._janela is not None:
                api._janela.evaluate_js("abrirDaTecla()")
        except Exception as erro:
            registrar(f"sinal: {erro!r}")


def ja_tem_bolha() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORTA_SINAL), timeout=1):
            return True
    except OSError:
        return False


def atalho_global(api: Api) -> None:
    """Ctrl+Shift+D em qualquer programa abre a caixa (RegisterHotKey do Windows, sem biblioteca)."""
    try:
        user32 = ctypes.windll.user32
        MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
        if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, ord("D")):
            registrar("Ctrl+Shift+D já está em uso por outro programa; o atalho não vai funcionar")
            return
        msg = ctypes.wintypes.MSG() if hasattr(ctypes, "wintypes") else None
        if msg is None:
            import ctypes.wintypes as wt
            msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:   # WM_HOTKEY
                api.mostrar()
                if api._janela is not None:
                    api._janela.evaluate_js("abrirDaTecla()")
    except Exception as erro:
        registrar(f"atalho global: {erro}")


def depois_de_abrir(api: Api) -> None:
    api.recolher()
    threading.Thread(target=escutar_sinal, args=(api,), daemon=True).start()
    threading.Thread(target=atalho_global, args=(api,), daemon=True).start()
    # arrastou a bolha: guarda onde ficou
    def vigiar():
        ultimo = None
        while True:
            time.sleep(1.5)
            try:
                # só com a barrinha do tamanho recolhido: com o balão aberto a janela é maior e o canto mudaria
                if api._janela is None or api.aberta or (int(api._janela.width), int(api._janela.height)) != TAM_BOLHA:
                    continue
                atual = (int(api._janela.x), int(api._janela.y))
                if atual != ultimo and ultimo is not None:
                    api.guardar_posicao()
                ultimo = atual
            except Exception:
                pass
    threading.Thread(target=vigiar, daemon=True).start()


def main() -> int:
    if ja_tem_bolha():
        return 0            # a que já está aberta se mostrou
    if not subir_servidor():
        ctypes.windll.user32.MessageBoxW(None, "O servidor do Gestor de Demandas não subiu. Abra o app pelo .bat uma vez e tente de novo.", "Gestor de Demandas", 0x10)
        return 1
    if webview is None:
        webbrowser.open(ENDERECO + "/bolha.html")
        return 0
    api = Api()
    x, y = api._canto()
    try:
        api._janela = webview.create_window("Gestor de Demandas", ENDERECO + "/bolha.html", width=TAM_BOLHA[0], height=TAM_BOLHA[1], x=x, y=y,
                                           frameless=True, on_top=True, resizable=True, easy_drag=False, transparent=False, js_api=api,
                                           min_size=TAM_BOLHA, background_color="#27507A")
        webview.start(func=depois_de_abrir, args=(api,), gui="edgechromium", private_mode=False)
    except Exception as erro:
        registrar(f"a janela nativa não abriu ({erro}); abrindo no navegador")
        webbrowser.open(ENDERECO + "/bolha.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
