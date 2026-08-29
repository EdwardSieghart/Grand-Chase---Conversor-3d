@echo off
REM Gera o executavel do Grand Chase 3D Importer para WINDOWS.
REM
REM Saida: dist\windows\gc3d.exe — um arquivo unico, que abre a interface quando
REM chamado sem argumentos e age como linha de comando quando recebe um
REM subcomando (convert, batch ou info).
REM
REM Requisitos: Python 3.10 ou mais novo, instalado com a opcao
REM "tcl/tk and IDLE" marcada (vem marcada por padrao; e o que fornece a
REM interface grafica).
REM
REM Uso:
REM   build\windows\build.bat
REM   build\windows\build.bat --test
REM
REM Nao e preciso rodar isto a mao para publicar: o GitHub Actions compila o .exe
REM num Windows de verdade a cada tag (veja .github/workflows/release.yml). Este
REM script serve para quem quiser compilar na propria maquina.

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
    echo     %PYTHON% gc3d_app.py
    echo     %PYTHON% gc3d_app.py --help
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
echo ==^> Pronto:
dir /b dist\windows
echo.
echo Teste rapido:
echo     dist\windows\gc3d.exe --version
echo     dist\windows\gc3d.exe              (abre a interface)

endlocal
