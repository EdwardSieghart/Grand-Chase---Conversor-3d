#!/usr/bin/env bash
# Gera o AppImage distribuivel, dentro de um container de glibc antigo.
#
# Uso:
#   ./build/linux/appimage.sh
#
# Saida: dist/GrandChase3D-<versao>-x86_64.AppImage
#
# POR QUE UM CONTAINER
#
# O PyInstaller liga o binario contra a glibc da maquina onde roda, e glibc so e
# compativel para tras. Compilar num Fedora atual (glibc 2.4x) produz um AppImage
# que morre com "GLIBC_2.4x not found" na maquina da maioria das pessoas — o
# oposto do que um AppImage existe para resolver. O container do Ubuntu 22.04
# tem glibc 2.35, e o resultado roda de 2022 para ca.
#
# Se quiser apenas TESTAR na sua propria maquina, sem distribuir, use
# build/linux/build.sh, que e direto e muito mais rapido.
#
# O CI nao usa este script: ele roda o appimage_interno.sh dentro de
# container: ubuntu:22.04, que da no mesmo sem precisar de podman aninhado.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

IMAGEM="${GC3D_IMAGEM:-docker.io/library/ubuntu:22.04}"

if command -v podman >/dev/null 2>&1; then
    MOTOR=podman
elif command -v docker >/dev/null 2>&1; then
    MOTOR=docker
else
    echo "ERRO: e preciso podman ou docker para montar o AppImage." >&2
    echo >&2
    echo "No Fedora:  sudo dnf install podman" >&2
    echo "No Ubuntu:  sudo apt install podman" >&2
    echo >&2
    echo "Para so testar na sua maquina, sem distribuir:" >&2
    echo "    ./build/linux/build.sh" >&2
    exit 1
fi

echo "==> Montando o AppImage em container ($MOTOR, $IMAGEM)"
echo "    glibc do seu sistema: $(ldd --version | sed -n '1{s/.*[[:space:]]//;p}') (nao sera usada)"

# :Z reetiqueta o volume para o SELinux, que bloqueia o acesso por padrao em
# Fedora e derivados. Em sistema sem SELinux a opcao e inofensiva.
#
# Rodamos como root DENTRO do container, porque o apt precisa disso. Isso nao
# suja o dono dos arquivos: no podman sem root o UID 0 de dentro e mapeado para o
# SEU usuario de fora, entao dist/ sai com o dono certo. Nao use --userns=keep-id
# aqui: ela mantem o seu UID dentro do container, e ai o apt-get falha com
# "Permission denied" em /var/lib/apt/lists.
"$MOTOR" run --rm -i \
    -v "$PROJECT_ROOT:/projeto:Z" \
    -w /projeto \
    -e GC3D_DENTRO_DO_CONTAINER=1 \
    "$IMAGEM" \
    bash -euo pipefail -s <<'DENTRO'
export DEBIAN_FRONTEND=noninteractive

echo "==> Preparando o ambiente ($(. /etc/os-release && echo "$PRETTY_NAME"), glibc $(ldd --version | sed -n '1{s/.*[[:space:]]//;p}'))"
apt-get update -qq
# python3-tk fornece o tkinter, que a interface usa; file e binutils sao pedidos
# pelo PyInstaller e pelo appimagetool para inspecionar binarios.
apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-tk python3-dev \
    binutils file curl ca-certificates zsync desktop-file-utils \
    >/dev/null

python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet "pyinstaller>=6.0" "tkinterdnd2==0.6.2"

./build/linux/appimage_interno.sh
DENTRO

echo
echo "==> Concluido. O arquivo abaixo pode ser distribuido:"
ls -lh dist/*.AppImage
