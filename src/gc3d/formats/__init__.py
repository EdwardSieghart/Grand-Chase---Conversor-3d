"""Leitores e escritores dos formatos de arquivo.

Cada modulo cuida de um formato e conhece apenas ele mesmo e a `Scene`:

* `p3m` — modelos do Grand Chase (geometria, ossos, skinning). Entrada.
* `frm` — animacoes do Grand Chase (keyframes). Entrada.
* `glb`  — glTF 2.0 binario. Saida.

Para acrescentar um formato novo, escreva um modulo aqui que converta de/para
`gc3d.scene.Scene`. Nada mais no projeto precisa mudar.
"""

from __future__ import annotations

__all__ = ["p3m", "frm", "glb"]

from . import frm, glb, p3m
