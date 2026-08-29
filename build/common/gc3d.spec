# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller: UM executavel, para Linux e Windows.

Gera um binario so, `gc3d`, a partir de `gc3d_app.py`. Ele decide entre abrir a
interface e agir como linha de comando conforme os argumentos recebidos.

Nao chame este arquivo direto; use os scripts por plataforma:

    build/linux/build.sh          binario Linux em dist/linux/
    build/linux/appimage.sh       AppImage em dist/ (roda em container)
    build/windows/build.bat       gc3d.exe em dist\\windows\\  (rodar no Windows)

Antes eram dois binarios, `gc3d` e `gc3d-gui`, e havia um comentario longo aqui
explicando por que MERGE() estava fora: ele move as dependencias compartilhadas
para o primeiro executavel, o que funciona em build de pasta mas quebra em
arquivo unico, deixando o segundo binario sem a libpython. Com um executavel so
o problema deixa de existir.

O nome da pasta de saida vem da variavel de ambiente GC3D_DIST_NAME, definida
pelos scripts, para que Linux e Windows nao sobrescrevam um ao outro.
"""

import os
import sys

# O .spec e executado com exec(), sem __file__ confiavel; o PyInstaller define
# SPECPATH com o diretorio do arquivo.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821
SRC = os.path.join(PROJECT_ROOT, "src")
ICONE = os.path.join(PROJECT_ROOT, "build", "icone")

# O pacote nao tem dependencias externas; excluimos modulos grandes da
# biblioteca padrao que o PyInstaller as vezes puxa por engano, para o binario
# ficar pequeno.
EXCLUDES = [
    "numpy",
    "PIL",
    "pytest",
    "setuptools",
    "pip",
    "unittest",
    "pydoc",
    "doctest",
    "lib2to3",
    "sqlite3",
    "email",
    "html",
    "http",
    "xml",
]

# gc3d_cli e gc3d_gui ficam na raiz do projeto e sao importados sob demanda
# dentro de gc3d_app, so quando o caminho correspondente e escolhido. Import
# dentro de funcao o PyInstaller encontra, mas import de modulo que nao esta em
# nenhum pacote precisa da raiz no pathex, senao a analise nao acha o arquivo.
HIDDEN = ["gc3d", "gc3d.formats", "gc3d.settings", "gc3d_cli", "gc3d_gui"]

# O arrastar e soltar depende do tkinterdnd2, que carrega uma extensao Tcl a
# partir de arquivos em disco. O PyInstaller nao descobre esses arquivos sozinho,
# porque nao sao imports: e preciso declara-los como `datas`. Se o pacote nao
# estiver instalado, o build segue sem o recurso — a interface detecta a ausencia
# em tempo de execucao e continua funcionando pelos botoes.
DATAS = []
try:
    from PyInstaller.utils.hooks import collect_data_files  # noqa: F821

    DATAS = collect_data_files("tkinterdnd2")
    if DATAS:
        HIDDEN.append("tkinterdnd2")
        print(f"[gc3d.spec] tkinterdnd2 incluido ({len(DATAS)} arquivos)")
    else:
        print("[gc3d.spec] tkinterdnd2 nao encontrado: sem arrastar e soltar")
except Exception as error:  # noqa: BLE001
    print(f"[gc3d.spec] tkinterdnd2 nao incluido: {error}")

# O icone entra no .exe pelo parametro do EXE. No Linux o PyInstaller ignora
# icone, e quem cuida da aparencia e o .desktop do AppImage, que aponta para o
# gc3d.png. Nao vale abortar o build por falta de arte.
ICONE_EXE = None
if sys.platform == "win32":
    candidato = os.path.join(ICONE, "gc3d.ico")
    if os.path.isfile(candidato):
        ICONE_EXE = candidato
        print(f"[gc3d.spec] icone: {candidato}")
    else:
        print(f"[gc3d.spec] sem icone: {candidato} nao existe")

analysis = Analysis(  # noqa: F821
    [os.path.join(PROJECT_ROOT, "gc3d_app.py")],
    pathex=[PROJECT_ROOT, SRC],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="gc3d",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Subsistema grafico: sem isso uma janela preta de console apareceria atras
    # da interface no Windows a cada abertura por clique duplo. A saida da linha
    # de comando e recuperada em tempo de execucao por gc3d_app.attach_console(),
    # que explica o mecanismo em detalhe.
    console=False,
    icon=ICONE_EXE,
)
