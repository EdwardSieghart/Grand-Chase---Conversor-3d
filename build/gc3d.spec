# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para gerar os executaveis do Grand Chase 3D Importer.

Gera dois binarios a partir do mesmo codigo:

* `gc3d`      — a interface de linha de comando (console)
* `gc3d-gui`  — a interface grafica (sem janela de console no Windows)

Uso:
    pyinstaller build/gc3d.spec --noconfirm --clean

Rode no proprio sistema de destino: o PyInstaller nao faz cross-compile. Para o
executavel do Windows, rode em uma maquina Windows (ou no Wine).
"""

import os

# O .spec e executado com exec(), sem __file__ confiavel; o PyInstaller define
# SPECPATH com o diretorio do arquivo.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821
SRC = os.path.join(PROJECT_ROOT, "src")

# O pacote nao tem dependencias externas; excluimos modulos grandes que o
# PyInstaller as vezes puxa por engano, para o binario ficar pequeno.
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
    "urllib",
]

cli_analysis = Analysis(  # noqa: F821
    [os.path.join(PROJECT_ROOT, "gc3d_cli.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=["gc3d", "gc3d.formats"],
    excludes=EXCLUDES + ["tkinter"],
    noarchive=False,
)

gui_analysis = Analysis(  # noqa: F821
    [os.path.join(PROJECT_ROOT, "gc3d_gui.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=["gc3d", "gc3d.formats"],
    excludes=EXCLUDES,
    noarchive=False,
)

MERGE_NOTE = """
Nao usamos MERGE(): ele move as dependencias compartilhadas para o primeiro
executavel, o que funciona em build de pasta (onedir) mas quebra em build de
arquivo unico -- o segundo binario fica sem a libpython e morre no boot com
"Failed to load Python shared library". Dois Analysis independentes custam
alguns megabytes a mais e cada binario roda por conta propria.
"""

cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data)  # noqa: F821
gui_pyz = PYZ(gui_analysis.pure, gui_analysis.zipped_data)  # noqa: F821

cli_exe = EXE(  # noqa: F821
    cli_pyz,
    cli_analysis.scripts,
    cli_analysis.binaries,
    cli_analysis.datas,
    [],
    name="gc3d",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui_analysis.scripts,
    gui_analysis.binaries,
    gui_analysis.datas,
    [],
    name="gc3d-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # No Windows isso evita a janela preta de console aparecer atras da interface.
    console=False,
)
