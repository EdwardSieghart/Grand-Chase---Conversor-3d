#!/usr/bin/env bash
# Gera o executavel do Grand Chase 3D Importer para LINUX.
#
# Saida: dist/linux/gc3d — um binario unico, que abre a interface quando chamado
# sem argumentos e age como linha de comando quando recebe um subcomando.
#
# Uso:
#   ./build/linux/build.sh            build normal
#   ./build/linux/build.sh --test     roda os testes antes
#
# Para gerar o AppImage distribuivel, use build/linux/appimage.sh: ele chama este
# script dentro de um container de glibc antigo, o que este aqui NAO faz. Um
# binario compilado direto no seu sistema so roda em maquinas com glibc igual ou
# mais nova, e serve para testar, nao para distribuir.

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
    echo "    $PYTHON gc3d_app.py"
    echo "    $PYTHON gc3d_app.py --help"
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
echo "==> Pronto:"
ls -lh "$DIST"
echo
echo "Teste rapido:"
echo "    ./$DIST/gc3d --version"
echo "    ./$DIST/gc3d              (abre a interface)"
