"""Pipeline de conversao de alto nivel.

Este e o modulo que a CLI e a GUI usam. Ele amarra as pecas:

    P3M -> Scene ---+
                    |--> merge --> to_right_handed --> GLB
    FRM -> Scene ---+

Tudo aqui e sincrono e sem estado global, para que a GUI possa chamar as mesmas
funcoes de uma thread de trabalho sem surpresas.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field

from .formats import frm as frm_format
from .formats import p3m as p3m_format
from .formats.glb import GlbOptions, export_glb
from .scene import Scene
from .textures import DdsError, find_texture_file, load_texture_as_png

__all__ = [
    "ConvertOptions",
    "ConvertResult",
    "build_scene",
    "convert_model",
    "convert_batch",
    "find_animations_for_model",
    "collect_inputs",
]


@dataclass
class ConvertOptions:
    """Ajustes da conversao. Os defaults servem para o caso comum."""

    #: Procura e embute a textura do modelo no GLB.
    embed_texture: bool = True
    #: Caminho explicito de textura. Tem prioridade sobre a busca automatica.
    texture_path: str | None = None
    #: Pastas extras onde procurar texturas.
    texture_dirs: list[str] = field(default_factory=list)
    #: Renderiza faces dos dois lados.
    double_sided: bool = True
    #: "OPAQUE" | "MASK" | "BLEND"; None decide pela presenca de alfa.
    alpha_mode: str | None = None
    #: Normaliza normais nao unitarias (varios P3M oficiais precisam disso).
    normalize_normals: bool = True
    #: Grava o JSON do GLB indentado. Util para depurar, gera arquivo maior.
    pretty_json: bool = False


@dataclass
class ConvertResult:
    """Resultado de uma conversao, para relatorio na CLI ou na GUI."""

    source: str
    output_path: str | None = None
    ok: bool = False
    bytes_written: int = 0
    summary: str = ""
    texture_used: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    #: Traceback completo, guardado apenas para o modo verboso.
    traceback: str | None = None


# ------------------------------------------------------------ montagem da cena


def build_scene(
    model_path: str | None,
    animation_paths: list[str] | tuple[str, ...] = (),
    warnings: list[str] | None = None,
) -> Scene:
    """Monta uma `Scene` left-handed a partir de um P3M e de zero ou mais FRM."""
    warn = warnings if warnings is not None else []
    scene = Scene()

    if model_path:
        p3m = p3m_format.load_p3m(model_path)
        name = os.path.splitext(os.path.basename(model_path))[0]
        scene = p3m_format.p3m_to_scene(p3m, name)
        if p3m.mesh_vertices_truncated:
            warn.append(
                "bloco de MeshVertex truncado ou ausente no P3M "
                "(inofensivo: a conversao usa apenas os SkinVertex)"
            )
        if p3m.trailing_bytes:
            warn.append(
                f"{p3m.trailing_bytes} byte(s) extras ignorados no fim do P3M"
            )
        if scene.unskinned_vertices:
            if not scene.skeleton:
                warn.append(
                    "nenhum vertice tem osso associado: exportado como malha "
                    "estatica, sem esqueleto"
                )
            else:
                warn.append(
                    f"{scene.unskinned_vertices} vertice(s) sem osso associado "
                    f"foram amarrados ao joint raiz"
                )

    for animation_path in animation_paths:
        frm = frm_format.load_frm(animation_path)
        name = os.path.splitext(os.path.basename(animation_path))[0]
        animation = frm_format.frm_to_animation(frm, name)

        if scene.skeleton and frm.num_bones != len(scene.skeleton):
            warn.append(
                f"{os.path.basename(animation_path)}: a animacao tem "
                f"{frm.num_bones} osso(s) e o modelo tem {len(scene.skeleton)}; "
                f"os ossos excedentes serao ignorados"
            )
        if frm.trailing_bytes:
            warn.append(
                f"{os.path.basename(animation_path)}: {frm.trailing_bytes} "
                f"byte(s) extras ignorados no fim do FRM"
            )
        scene.animations.append(animation)

    return scene


def _resolve_texture(
    model_path: str | None, scene: Scene, options: ConvertOptions, warn: list[str]
) -> tuple[bytes | None, str | None]:
    """Devolve `(png_bytes, caminho_usado)` da textura, ou `(None, None)`."""
    if not options.embed_texture:
        return None, None

    path = options.texture_path
    if not path and model_path:
        declared = scene.meshes[0].texture_name if scene.meshes else ""
        path = find_texture_file(model_path, declared, options.texture_dirs)
    if not path:
        return None, None

    if not os.path.isfile(path):
        warn.append(f"textura nao encontrada: {path}")
        return None, None

    try:
        return load_texture_as_png(path), path
    except (DdsError, OSError, ValueError) as error:
        warn.append(f"falha ao converter a textura {os.path.basename(path)}: {error}")
        return None, None


# ------------------------------------------------------------------- conversao


def convert_model(
    model_path: str | None,
    output_path: str,
    animation_paths: list[str] | tuple[str, ...] = (),
    options: ConvertOptions | None = None,
) -> ConvertResult:
    """Converte um P3M (e FRMs opcionais) em um arquivo GLB."""
    options = options or ConvertOptions()
    source = model_path or (animation_paths[0] if animation_paths else "<vazio>")
    result = ConvertResult(source=source)

    try:
        scene = build_scene(model_path, animation_paths, result.warnings)

        if not scene.meshes and not scene.animations:
            raise ValueError("nada para converter: nenhuma malha e nenhuma animacao")
        if scene.animations and not scene.skeleton:
            result.warnings.append(
                "ha animacao mas nenhum esqueleto (nenhum P3M informado); "
                "as animacoes nao serao gravadas no GLB"
            )

        if options.normalize_normals:
            fixed = scene.normalize_normals()
            if fixed:
                result.warnings.append(
                    f"{fixed} normal(is) nao unitaria(s) normalizada(s)"
                )

        texture_png, texture_path = _resolve_texture(
            model_path, scene, options, result.warnings
        )

        scene.to_right_handed()
        data = export_glb(
            scene,
            GlbOptions(
                texture_png=texture_png,
                double_sided=options.double_sided,
                alpha_mode=options.alpha_mode,
                pretty_json=options.pretty_json,
            ),
        )

        parent = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(parent, exist_ok=True)
        with open(output_path, "wb") as handle:
            handle.write(data)

        result.ok = True
        result.output_path = output_path
        result.bytes_written = len(data)
        result.summary = scene.summary()
        result.texture_used = texture_path
    except Exception as error:  # noqa: BLE001 - a CLI/GUI relata por arquivo
        result.ok = False
        result.error = f"{type(error).__name__}: {error}"
        result.traceback = traceback.format_exc()

    return result


# --------------------------------------------------------------- lote e busca


def find_animations_for_model(model_path: str, animation_dir: str) -> list[str]:
    """Lista os FRM de uma pasta que parecem pertencer a um modelo.

    O jogo nao guarda essa ligacao em nenhum lugar, entao usamos duas pistas:
    o prefixo do nome do arquivo e a quantidade de ossos. A segunda e a
    confiavel: um FRM so pode animar um modelo com o mesmo numero de ossos.
    """
    if not os.path.isdir(animation_dir):
        return []

    try:
        p3m = p3m_format.load_p3m(model_path)
    except (p3m_format.InvalidP3mError, OSError):
        return []
    num_bones = p3m.num_angle_bones

    matches: list[str] = []
    for name in sorted(os.listdir(animation_dir)):
        if not name.lower().endswith(".frm"):
            continue
        path = os.path.join(animation_dir, name)
        try:
            frm = frm_format.load_frm(path)
        except (frm_format.InvalidFrmError, OSError):
            continue
        if frm.num_bones == num_bones:
            matches.append(path)
    return matches


def collect_inputs(paths: list[str], recursive: bool = True) -> tuple[list[str], list[str]]:
    """Expande arquivos e pastas em duas listas: `(p3m, frm)`."""
    models: list[str] = []
    animations: list[str] = []

    def classify(path: str) -> None:
        lower = path.lower()
        if lower.endswith(".p3m"):
            models.append(path)
        elif lower.endswith(".frm"):
            animations.append(path)

    for entry in paths:
        if os.path.isfile(entry):
            classify(entry)
        elif os.path.isdir(entry):
            if recursive:
                for root, _, files in os.walk(entry):
                    for name in sorted(files):
                        classify(os.path.join(root, name))
            else:
                for name in sorted(os.listdir(entry)):
                    full = os.path.join(entry, name)
                    if os.path.isfile(full):
                        classify(full)

    return sorted(models), sorted(animations)


def convert_batch(
    model_paths: list[str],
    output_dir: str,
    options: ConvertOptions | None = None,
    animation_dir: str | None = None,
    progress=None,
) -> list[ConvertResult]:
    """Converte varios modelos para uma pasta de saida.

    `progress` e um callable opcional `(indice, total, caminho)` chamado antes de
    cada arquivo, para a GUI atualizar a barra de progresso.
    """
    options = options or ConvertOptions()
    results: list[ConvertResult] = []
    total = len(model_paths)

    for index, model_path in enumerate(model_paths):
        if progress is not None:
            progress(index, total, model_path)
        stem = os.path.splitext(os.path.basename(model_path))[0]
        output_path = os.path.join(output_dir, stem + ".glb")
        animations = (
            find_animations_for_model(model_path, animation_dir)
            if animation_dir
            else []
        )
        results.append(convert_model(model_path, output_path, animations, options))

    if progress is not None:
        progress(total, total, "")
    return results
