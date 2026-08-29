#!/usr/bin/env bash
# Monta o AppImage. RODA DENTRO do ambiente de glibc antigo, nunca no seu sistema.
#
# Quem chama:
#   build/linux/appimage.sh        localmente, dentro de um container podman/docker
#   .github/workflows/release.yml  no CI, dentro de container: ubuntu:22.04
#
# Saida: dist/GrandChase3D-<versao>-x86_64.AppImage
#
# POR QUE glibc ANTIGO
#
# O PyInstaller nao embute a glibc; ele liga o binario contra a do sistema onde
# roda. E a glibc so tem compatibilidade para TRAS: um binario compilado contra a
# 2.43 exige 2.43 ou mais nova e morre com "version `GLIBC_2.43' not found" em
# qualquer maquina mais antiga. Compilando no Ubuntu 22.04 (glibc 2.35), o
# AppImage roda de 2022 para ca, que e o que se espera de um AppImage.
#
# ESTRUTURA DO AppDir
#
#   AppDir/AppRun                     script de entrada, repassa os argumentos
#   AppDir/gc3d.desktop               nome, icone e categoria no menu
#   AppDir/gc3d.png                   icone de 256x256
#   AppDir/.DirIcon                   copia do icone, e onde os arquivadores olham
#   AppDir/usr/bin/gc3d               o binario do PyInstaller
#   AppDir/usr/share/...              copias do .desktop e do icone, para quem
#                                     instalar o AppImage no sistema
#
# O AppRun exporta APPIMAGE quando ela nao vem definida. O runtime do AppImage
# normalmente ja faz isso, e e dela que o programa descobre onde gravar o
# gc3d.ini — sem ela cairia no /tmp/.mount_XXXX somente leitura de dentro do
# proprio AppImage. O reforco cobre o caso de rodar o AppDir direto, sem empacotar.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

ARQUITETURA="$(uname -m)"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARQUITETURA}.AppImage"

PYTHON="${PYTHON:-python3}"
VERSAO="$("$PYTHON" - <<'EOF'
import re, pathlib
texto = pathlib.Path("src/gc3d/__init__.py").read_text(encoding="utf-8")
print(re.search(r'__version__\s*=\s*"([^"]+)"', texto).group(1))
EOF
)"

APPDIR="build/linux/AppDir"
SAIDA="dist/GrandChase3D-${VERSAO}-${ARQUITETURA}.AppImage"

echo "==> AppImage do Grand Chase 3D Importer ${VERSAO} (${ARQUITETURA})"
echo "    glibc do ambiente: $(ldd --version | sed -n '1{s/.*[[:space:]]//;p}')"

# ------------------------------------------------------------------- binario

echo "==> Compilando o binario"
PYTHON="$PYTHON" ./build/linux/build.sh

test -x dist/linux/gc3d || { echo "ERRO: dist/linux/gc3d nao foi gerado" >&2; exit 1; }

# --------------------------------------------------------------------- AppDir

echo "==> Montando o AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APPDIR/usr/share/metainfo"

cp dist/linux/gc3d "$APPDIR/usr/bin/gc3d"
chmod +x "$APPDIR/usr/bin/gc3d"

cp build/icone/gc3d.png "$APPDIR/gc3d.png"
cp build/icone/gc3d.png "$APPDIR/.DirIcon"
cp build/icone/gc3d.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/gc3d.png"

cat > "$APPDIR/gc3d.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Grand Chase 3D Importer
GenericName=Conversor de modelos 3D
Comment=Converte modelos e animacoes do Grand Chase de e para glTF
Exec=gc3d %F
Icon=gc3d
Terminal=false
Categories=Graphics;3DGraphics;
Keywords=grandchase;p3m;frm;glb;gltf;blender;3d;
MimeType=model/gltf-binary;
DESKTOP
cp "$APPDIR/gc3d.desktop" "$APPDIR/usr/share/applications/gc3d.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Entrada do AppImage.
AQUI="$(dirname "$(readlink -f "$0")")"

# O programa grava o gc3d.ini na pasta do arquivo .AppImage, e descobre esse
# caminho pela variavel APPIMAGE. O runtime do AppImage a define; este reforco
# cobre a execucao do AppDir direto, sem empacotar, quando ela nao existe.
if [ -z "$APPIMAGE" ]; then
    APPIMAGE="$AQUI/AppRun"
    export APPIMAGE
fi

exec "$AQUI/usr/bin/gc3d" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ---------------------------------------------------------------- appimagetool

FERRAMENTA="build/linux/appimagetool-${ARQUITETURA}.AppImage"
if [ ! -x "$FERRAMENTA" ]; then
    echo "==> Baixando o appimagetool"
    curl -fsSL -o "$FERRAMENTA" "$APPIMAGETOOL_URL"
    chmod +x "$FERRAMENTA"
fi

echo "==> Empacotando"
mkdir -p dist
rm -f "$SAIDA"

# --appimage-extract-and-run: o appimagetool e ele mesmo um AppImage, e montar um
# AppImage exige FUSE. Container nao tem FUSE, e varias distribuicoes atuais nao
# trazem mais a libfuse2. Com esta opcao ele se descompacta num diretorio
# temporario em vez de montar, e funciona em qualquer lugar.
#
# ARCH e obrigatorio: sem ela o appimagetool nao adivinha a arquitetura de um
# AppDir e aborta.
ARCH="$ARQUITETURA" "./$FERRAMENTA" --appimage-extract-and-run \
    "$APPDIR" "$SAIDA"

chmod +x "$SAIDA"

echo
echo "==> Pronto:"
ls -lh "$SAIDA"
echo
echo "    ./$SAIDA --version"
echo "    ./$SAIDA config"
echo "    ./$SAIDA            (abre a interface)"
