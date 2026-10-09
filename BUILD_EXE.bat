@echo off
chcp 65001 > nul
title SDSuper - Compilar Utilitário Executável
echo.
echo =====================================================================
echo  [SDSUPER] COMPILANDO EXECUTÁVEL PORTÁTIL COM NOVO VISUAL STITCH
echo =====================================================================
echo.

cd /d "%~dp0"

echo [*] Limpando compilações anteriores...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [*] Executando PyInstaller...
python -m PyInstaller --clean Utilitario_SDSuper.spec

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [*] Copiando executável final para a raiz do projeto...
    copy /y "dist\Utilitario_SDSuper.exe" "Utilitario_SDSuper.exe" > nul
    echo.
    echo [SUCESSO] Utilitario_SDSuper.exe compilado com sucesso com o novo visual!
    echo.
) else (
    echo.
    echo [ERRO] Falha ao compilar com PyInstaller.
    echo.
)

pause
