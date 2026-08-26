"""gc3d — conversor de modelos e animacoes do Grand Chase.

Le os formatos proprietarios do jogo (P3M, FRM) e exporta glTF binario (GLB),
que abre direto no Blender, Unity, Godot e navegadores.

Uso programatico:

    from gc3d import convert_model, ConvertOptions

    resultado = convert_model("abta003.p3m", "abta003.glb")
    print(resultado.ok, resultado.summary)

Uso de baixo nivel, quando se quer inspecionar os dados crus:

    from gc3d.formats import p3m
    arquivo = p3m.load_p3m("abta003.p3m")
    print(arquivo.num_angle_bones, len(arquivo.skin_vertices))

O pacote nao tem nenhuma dependencia fora da biblioteca padrao do Python.
"""

from __future__ import annotations

__version__ = "1.2.0"
__all__ = [
    "__version__",
    "ConvertOptions",
    "ConvertResult",
    "Direction",
    "AnimationIndex",
    "build_scene",
    "convert_model",
    "convert_to_gc",
    "convert_batch",
    "collect_inputs",
    "detect_direction",
    "classify_path",
    "find_animations_for_model",
    "Scene",
    "Mesh",
    "Joint",
    "Animation",
    "Keyframe",
    "Vertex",
    "DEFAULT_FPS",
]

from .convert import (
    AnimationIndex,
    ConvertOptions,
    ConvertResult,
    Direction,
    build_scene,
    classify_path,
    collect_inputs,
    convert_batch,
    convert_model,
    convert_to_gc,
    detect_direction,
    find_animations_for_model,
)
from .scene import (
    DEFAULT_FPS,
    Animation,
    Joint,
    Keyframe,
    Mesh,
    Scene,
    Vertex,
)
