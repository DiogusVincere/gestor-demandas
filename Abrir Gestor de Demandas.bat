@echo off
rem Abre o Gestor de Demandas: sobe o servidor local (so nesta maquina) e abre a pagina no navegador.
rem Se ja estiver aberto, so abre a pagina de novo. Os dados ficam em dados\ ao lado deste arquivo.
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw "%~dp0servidor.py" & exit /b)
where pyw >nul 2>nul && (start "" pyw "%~dp0servidor.py" & exit /b)
echo Python nao encontrado neste computador. Instale o Python 3 (python.org) e rode de novo.
pause
