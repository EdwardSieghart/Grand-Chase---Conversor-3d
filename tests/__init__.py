"""Suite de testes do Grand Chase 3D Importer.

Roda com a biblioteca padrao, sem pytest:

    python3 -m unittest discover -s tests -v

Este `__init__` coloca `src/` no `sys.path` para que os testes importem `gc3d`
sem precisar instalar o pacote.
"""

from __future__ import annotations

import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
SAMPLES_DIR = os.path.join(PROJECT_ROOT, "samples")
TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")

for path in (SRC_DIR, TOOLS_DIR):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)
