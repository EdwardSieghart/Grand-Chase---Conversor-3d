#!/usr/bin/env bash
# Gera os executaveis do Grand Chase 3D Importer para LINUX.
#
# Saida em dist/linux/:
#   gc3d      - linha de comando
#   gc3d-gui  - interface grafica
#
# Uso:
#   ./build/linux/build.sh            build normal
#   ./build/linux/build.sh --test     roda os testes antes

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --test) RUN_TESTS=1 ;;
        *) echo "opcao desconhecida: $arg" >&2; exit 2 ;;
    esac
done

PYTHON="${PYTHON:-python3}"
DIST="dist/linux"
WORK="build/linux/pyinstaller"

echo "==> Grand Chase 3D Importer — build Linux"
echo "    projeto: $PROJECT_ROOT"
echo "    python:  $("$PYTHON" --version 2>&1)"

if [ "$RUN_TESTS" -eq 1 ]; then
    echo "==> Rodando testes"
    "$PYTHON" -m unittest discover -s tests -t .
fi

if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo
    echo "PyInstaller nao encontrado. Instale com:"
    echo "    $PYTHON -m pip install --user pyinstaller"
    echo
    echo "Sem ele o programa continua funcionando pelo Python:"
    echo "    $PYTHON gc3d_gui.py"
    echo "    $PYTHON gc3d_cli.py --help"
    exit 1
fi

echo "==> Limpando build anterior"
rm -rf "$DIST" "$WORK"

echo "==> Empacotando"
"$PYTHON" -m PyInstaller build/common/gc3d.spec \
    --noconfirm --clean \
    --distpath "$DIST" \
    --workpath "$WORK"

echo
echo "==> Pronto. Binarios em $DIST/:"
ls -lh "$DIST"
echo
echo "Teste rapido:"
echo "    ./$DIST/gc3d --version"
echo "    ./$DIST/gc3d-gui"
