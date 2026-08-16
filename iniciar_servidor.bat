@echo off
title Extrator de Questoes - Servidor Local
echo =======================================================================
echo           INICIALIZADOR PORTATIL DO EXTRATOR DE QUESTOES
echo =======================================================================
echo.

:: 1. Verifica se o Python ou o Launcher do Python (py) esta instalado
set "PYTHON_CMD="

py -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
) else (
    python -c "import sys" >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] Python nao encontrado neste computador!
    echo Por favor, instale o Python 3.10 ou superior antes de rodar o extrator.
    echo Baixe em: https://www.python.org/downloads/
    echo.
    pause
    exit /b
)

:: 2. Instala as dependencias do requirements.txt usando o interpretador correto
echo [*] Verificando e instalando dependencias (isso pode levar alguns segundos)...
%PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [WARNING] Algumas dependencias falharam ao instalar automaticamente.
    echo Tentando prosseguir mesmo assim...
)
echo [SUCCESS] Dependencias validadas!
echo.

:: 3. Inicia o Flask
echo [*] Iniciando o servidor Flask local...
start http://localhost:5000
%PYTHON_CMD% "%~dp0app.py"

pause
