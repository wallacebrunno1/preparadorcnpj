@echo off
title Utilitario SDSuper - Replicacao de Filiais em Massa
cd /d "%~dp0"
echo ========================================================
echo   Iniciando SDSuper - Utilitario de Filiais e Permissoes
echo ========================================================
echo.

rem 1. Prioridade maxima: Executavel Standalone 100% integrado (nao precisa de Python)
if exist "%~dp0Utilitario_SDSuper.exe" (
    echo [OK] Iniciando aplicativo standalone integrado...
    "%~dp0Utilitario_SDSuper.exe"
    goto fim
)

rem 2. Segunda opcao: Executavel na pasta dist
if exist "%~dp0dist\Utilitario_SDSuper\Utilitario_SDSuper.exe" (
    echo [OK] Iniciando aplicativo a partir da pasta dist...
    "%~dp0dist\Utilitario_SDSuper\Utilitario_SDSuper.exe"
    goto fim
)

rem 3. Terceira opcao: Interpretador Python local
where python >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Iniciando via Python local...
    python server.py
    goto fim
)

echo ========================================================
echo [ERRO] Python nao esta instalado e Utilitario_SDSuper.exe
echo        nao foi encontrado nesta pasta.
echo ========================================================
echo.
pause

:fim
