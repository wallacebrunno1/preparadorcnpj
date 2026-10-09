@echo off
title SDSuper - Compilar Utilitario Executavel
echo.
echo =====================================================================
echo  [SDSUPER] COMPILANDO EXECUTAVEL PORTATIL COM NOVO VISUAL STITCH
echo =====================================================================
echo.

cd /d "%~dp0"

echo [*] Limpando compilacoes anteriores...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [*] Executando PyInstaller...
python -m PyInstaller --clean Utilitario_SDSuper.spec

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [*] Copiando executavel final para a raiz do projeto...
    copy /y "dist\Utilitario_SDSuper.exe" "Utilitario_SDSuper.exe" > nul
    echo.
    echo [SUCESSO] Utilitario_SDSuper.exe compilado com sucesso!
    echo.
) else (
    echo.
    echo [ERRO] Falha ao compilar com PyInstaller.
    echo.
)
pause
