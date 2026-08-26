#!/usr/bin/env bash
# Gera os executaveis do Grand Chase 3D Importer para Linux.
#
# Produz em dist/:
#   gc3d      - linha de comando
#   gc3d-gui  - interface grafica
#
# O PyInstaller nao faz cross-compile: este script gera binarios Linux. Para
# Windows, rode build/build_windows.bat em uma maquina Windows.
#
# Uso:
#   ./build/build_linux.sh            # build normal
#   ./build/build_linux.sh --test     # roda os testes antes

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --test) RUN_TESTS=1 ;;
        *) echo "opcao desconhecida: $arg" >&2; exit 2 ;;
    esac
done

PYTHON="${PYTHON:-python3}"

echo "==> Projeto: $PROJECT_ROOT"
echo "==> Python:  $("$PYTHON" --version)"

if [ "$RUN_TESTS" -eq 1 ]; then
    echo "==> Rodando testes"
    "$PYTHON" -m unittest discover -s tests -t .
fi

if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "==> PyInstaller nao encontrado."
    echo "    Instale com:  $PYTHON -m pip install --user pyinstaller"
    echo
    echo "    Sem o PyInstaller o programa continua funcionando pelo Python:"
    echo "      $PYTHON gc3d_cli.py --help"
    echo "      $PYTHON gc3d_gui.py"
    exit 1
fi

echo "==> Limpando builds anteriores"
rm -rf dist build/gc3d build/gc3d-gui

echo "==> Empacotando"
"$PYTHON" -m PyInstaller build/gc3d.spec --noconfirm --clean --distpath dist --workpath build/pyinstaller

echo
echo "==> Pronto. Binarios em dist/:"
ls -lh dist/ 2>/dev/null || true
echo
echo "Teste rapido:"
echo "  ./dist/gc3d --help"
echo "  ./dist/gc3d-gui"
