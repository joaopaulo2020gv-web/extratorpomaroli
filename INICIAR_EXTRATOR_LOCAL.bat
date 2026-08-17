@echo off
title Extrator de Questoes Pomaroli - Painel Visual
cd /d "%~dp0"
echo =======================================================================
echo           EXTRATOR DE QUESTOES POMAROLI - INICIANDO
echo =======================================================================
echo.
echo [*] Abrindo o Extrator Visual no seu navegador...
start http://localhost:5000
py "%~dp0app.py" 2>nul || python "%~dp0app.py"
pause
