@echo off
rem Servidor central (modelo A): roda NA MAQUINA CENTRAL, um processo so, e todo mundo abre
rem http://NOME-DA-MAQUINA:8731 no navegador (ou pela bolha apontada para ela).
rem - usuarios.json ao lado do departamentos.json liga o login (copie de usuarios.exemplo.json).
rem - Para o banco SQLite, ponha "armazem": "sqlite" no departamento em departamentos.json, com a pasta
rem   no disco LOCAL desta maquina (nao em pasta de rede).
cd /d "%~dp0"
python servidor.py --host 0.0.0.0 --sem-navegador
pause
