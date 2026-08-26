@echo off
REM Gera os executaveis do Grand Chase 3D Importer para WINDOWS.
REM
REM Saida em dist\windows\:
REM   gc3d.exe      - linha de comando
REM   gc3d-gui.exe  - interface grafica
REM
REM Requisitos: Python 3.10 ou mais novo, instalado com a opcao
REM "tcl/tk and IDLE" marcada (vem marcada por padrao; e o que fornece a
REM interface grafica).
REM
REM Uso:
REM   build\windows\build.bat
REM   build\windows\build.bat --test

setlocal
cd /d "%~dp0..\.."

if "%PYTHON%"=="" set PYTHON=python

echo ==^> Grand Chase 3D Importer -- build Windows
echo     projeto: %CD%
%PYTHON% --version
if errorlevel 1 (
    echo.
    echo ERRO: Python nao encontrado no PATH.
    echo Instale de https://www.python.org/downloads/ marcando
    echo "Add Python to PATH" e "tcl/tk and IDLE".
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
    echo.
    echo PyInstaller nao encontrado. Instale com:
    echo     %PYTHON% -m pip install pyinstaller
    echo.
    echo Sem ele o programa continua funcionando pelo Python:
    echo     %PYTHON% gc3d_gui.py
    echo     %PYTHON% gc3d_cli.py --help
    exit /b 1
)

echo ==^> Limpando build anterior
if exist dist\windows rmdir /s /q dist\windows
if exist build\windows\pyinstaller rmdir /s /q build\windows\pyinstaller

echo ==^> Empacotando
%PYTHON% -m PyInstaller build\common\gc3d.spec ^
    --noconfirm --clean ^
    --distpath dist\windows ^
    --workpath build\windows\pyinstaller
if errorlevel 1 (
    echo ERRO: PyInstaller falhou.
    exit /b 1
)

echo.
echo ==^> Pronto. Executaveis em dist\windows\:
dir /b dist\windows
echo.
echo Teste rapido:
echo     dist\windows\gc3d.exe --version
echo     dist\windows\gc3d-gui.exe

endlocal
