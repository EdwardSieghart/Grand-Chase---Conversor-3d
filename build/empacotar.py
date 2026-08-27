#!/usr/bin/env python3
"""Monta as pastas de distribuicao do Grand Chase 3D Importer.

Produz uma pasta por sistema, cada uma autocontida:

    release/
    ├── GrandChase3D-Linux/
    │   ├── Converter.sh          <- abre a interface grafica
    │   ├── Linha de comando.sh   <- abre um terminal com o gc3d disponivel
    │   ├── LEIA-ME.txt
    │   ├── LICENSE
    │   ├── gc3d                  <- executavel, se tiver sido compilado
    │   ├── gc3d-gui              <- executavel, se tiver sido compilado
    │   ├── app/                  <- codigo Python (usado se nao houver executavel)
    │   └── exemplos/             <- alguns arquivos do jogo para testar
    └── GrandChase3D-Windows/
        ├── Converter.bat
        ├── Linha de comando.bat
        ├── ... o mesmo, com gc3d.exe e gc3d-gui.exe

Os lancadores funcionam **com ou sem** o executavel compilado: se o binario
estiver na pasta, e ele que roda; se nao, o script chama o Python sobre o codigo
em `app/`. Assim a pasta serve tanto para quem baixou o pacote pronto quanto para
quem so tem o codigo.

Uso:
    python3 build/empacotar.py                # monta as duas pastas
    python3 build/empacotar.py --zip          # monta e gera os .zip
    python3 build/empacotar.py --so linux     # apenas uma delas
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
RELEASE_DIR = os.path.join(PROJECT_ROOT, "release")

#: Arquivos de exemplo incluidos no pacote, para o usuario testar na hora.
#: Poucos e pequenos de proposito: o pacote nao e um repositorio de assets.
SAMPLE_LIMITS = {"p3m": 2, "frm": 1, "dds": 2}


def read_version() -> str:
    """Le a versao do pacote, sem importar o modulo."""
    path = os.path.join(PROJECT_ROOT, "src", "gc3d", "__init__.py")
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


VERSION = read_version()


# ------------------------------------------------------------------ lancadores

LINUX_GUI_LAUNCHER = """#!/usr/bin/env bash
# Abre o Grand Chase 3D Importer.
#
# Se o executavel estiver nesta pasta, e ele que roda. Se nao, usa o Python
# sobre o codigo em app/ -- o programa nao tem dependencias, so precisa do
# Python 3.10 ou mais novo.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

if [ -x ./gc3d-gui ]; then
    exec ./gc3d-gui "$@"
fi

for candidato in python3 python; do
    if command -v "$candidato" >/dev/null 2>&1; then
        exec "$candidato" app/gc3d_gui.py "$@"
    fi
done

cat >&2 <<'MSG'

Nao encontrei nem o executavel gc3d-gui nem o Python nesta maquina.

Instale o Python 3 com o gerenciador de pacotes da sua distribuicao:

    sudo dnf install python3 python3-tkinter     # Fedora
    sudo apt install python3 python3-tk          # Debian, Ubuntu
    sudo pacman -S python tk                     # Arch

Depois rode este script de novo.

MSG
read -rp "Pressione Enter para fechar..."
exit 1
"""

LINUX_CLI_LAUNCHER = """#!/usr/bin/env bash
# Abre um terminal com o comando 'gc3d' disponivel.
#
# Exemplos, ja dentro do terminal que este script abre:
#
#     gc3d --help
#     gc3d info modelo.p3m
#     gc3d convert modelo.p3m -o saida/
#     gc3d convert personagem.glb -o saida/
#     gc3d batch "pasta com modelos" --merge -o saida/

DIR="$(dirname "$(readlink -f "$0")")"
cd "$DIR" || exit 1

if [ -x ./gc3d ]; then
    gc3d() { "$DIR/gc3d" "$@"; }
else
    PY=""
    for candidato in python3 python; do
        if command -v "$candidato" >/dev/null 2>&1; then PY="$candidato"; break; fi
    done
    if [ -z "$PY" ]; then
        echo "Python nao encontrado. Instale o python3 e tente de novo." >&2
        read -rp "Pressione Enter para fechar..."
        exit 1
    fi
    gc3d() { "$PY" "$DIR/app/gc3d_cli.py" "$@"; }
fi
export -f gc3d 2>/dev/null || true

echo "Grand Chase 3D Importer VERSAO_AQUI -- linha de comando"
echo "Digite 'gc3d --help' para ver os comandos. 'exit' para sair."
echo
gc3d --version
echo
exec "${SHELL:-/bin/bash}" -i
"""

WINDOWS_GUI_LAUNCHER = """@echo off
REM Abre o Grand Chase 3D Importer.
REM
REM Se o executavel estiver nesta pasta, e ele que roda. Se nao, usa o Python
REM sobre o codigo em app\\ -- o programa nao tem dependencias, so precisa do
REM Python 3.10 ou mais novo.

setlocal
cd /d "%~dp0"

if exist "gc3d-gui.exe" (
    start "" "gc3d-gui.exe" %*
    exit /b 0
)

REM Procura o Python. Tentamos primeiro com 'where', que localiza sem executar
REM e assim nao dispara o atalho da Microsoft Store. Se o proprio 'where' nao
REM existir (acontece em ambientes reduzidos), caimos para chamar o interpretador
REM direto e olhar o codigo de retorno.
set "PY="
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
    pythonw --version >nul 2>&1 && set "PY=pythonw"
)
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)

if defined PY (
    start "" %PY% "app\\gc3d_gui.py" %*
    exit /b 0
)

echo.
echo Nao encontrei nem o gc3d-gui.exe nem o Python nesta maquina.
echo.
echo Instale o Python 3 de https://www.python.org/downloads/
echo Na instalacao, deixe marcado:
echo    [x] Add Python to PATH
echo    [x] tcl/tk and IDLE     ^(necessario para a interface^)
echo.
echo Depois execute este arquivo de novo.
echo.
pause
exit /b 1
"""

WINDOWS_CLI_LAUNCHER = """@echo off
REM Abre um prompt com o comando 'gc3d' disponivel.
REM
REM Exemplos, ja dentro do prompt que este script abre:
REM
REM     gc3d --help
REM     gc3d info modelo.p3m
REM     gc3d convert modelo.p3m -o saida\\
REM     gc3d convert personagem.glb -o saida\\
REM     gc3d batch "pasta com modelos" --merge -o saida\\

cd /d "%~dp0"

if exist "gc3d.exe" (
    doskey gc3d="%~dp0gc3d.exe" $*
    "%~dp0gc3d.exe" --version
    goto prompt
)

REM Mesma deteccao em camadas do Converter.bat: 'where' primeiro, chamada direta
REM como reserva.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo Python nao encontrado. Instale de https://www.python.org/downloads/
    echo marcando "Add Python to PATH", e tente de novo.
    pause
    exit /b 1
)

doskey gc3d=%PY% "%~dp0app\\gc3d_cli.py" $*
%PY% "%~dp0app\\gc3d_cli.py" --version

:prompt
echo.
echo Grand Chase 3D Importer VERSAO_AQUI -- linha de comando
echo Digite "gc3d --help" para ver os comandos. "exit" para sair.
echo.
cmd /k
"""


# --------------------------------------------------------------------- LEIA-ME


def readme_text(platform: str, has_binary: bool) -> str:
    if platform == "linux":
        abrir = "Converter.sh"
        terminal = "Linha de comando.sh"
        instalar = (
            "    sudo dnf install python3 python3-tkinter     # Fedora\n"
            "    sudo apt install python3 python3-tk          # Debian, Ubuntu\n"
            "    sudo pacman -S python tk                     # Arch"
        )
        nota_binario = (
            "Esta pasta inclui os executaveis 'gc3d-gui' e 'gc3d', que nao\n"
            "precisam de Python instalado."
            if has_binary
            else "Esta pasta NAO inclui executaveis compilados: os lancadores usam\n"
            "o Python sobre o codigo em app/. Precisa do Python 3.10 ou mais novo."
        )
        primeiro_passo = (
            "1. Marque o Converter.sh como executavel, se ainda nao estiver:\n"
            "\n"
            "       chmod +x Converter.sh \"Linha de comando.sh\"\n"
            "\n"
            "2. Abra o Converter.sh (duplo clique, ou ./Converter.sh no terminal)."
        )
    else:
        abrir = "Converter.bat"
        terminal = "Linha de comando.bat"
        instalar = (
            "    Baixe de https://www.python.org/downloads/\n"
            "    Na instalacao, deixe marcado:\n"
            "        [x] Add Python to PATH\n"
            "        [x] tcl/tk and IDLE     (necessario para a interface)"
        )
        nota_binario = (
            "Esta pasta inclui os executaveis 'gc3d-gui.exe' e 'gc3d.exe', que\n"
            "nao precisam de Python instalado."
            if has_binary
            else "Esta pasta NAO inclui executaveis compilados: os lancadores usam\n"
            "o Python sobre o codigo em app\\. Precisa do Python 3.10 ou mais novo."
        )
        primeiro_passo = f"1. Clique duas vezes em {abrir}."

    return f"""Grand Chase 3D Importer {VERSION}
{'=' * (len(VERSION) + 25)}

Conversor de modelos e animacoes do Grand Chase Classic, nos dois sentidos:

    .p3m + .frm   ->  .glb          para editar no Blender
    .glb / .gltf  ->  .p3m + .frm   para voltar ao jogo

O sentido e detectado sozinho pelas extensoes do que voce carregar.


COMO ABRIR
----------

{primeiro_passo}

Para usar pela linha de comando, abra o "{terminal}".

{nota_binario}


COMO USAR A INTERFACE
---------------------

1. Arraste os arquivos ou pastas para dentro da janela, ou use os botoes
   "Adicionar arquivos" / "Adicionar pasta". Modelos, animacoes e glTF vao
   todos para a mesma lista.

2. A faixa azul no topo mostra o que sera feito, por exemplo:

       P3M + FRM -> GLB     4 modelo(s), 68 animacao(oes)  ->  um unico .glb

3. Escolha a pasta de saida e clique em Converter.

Por padrao tudo vira UM arquivo .glb: todos os modelos e todas as animacoes
juntos. E o que faz sentido para um personagem, que costuma vir repartido em
varios .p3m (corpo, rosto, cabelo, arma). Desmarque "Juntar tudo em um unico
.glb" se preferir um arquivo por modelo.


A PASTA exemplos/
-----------------

Traz alguns arquivos do jogo para voce testar sem precisar procurar nada.
Arraste-os para a janela e converta.


NO BLENDER
----------

Importe com File > Import > glTF 2.0.

Ajuste importante: as animacoes do Grand Chase rodam a 55 FPS. Antes de
qualquer coisa, va em Output Properties > Frame Rate > Custom e ponha 55.
Sem isso a animacao toca na velocidade errada, e ao exportar de volta os
tempos dos keyframes perdem precisao.

As acoes (animacoes) aparecem em Dope Sheet > Action Editor. Com muitas,
use o editor Nonlinear Animation.

Nao renomeie os ossos (bone_0, bone_1, ...) se pretende reaproveitar os
arquivos .frm que o jogo ja tem: e por esse nome que a numeracao original
e restaurada na volta.


VOLTANDO PARA O JOGO
--------------------

Ao converter um .glb voce recebe:

    personagem.p3m                 malha, esqueleto e skinning
    personagem_<animacao>.frm      uma por animacao
    personagem.dds                 a textura, no formato que o jogo le

Antes de exportar do Blender:

  - cena em 55 FPS;
  - aplique as transformacoes (Object > Apply > All Transforms);
  - triangule a malha;
  - marque Include > Animations, modo Actions, para levar todas.

Limites do formato do jogo, que o conversor avisa quando encosta:
255 ossos, 65535 vertices, 65535 triangulos, um osso por vertice e uma
malha por arquivo.


SE PRECISAR DO PYTHON
---------------------

{instalar}


PROBLEMAS
---------

O arrastar e soltar nao funciona
    Falta o pacote opcional tkinterdnd2. Use os botoes de adicionar, que
    fazem o mesmo, ou instale com:  pip install tkinterdnd2
    (os executaveis compilados ja vem com o recurso)

A interface nao abre
    Falta o tkinter. No Windows, reinstale o Python marcando
    "tcl/tk and IDLE". No Linux, instale o pacote python3-tkinter.

O modelo aparece sem textura
    O .dds precisa estar na mesma pasta do .p3m. No Blender, mude o
    viewport para Material Preview.

"P3M versao 0.7 ainda nao implementado"
    Apenas a versao 0.5 e suportada, que cobre praticamente todo o
    conteudo do Grand Chase Classic. A recusa e proposital: interpretar
    outra versao com o layout errado geraria geometria corrompida sem
    aviso.


LICENCA
-------

MIT, veja o arquivo LICENSE.

Os formatos P3M e FRM pertencem ao Grand Chase / KOG Studios. Esta e uma
ferramenta independente de interoperabilidade. Os arquivos em exemplos/
sao do jogo e servem apenas para teste.
"""


# ------------------------------------------------------------------ montagem


def copy_app(target: str) -> None:
    """Copia o codigo Python para `app/`, sem lixo."""
    app = os.path.join(target, "app")
    os.makedirs(app, exist_ok=True)

    for name in ("gc3d_cli.py", "gc3d_gui.py"):
        shutil.copy2(os.path.join(PROJECT_ROOT, name), os.path.join(app, name))

    shutil.copytree(
        os.path.join(PROJECT_ROOT, "src"),
        os.path.join(app, "src"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def copy_samples(target: str) -> int:
    """Copia alguns arquivos de exemplo. Devolve quantos foram copiados."""
    source = os.path.join(PROJECT_ROOT, "samples")
    if not os.path.isdir(source):
        return 0
    destination = os.path.join(target, "exemplos")
    os.makedirs(destination, exist_ok=True)

    copied = 0
    for kind, limit in SAMPLE_LIMITS.items():
        folder = os.path.join(source, kind)
        if not os.path.isdir(folder):
            continue
        names = sorted(
            n for n in os.listdir(folder) if n.lower().endswith("." + kind)
        )
        for name in names[:limit]:
            shutil.copy2(
                os.path.join(folder, name), os.path.join(destination, name)
            )
            copied += 1
    return copied


def copy_binaries(target: str, platform: str) -> bool:
    """Copia os executaveis compilados, se existirem. Devolve se achou algum."""
    source = os.path.join(PROJECT_ROOT, "dist", platform)
    if not os.path.isdir(source):
        return False
    found = False
    for name in sorted(os.listdir(source)):
        path = os.path.join(source, name)
        if not os.path.isfile(path):
            continue
        shutil.copy2(path, os.path.join(target, name))
        if platform == "linux":
            _make_executable(os.path.join(target, name))
        found = True
    return found


def _make_executable(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_text(path: str, content: str, executable: bool = False) -> None:
    # newline="" preserva os \r\n que os arquivos .bat precisam no Windows.
    newline = "\r\n" if path.lower().endswith(".bat") else "\n"
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(content)
    if executable:
        _make_executable(path)


def build_platform(platform: str) -> str:
    """Monta a pasta de um sistema. Devolve o caminho."""
    label = "Linux" if platform == "linux" else "Windows"
    target = os.path.join(RELEASE_DIR, f"GrandChase3D-{label}")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)

    has_binary = copy_binaries(target, platform)
    copy_app(target)
    samples = copy_samples(target)

    if platform == "linux":
        write_text(
            os.path.join(target, "Converter.sh"),
            LINUX_GUI_LAUNCHER,
            executable=True,
        )
        write_text(
            os.path.join(target, "Linha de comando.sh"),
            LINUX_CLI_LAUNCHER.replace("VERSAO_AQUI", VERSION),
            executable=True,
        )
    else:
        write_text(os.path.join(target, "Converter.bat"), WINDOWS_GUI_LAUNCHER)
        write_text(
            os.path.join(target, "Linha de comando.bat"),
            WINDOWS_CLI_LAUNCHER.replace("VERSAO_AQUI", VERSION),
        )

    write_text(os.path.join(target, "LEIA-ME.txt"), readme_text(platform, has_binary))
    license_path = os.path.join(PROJECT_ROOT, "LICENSE")
    if os.path.isfile(license_path):
        shutil.copy2(license_path, os.path.join(target, "LICENSE"))

    size = sum(
        os.path.getsize(os.path.join(root, name))
        for root, _, files in os.walk(target)
        for name in files
    )
    print(
        f"  {label:8s} -> {os.path.relpath(target, PROJECT_ROOT)}"
        f"  ({size / (1024 * 1024):.1f} MB, "
        f"executaveis: {'sim' if has_binary else 'nao'}, "
        f"exemplos: {samples})"
    )
    return target


def make_zip(folder: str) -> str:
    """Compacta a pasta, preservando o bit de execucao dos lancadores."""
    archive = folder + f"-{VERSION}.zip"
    if os.path.exists(archive):
        os.remove(archive)
    base = os.path.dirname(folder)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _, files in os.walk(folder):
            for name in sorted(files):
                path = os.path.join(root, name)
                arcname = os.path.relpath(path, base)
                info = zipfile.ZipInfo.from_file(path, arcname)
                # O zip padrao perde as permissoes; sem isso o .sh chega sem o
                # bit de execucao e o usuario tem de rodar chmod na mao.
                mode = os.stat(path).st_mode
                info.external_attr = (mode & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as handle:
                    zf.writestr(info, handle.read())
    size = os.path.getsize(archive)
    print(
        f"  {os.path.basename(archive)}  ({size / (1024 * 1024):.1f} MB)"
    )
    return archive


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--so",
        choices=("linux", "windows", "ambos"),
        default="ambos",
        help="qual pacote montar (padrao: ambos)",
    )
    parser.add_argument(
        "--zip", action="store_true", help="gera tambem os arquivos .zip"
    )
    args = parser.parse_args(argv[1:])

    print(f"Grand Chase 3D Importer {VERSION} — empacotando")
    os.makedirs(RELEASE_DIR, exist_ok=True)

    platforms = ["linux", "windows"] if args.so == "ambos" else [args.so]
    folders = [build_platform(platform) for platform in platforms]

    if args.zip:
        print("\nCompactando:")
        for folder in folders:
            make_zip(folder)

    print("\nPronto.")
    missing = [
        p for p in platforms if not os.path.isdir(os.path.join(PROJECT_ROOT, "dist", p))
    ]
    if missing:
        print(
            f"\nAviso: sem executaveis compilados para {', '.join(missing)}. "
            f"Os lancadores vao usar o Python. Para compilar:"
        )
        if "linux" in missing:
            print("    ./build/linux/build.sh")
        if "windows" in missing:
            print("    build\\windows\\build.bat        (no Windows)")
            print("    ./build/windows/build_wine.sh   (a partir do Linux)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
