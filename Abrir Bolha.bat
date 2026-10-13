@echo off
rem A bolha do Gestor de Demandas: fica no canto da tela; Ctrl+Shift+D abre de qualquer programa.
rem Precisa do pywebview (pip install pywebview). Sobe o servidor sozinha se ele nao estiver no ar.
cd /d "%~dp0"
start "" pythonw "%~dp0bolha.pyw"
