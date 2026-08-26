#!/usr/bin/env bash
# Gera os executaveis .exe do Windows a PARTIR DO LINUX, usando Wine.
#
# O PyInstaller nao faz cross-compile: ele empacota o interpretador da
# plataforma em que roda. A saida deste script e um .exe de verdade porque o
# PyInstaller roda dentro do Wine, sobre um Python para Windows.
#
# Saida em dist/windows/:
#   gc3d.exe      - linha de comando
#   gc3d-gui.exe  - interface grafica
#
# Na primeira execucao o script baixa e instala, dentro de um prefixo Wine
# proprio, um Python para Windows (embutido) e o PyInstaller. Isso leva alguns
# minutos e precisa de internet. Nas vezes seguintes reaproveita tudo.
#
# Uso:
#   ./build/windows/build_wine.sh
#   ./build/windows/build_wine.sh --clean-prefix   recria o prefixo do zero

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

# Prefixo proprio: nao mexe no ~/.wine do usuario.
export WINEPREFIX="${WINEPREFIX:-$HOME/.gc3d-wine}"
export WINEARCH=win64
# Silencia o ruido de log do Wine, que e volumoso e nao ajuda aqui.
export WINEDEBUG="${WINEDEBUG:--all}"

PYTHON_VERSION="${PYTHON_VERSION:-3.12.8}"
PYTHON_DIR="$WINEPREFIX/drive_c/python"
CACHE="$HOME/.cache/gc3d-build"

CLEAN_PREFIX=0
for arg in "$@"; do
    case "$arg" in
        --clean-prefix) CLEAN_PREFIX=1 ;;
        *) echo "opcao desconhecida: $arg" >&2; exit 2 ;;
    esac
done

echo "==> Grand Chase 3D Importer — build Windows via Wine"
echo "    projeto:  $PROJECT_ROOT"
echo "    prefixo:  $WINEPREFIX"

if ! command -v wine >/dev/null 2>&1; then
    cat >&2 <<'MSG'

ERRO: Wine nao encontrado.

Instale com:
    sudo dnf install wine          # Fedora
    sudo apt install wine64        # Debian / Ubuntu
    sudo pacman -S wine            # Arch

Alternativa sem Wine: rode build\windows\build.bat em uma maquina Windows.
MSG
    exit 1
fi

if [ "$CLEAN_PREFIX" -eq 1 ]; then
    echo "==> Removendo o prefixo Wine"
    rm -rf "$WINEPREFIX"
fi

mkdir -p "$CACHE"

# ------------------------------------------------------- Python para Windows

if [ ! -f "$PYTHON_DIR/python.exe" ]; then
    ARCHIVE="$CACHE/python-$PYTHON_VERSION-embed-amd64.zip"
    if [ ! -f "$ARCHIVE" ]; then
        URL="https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-embed-amd64.zip"
        echo "==> Baixando Python $PYTHON_VERSION para Windows"
        echo "    $URL"
        if command -v curl >/dev/null 2>&1; then
            curl -fL --progress-bar -o "$ARCHIVE" "$URL"
        elif command -v wget >/dev/null 2>&1; then
            wget -q --show-progress -O "$ARCHIVE" "$URL"
        else
            echo "ERRO: precisa de curl ou wget para baixar." >&2
            exit 1
        fi
    else
        echo "==> Usando Python $PYTHON_VERSION do cache"
    fi

    echo "==> Instalando Python no prefixo Wine"
    mkdir -p "$PYTHON_DIR"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ARCHIVE" -d "$PYTHON_DIR"
    else
        python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
            "$ARCHIVE" "$PYTHON_DIR"
    fi

    # A distribuicao embutida vem com o site-packages desligado; e preciso
    # habilitar para o pip e o PyInstaller funcionarem.
    for pth in "$PYTHON_DIR"/python*._pth; do
        [ -f "$pth" ] || continue
        sed -i 's/^#import site/import site/' "$pth"
        grep -q '^Lib\\site-packages' "$pth" || echo 'Lib\site-packages' >> "$pth"
    done
fi

echo "==> Python no Wine: $(wine "$PYTHON_DIR/python.exe" --version 2>&1 | tail -1)"

# ------------------------------------------------------------------- pip

if ! wine "$PYTHON_DIR/python.exe" -c "import pip" >/dev/null 2>&1; then
    GETPIP="$CACHE/get-pip.py"
    if [ ! -f "$GETPIP" ]; then
        echo "==> Baixando get-pip.py"
        if command -v curl >/dev/null 2>&1; then
            curl -fLs -o "$GETPIP" https://bootstrap.pypa.io/get-pip.py
        else
            wget -q -O "$GETPIP" https://bootstrap.pypa.io/get-pip.py
        fi
    fi
    echo "==> Instalando pip"
    cp "$GETPIP" "$PYTHON_DIR/get-pip.py"
    wine "$PYTHON_DIR/python.exe" "$PYTHON_DIR/get-pip.py" --no-warn-script-location
fi

# ------------------------------------------------------------- PyInstaller

if ! wine "$PYTHON_DIR/python.exe" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "==> Instalando PyInstaller no Wine"
    wine "$PYTHON_DIR/python.exe" -m pip install --no-warn-script-location pyinstaller
fi

# ------------------------------------------------------------------ tkinter
#
# A distribuicao embutida do Python NAO inclui tkinter, e a interface grafica
# depende dele. Copiamos tkinter, _tkinter.pyd e as bibliotecas Tcl/Tk de uma
# instalacao completa. Sem isso, so o gc3d.exe (linha de comando) funciona.

HAS_TK=1
if ! wine "$PYTHON_DIR/python.exe" -c "import tkinter" >/dev/null 2>&1; then
    HAS_TK=0
    echo "==> tkinter ausente no Python embutido (esperado)"
    echo "    tentando obter os arquivos do instalador completo"

    NUGET_DIR="$CACHE/python-full"
    if [ ! -d "$NUGET_DIR" ]; then
        # O pacote NuGet "python" traz uma instalacao completa, com tkinter.
        NUPKG="$CACHE/python.$PYTHON_VERSION.nupkg"
        if [ ! -f "$NUPKG" ]; then
            URL="https://www.nuget.org/api/v2/package/python/$PYTHON_VERSION"
            echo "    baixando $URL"
            if command -v curl >/dev/null 2>&1; then
                curl -fL --progress-bar -o "$NUPKG" "$URL" || true
            else
                wget -q --show-progress -O "$NUPKG" "$URL" || true
            fi
        fi
        if [ -f "$NUPKG" ]; then
            mkdir -p "$NUGET_DIR"
            python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
                "$NUPKG" "$NUGET_DIR" 2>/dev/null || true
        fi
    fi

    TOOLS="$NUGET_DIR/tools"
    if [ -d "$TOOLS" ]; then
        echo "    copiando tkinter, Tcl/Tk e DLLs"
        [ -d "$TOOLS/Lib/tkinter" ] && cp -r "$TOOLS/Lib/tkinter" "$PYTHON_DIR/Lib/" 2>/dev/null || true
        [ -d "$TOOLS/tcl" ] && cp -r "$TOOLS/tcl" "$PYTHON_DIR/" 2>/dev/null || true
        mkdir -p "$PYTHON_DIR/DLLs"
        for f in "$TOOLS/DLLs"/_tkinter.pyd "$TOOLS/DLLs"/tcl*.dll "$TOOLS/DLLs"/tk*.dll "$TOOLS/DLLs"/zlib*.dll; do
            [ -f "$f" ] && cp "$f" "$PYTHON_DIR/DLLs/" 2>/dev/null || true
        done
        for f in "$TOOLS"/tcl*.dll "$TOOLS"/tk*.dll; do
            [ -f "$f" ] && cp "$f" "$PYTHON_DIR/" 2>/dev/null || true
        done
        if wine "$PYTHON_DIR/python.exe" -c "import tkinter" >/dev/null 2>&1; then
            HAS_TK=1
            echo "    tkinter funcionando"
        else
            echo "    tkinter ainda indisponivel"
        fi
    fi
fi

if [ "$HAS_TK" -eq 0 ]; then
    cat <<'MSG'

AVISO: nao foi possivel habilitar o tkinter no Python do Wine.
       O gc3d.exe (linha de comando) sera gerado normalmente.
       O gc3d-gui.exe pode falhar ao abrir no Windows.

       Para um .exe de interface grafica garantido, rode
       build\windows\build.bat em uma maquina Windows real.

MSG
fi

# ---------------------------------------------------------------- build

echo "==> Limpando build anterior"
rm -rf dist/windows build/windows/pyinstaller

echo "==> Empacotando com PyInstaller dentro do Wine"
wine "$PYTHON_DIR/python.exe" -m PyInstaller build/common/gc3d.spec \
    --noconfirm --clean \
    --distpath dist/windows \
    --workpath build/windows/pyinstaller

echo
if [ -d dist/windows ]; then
    echo "==> Pronto. Executaveis em dist/windows/:"
    ls -lh dist/windows
    echo
    echo "Teste rapido (pelo Wine):"
    echo "    WINEPREFIX=$WINEPREFIX wine dist/windows/gc3d.exe --version"
else
    echo "ERRO: nada foi gerado em dist/windows." >&2
    exit 1
fi
