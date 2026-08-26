@echo off
REM Gera os executaveis do Grand Chase 3D Importer para Windows.
REM
REM Produz em dist\:
REM   gc3d.exe      - linha de comando
REM   gc3d-gui.exe  - interface grafica
REM
REM Requisitos: Python 3.10 ou mais novo, com a opcao "tcl/tk and IDLE" marcada
REM na instalacao (necessaria para a interface grafica).
REM
REM Uso:
REM   build\build_windows.bat
REM   build\build_windows.bat --test

setlocal enabledelayedexpansion
cd /d "%~dp0.."

if "%PYTHON%"=="" set PYTHON=python

echo ==^> Projeto: %CD%
%PYTHON% --version
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    echo Instale de https://www.python.org/downloads/ marcando "Add Python to PATH".
    exit /b 1
)

if "%1"=="--test" (
    echo ==^> Rodando testes
    %PYTHON% -m unittest discover -s tests -t .
    if errorlevel 1 (
        echo ERRO: testes falharam, build abortado.
        exit /b 1
    )
)

%PYTHON% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo ==^> PyInstaller nao encontrado.
    echo     Instale com:  %PYTHON% -m pip install pyinstaller
    echo.
    echo     Sem o PyInstaller o programa continua funcionando pelo Python:
    echo       %PYTHON% gc3d_cli.py --help
    echo       %PYTHON% gc3d_gui.py
    exit /b 1
)

echo ==^> Limpando builds anteriores
if exist dist rmdir /s /q dist
if exist build\pyinstaller rmdir /s /q build\pyinstaller

echo ==^> Empacotando
%PYTHON% -m PyInstaller build\gc3d.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
if errorlevel 1 (
    echo ERRO: PyInstaller falhou.
    exit /b 1
)

echo.
echo ==^> Pronto. Executaveis em dist\:
dir /b dist
echo.
echo Teste rapido:
echo   dist\gc3d.exe --help
echo   dist\gc3d-gui.exe

endlocal
