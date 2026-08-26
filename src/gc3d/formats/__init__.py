"""Leitores e escritores dos formatos de arquivo.

Cada modulo cuida de um formato e conhece apenas ele mesmo e a `Scene`:

* `p3m`     — modelos do Grand Chase. **Le e escreve.**
* `frm`     — animacoes do Grand Chase. **Le e escreve.**
* `glb`     — escreve glTF 2.0 binario.
* `gltf_in` — le glTF 2.0, binario (`.glb`) e texto (`.gltf`).

A escrita de glTF e a leitura ficam em modulos separados porque as duas metades
quase nao compartilham codigo: escrever e montar acessores; ler e resolver
acessores, hierarquia e reamostragem de animacao. Mantê-las juntas produziria um
arquivo grande sem ganho.

Para acrescentar um formato novo, escreva um modulo aqui que converta de/para
`gc3d.scene.Scene`. Nada mais no projeto precisa mudar.
"""

from __future__ import annotations

__all__ = ["p3m", "frm", "glb", "gltf_in"]

from . import frm, glb, gltf_in, p3m
