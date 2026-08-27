"""Pipeline de conversao de alto nivel, nas duas direcoes.

    P3M + FRM  ──▶  Scene  ──▶  GLB          (extrair do jogo)
    GLB/glTF   ──▶  Scene  ──▶  P3M + FRM    (devolver para o jogo)

A direcao e deduzida da extensao dos arquivos de entrada, e nao pedida ao
usuario: se entram `.p3m`/`.frm`, o destino so pode ser glTF; se entra
`.glb`/`.gltf`, o destino so pode ser P3M/FRM.

Tudo aqui e sincrono e sem estado global, para que a interface grafica possa
chamar as mesmas funcoes de uma thread de trabalho sem surpresas.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field

from .formats import frm as frm_format
from .formats import gltf_in
from .formats import p3m as p3m_format
from .formats.glb import GlbOptions, export_glb
from .scene import DEFAULT_FPS, Scene
from .textures import DdsError, find_texture_file, load_texture_as_png

__all__ = [
    "ConvertOptions",
    "ConvertResult",
    "Direction",
    "AnimationIndex",
    "GC_EXTENSIONS",
    "GLTF_EXTENSIONS",
    "classify_path",
    "detect_direction",
    "build_scene",
    "convert_model",
    "convert_to_gc",
    "convert_batch",
    "convert_merged",
    "skeleton_signature",
    "find_animations_for_model",
    "collect_inputs",
]

#: Extensoes dos formatos do jogo (entrada da conversao direta).
GC_EXTENSIONS = (".p3m", ".frm")
#: Extensoes de glTF (entrada da conversao inversa).
GLTF_EXTENSIONS = (".glb", ".gltf")


class Direction:
    """Sentido da conversao."""

    TO_GLTF = "para_glb"
    TO_GC = "para_p3m_frm"

    LABELS = {
        TO_GLTF: "P3M/FRM -> GLB",
        TO_GC: "GLB -> P3M/FRM",
    }


@dataclass
class ConvertOptions:
    """Ajustes da conversao. Os defaults servem para o caso comum."""

    # ---- comuns
    #: Normaliza normais nao unitarias (varios P3M oficiais precisam disso).
    normalize_normals: bool = True

    # ---- P3M/FRM -> GLB
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
    #: Grava o JSON do GLB indentado. Util para depurar, gera arquivo maior.
    pretty_json: bool = False

    # ---- GLB -> P3M/FRM
    #: Grava tambem as animacoes do glTF como arquivos .frm.
    export_animations: bool = True
    #: Extrai a textura embutida do glTF como .png ao lado do .p3m.
    extract_texture: bool = True
    #: Prefixo dos arquivos .frm gerados.
    animation_prefix: str = ""

    # ---- selecao de animacoes (apenas P3M/FRM -> GLB)
    #: Se True, cada modelo recebe apenas as animacoes com o mesmo numero de
    #: ossos. O padrao e **False**: incluir tudo e o comportamento menos
    #: surpreendente, porque a contagem de ossos e um filtro grosseiro (ha sete
    #: esqueletos diferentes com 15 ossos no conjunto de teste) e uma animacao
    #: descartada em silencio parece um defeito do programa.
    match_animations_by_bones: bool = False


@dataclass
class ConvertResult:
    """Resultado de uma conversao, para relatorio na CLI ou na GUI."""

    source: str
    direction: str = Direction.TO_GLTF
    #: Todos os arquivos gravados (um GLB, ou um P3M mais N FRM).
    outputs: list[str] = field(default_factory=list)
    ok: bool = False
    bytes_written: int = 0
    summary: str = ""
    texture_used: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    #: Traceback completo, guardado apenas para o modo verboso.
    traceback: str | None = None

    @property
    def output_path(self) -> str | None:
        """Primeiro arquivo gravado, para mensagens curtas."""
        return self.outputs[0] if self.outputs else None


# ---------------------------------------------------------- deteccao de direcao


def classify_path(path: str) -> str | None:
    """Devolve `"p3m"`, `"frm"`, `"gltf"` ou None, conforme a extensao."""
    extension = os.path.splitext(path)[1].lower()
    if extension == ".p3m":
        return "p3m"
    if extension == ".frm":
        return "frm"
    if extension in GLTF_EXTENSIONS:
        return "gltf"
    return None


def detect_direction(paths: list[str] | tuple[str, ...]) -> str | None:
    """Deduz o sentido da conversao a partir das extensoes.

    Devolve None quando nao ha nada reconhecivel. Se houver mistura de glTF com
    arquivos do jogo, o glTF ganha e os demais serao reportados como ignorados
    por quem chamou — misturar os dois num unico trabalho nao tem significado.
    """
    kinds = {classify_path(path) for path in paths}
    kinds.discard(None)
    if not kinds:
        return None
    if "gltf" in kinds:
        return Direction.TO_GC
    return Direction.TO_GLTF


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


# ------------------------------------------- P3M/FRM -> um unico GLB (juntando)


def skeleton_signature(scene: Scene) -> tuple:
    """Assinatura que identifica um esqueleto, para agrupar modelos.

    Nao basta o numero de ossos: medindo os 127 modelos do conjunto de teste ha
    **18 esqueletos distintos**, e sete deles tem exatamente 15 ossos. Juntar
    modelos de esqueletos diferentes num unico `skin` misturaria bind poses e
    deformaria a malha, entao a assinatura inclui as translacoes e a hierarquia.

    As translacoes sao arredondadas porque vem de float de 32 bits e a comparacao
    exata seria fragil.
    """
    return (
        len(scene.skeleton),
        tuple(
            tuple(round(component, 5) for component in joint.translation)
            for joint in scene.skeleton
        ),
        tuple(joint.parent for joint in scene.skeleton),
        tuple(tuple(joint.children) for joint in scene.skeleton),
    )


def convert_merged(
    model_paths: list[str] | tuple[str, ...],
    animation_paths: list[str] | tuple[str, ...],
    output_path: str,
    options: ConvertOptions | None = None,
) -> ConvertResult:
    """Converte varios modelos e animacoes em **um unico** arquivo GLB.

    E o modo natural para um personagem: corpo, rosto, cabelo e arma costumam
    estar em `.p3m` separados e pertencem ao mesmo boneco, entao um arquivo com
    tudo dentro e mais util que um arquivo por peca.

    Os modelos sao agrupados por esqueleto (ver `skeleton_signature`). Cada grupo
    vira uma `skin` dentro do mesmo GLB — o glTF permite varias —, o que mantem
    correto o caso em que a selecao mistura personagens diferentes, em vez de
    deformar a malha por forçar um esqueleto so.

    Cada animacao entra no grupo cujo numero de ossos ela usa. Se nenhum grupo
    casar, entra no grupo com mais ossos, com aviso: assim a animacao nunca e
    descartada em silencio.
    """
    options = options or ConvertOptions()
    result = ConvertResult(
        source=(
            f"{len(model_paths)} modelo(s) + {len(animation_paths)} animacao(oes)"
        ),
        direction=Direction.TO_GLTF,
    )

    try:
        if not model_paths:
            raise ValueError(
                "nada para juntar: e preciso pelo menos um modelo .p3m"
            )

        # Uma cena por modelo, agrupadas por esqueleto.
        groups: dict[tuple, Scene] = {}
        order: list[tuple] = []
        fixed_normals = 0
        for model_path in model_paths:
            scene = build_scene(model_path, (), result.warnings)
            if not scene.meshes:
                continue

            texture_png, texture_path = _resolve_texture(
                model_path, scene, options, result.warnings
            )
            for mesh in scene.meshes:
                mesh.texture_png = texture_png
                mesh.texture_source = texture_path
            if texture_path and result.texture_used is None:
                result.texture_used = texture_path

            if options.normalize_normals:
                fixed_normals += scene.normalize_normals()

            signature = skeleton_signature(scene)
            if signature in groups:
                groups[signature].meshes.extend(scene.meshes)
            else:
                groups[signature] = scene
                order.append(signature)

        if not groups:
            raise ValueError("nenhum dos modelos informados tem malha")
        if fixed_normals:
            result.warnings.append(
                f"{fixed_normals} normal(is) nao unitaria(s) normalizada(s)"
            )

        # Distribui as animacoes entre os grupos, pelo numero de ossos.
        by_bones: dict[int, list[tuple]] = {}
        for signature in order:
            by_bones.setdefault(len(groups[signature].skeleton), []).append(signature)
        largest = max(order, key=lambda s: len(groups[s].skeleton))
        ambiguous = 0

        for animation_path in animation_paths:
            try:
                frm = frm_format.load_frm(animation_path)
            except (frm_format.InvalidFrmError, OSError) as error:
                result.warnings.append(
                    f"{os.path.basename(animation_path)} ignorado: {error}"
                )
                continue
            name = os.path.splitext(os.path.basename(animation_path))[0]

            candidates = by_bones.get(frm.num_bones)
            if not candidates:
                target = largest
                result.warnings.append(
                    f"{os.path.basename(animation_path)}: nenhum esqueleto do "
                    f"arquivo tem {frm.num_bones} osso(s); a animacao foi para o "
                    f"esqueleto de {len(groups[largest].skeleton)} osso(s)"
                )
            else:
                # Cada animacao entra em UM grupo. Coloca-la em todos os que tem
                # a mesma contagem de ossos criaria varias actions de mesmo nome
                # no Blender, o que confunde mais do que ajuda; e o FRM pertence a
                # um personagem, nao a vários.
                target = candidates[0]
                if len(candidates) > 1:
                    ambiguous += 1
            groups[target].animations.append(frm_format.frm_to_animation(frm, name))

        if ambiguous:
            result.warnings.append(
                f"{ambiguous} animacao(oes) serviam a mais de um esqueleto com a "
                f"mesma contagem de ossos; cada uma foi para o primeiro"
            )

        scenes = [groups[signature] for signature in order]
        if len(scenes) > 1:
            result.warnings.append(
                f"os modelos usam {len(scenes)} esqueletos diferentes "
                f"({', '.join(str(len(s.skeleton)) for s in scenes)} ossos); cada "
                f"um virou uma armature separada dentro do mesmo arquivo"
            )

        for scene in scenes:
            scene.to_right_handed()

        data = export_glb(
            scenes,
            GlbOptions(
                double_sided=options.double_sided,
                alpha_mode=options.alpha_mode,
                pretty_json=options.pretty_json,
            ),
        )
        _write_file(output_path, data)

        result.ok = True
        result.outputs = [output_path]
        result.bytes_written = len(data)
        result.summary = _merged_summary(scenes)
    except Exception as error:  # noqa: BLE001
        _record_failure(result, error)

    return result


def _merged_summary(scenes: list[Scene]) -> str:
    meshes = sum(len(s.meshes) for s in scenes)
    vertices = sum(s.vertex_count for s in scenes)
    triangles = sum(s.triangle_count for s in scenes)
    animations = sum(len(s.animations) for s in scenes)
    keyframes = sum(len(a.frames) for s in scenes for a in s.animations)
    parts = [
        f"{meshes} malha(s)",
        f"{vertices} vertices",
        f"{triangles} triangulos",
        f"{len(scenes)} esqueleto(s)",
        f"{animations} animacao(oes)",
    ]
    if keyframes:
        parts.append(f"{keyframes} keyframes")
    return ", ".join(parts)


# --------------------------------------------------- P3M/FRM -> GLB (direta)


def convert_model(
    model_path: str | None,
    output_path: str,
    animation_paths: list[str] | tuple[str, ...] = (),
    options: ConvertOptions | None = None,
) -> ConvertResult:
    """Converte um P3M (e FRMs opcionais) em um arquivo GLB."""
    options = options or ConvertOptions()
    source = model_path or (animation_paths[0] if animation_paths else "<vazio>")
    result = ConvertResult(source=source, direction=Direction.TO_GLTF)

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

        _write_file(output_path, data)

        result.ok = True
        result.outputs = [output_path]
        result.bytes_written = len(data)
        result.summary = scene.summary()
        result.texture_used = texture_path
    except Exception as error:  # noqa: BLE001 - a CLI/GUI relata por arquivo
        _record_failure(result, error)

    return result


# ---------------------------------------------------- GLB -> P3M/FRM (inversa)


def convert_to_gc(
    gltf_path: str,
    output_dir: str,
    options: ConvertOptions | None = None,
) -> ConvertResult:
    """Converte um `.glb`/`.gltf` em um `.p3m` e, opcionalmente, varios `.frm`.

    Gera:

        <nome>.p3m                    a malha e o esqueleto
        <nome>_<animacao>.frm         uma por animacao do glTF
        <nome>.png                    a textura base color, se estiver embutida
    """
    options = options or ConvertOptions()
    result = ConvertResult(source=gltf_path, direction=Direction.TO_GC)

    try:
        stem = os.path.splitext(os.path.basename(gltf_path))[0]
        document = gltf_in.load_gltf(gltf_path)
        scene = gltf_in.gltf_to_scene(
            document, stem, DEFAULT_FPS, result.warnings
        )

        if not scene.meshes:
            raise ValueError(
                "o glTF nao tem nenhuma malha triangulada para converter"
            )

        if options.normalize_normals:
            fixed = scene.normalize_normals()
            if fixed:
                result.warnings.append(
                    f"{fixed} normal(is) nao unitaria(s) normalizada(s)"
                )

        # Um P3M sempre declara pelo menos um par de ossos, mesmo quando a malha
        # e estatica: os arquivos oficiais desse tipo tem 1 PositionBone,
        # 1 AngleBone e o sentinela 0xFF no indice de osso de todo vertice.
        # Reproduzimos essa forma, deixando os vertices sem joint para que o
        # escritor grave 0xFF. Atribuir os vertices ao osso raiz mudaria o
        # arquivo sem necessidade.
        if not scene.skeleton:
            from .scene import Joint

            scene.skeleton = [Joint(name="bone_0")]

        scene.to_left_handed()

        texture_name = ""
        texture_png = None
        if options.extract_texture:
            texture_png = gltf_in.extract_base_color_png(document)
            if texture_png:
                texture_name = stem + ".png"

        p3m = p3m_format.scene_to_p3m(scene, texture_name)
        p3m_path = os.path.join(output_dir, stem + ".p3m")
        written = p3m_format.save_p3m(p3m, _ensure_dir(p3m_path))
        result.outputs.append(p3m_path)
        result.bytes_written += written

        if texture_png:
            texture_path = os.path.join(output_dir, texture_name)
            _write_file(texture_path, texture_png)
            result.outputs.append(texture_path)
            result.bytes_written += len(texture_png)
            result.texture_used = texture_path

        if options.export_animations:
            num_bones = len(scene.skeleton)
            for animation in scene.animations:
                safe = _safe_name(animation.name) or "anim"
                filename = f"{options.animation_prefix}{stem}_{safe}.frm"
                frm_path = os.path.join(output_dir, filename)
                try:
                    frm = frm_format.animation_to_frm(animation, num_bones)
                except frm_format.InvalidFrmError as error:
                    result.warnings.append(
                        f"animacao {animation.name!r} nao gravada: {error}"
                    )
                    continue
                written = frm_format.save_frm(frm, _ensure_dir(frm_path))
                result.outputs.append(frm_path)
                result.bytes_written += written
        elif scene.animations:
            result.warnings.append(
                f"{len(scene.animations)} animacao(oes) presentes no glTF nao "
                f"foram gravadas (exportacao de animacoes desligada)"
            )

        result.ok = True
        result.summary = scene.summary()
    except Exception as error:  # noqa: BLE001
        _record_failure(result, error)

    return result


def _safe_name(name: str) -> str:
    """Reduz um nome de animacao a algo seguro para nome de arquivo."""
    keep = []
    for char in name.strip():
        if char.isalnum() or char in "-_":
            keep.append(char)
        elif char in " .":
            keep.append("_")
    return "".join(keep)[:60].strip("_")


def _ensure_dir(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    return path


def _write_file(path: str, data: bytes) -> None:
    _ensure_dir(path)
    with open(path, "wb") as handle:
        handle.write(data)


def _record_failure(result: ConvertResult, error: Exception) -> None:
    result.ok = False
    result.error = f"{type(error).__name__}: {error}"
    result.traceback = traceback.format_exc()


# --------------------------------------------------------------- lote e busca


def find_animations_for_model(model_path: str, animation_dir: str) -> list[str]:
    """Lista os FRM de uma pasta que parecem pertencer a um modelo.

    O jogo nao guarda essa ligacao em nenhum lugar, entao usamos o unico
    critario confiavel: um FRM so pode animar um modelo com o mesmo numero de
    ossos.
    """
    if not os.path.isdir(animation_dir):
        return []
    paths = [
        os.path.join(animation_dir, name)
        for name in sorted(os.listdir(animation_dir))
        if name.lower().endswith(".frm")
    ]
    index = AnimationIndex(paths)
    chosen, _ = index.select_for(model_path, match_by_bones=True)
    return chosen


class AnimationIndex:
    """Agrupa arquivos `.frm` por numero de ossos, lendo cada um uma unica vez.

    Existe para que converter 80 modelos com 68 animacoes disponiveis nao releia
    os mesmos 68 arquivos 80 vezes. A GUI e a CLI usam a mesma instancia.
    """

    def __init__(self, animation_paths: list[str] | tuple[str, ...] = ()) -> None:
        #: numero de ossos -> caminhos
        self.by_bone_count: dict[int, list[str]] = {}
        #: arquivos que nao puderam ser lidos, com o motivo
        self.unreadable: list[tuple[str, str]] = []
        self.paths: list[str] = []

        for path in animation_paths:
            try:
                count = frm_format.load_frm(path).num_bones
            except Exception as error:  # noqa: BLE001
                self.unreadable.append((path, str(error)))
                continue
            self.by_bone_count.setdefault(count, []).append(path)
            self.paths.append(path)

    def __len__(self) -> int:
        return len(self.paths)

    @property
    def bone_counts(self) -> list[int]:
        return sorted(self.by_bone_count)

    def select_for(
        self, model_path: str, match_by_bones: bool = True
    ) -> tuple[list[str], list[str]]:
        """Escolhe as animacoes para um modelo. Devolve `(escolhidas, avisos)`.

        Com `match_by_bones=False`, devolve todas — util quando o usuario sabe
        que as animacoes pertencem ao modelo apesar da contagem de ossos, ou
        quando quer todas num unico GLB de propósito.

        Quando o casamento por ossos nao encontra nada, o aviso diz **por que**,
        listando as contagens disponiveis. Sem isso, o modelo sairia sem animacao
        nenhuma e a causa ficaria invisivel.
        """
        warnings: list[str] = []
        if not self.paths:
            return [], warnings

        if not match_by_bones:
            return list(self.paths), warnings

        try:
            bones = p3m_format.load_p3m(model_path).num_angle_bones
        except (p3m_format.InvalidP3mError, OSError) as error:
            warnings.append(
                f"nao foi possivel ler os ossos do modelo para casar as "
                f"animacoes ({error}); nenhuma animacao foi incluida"
            )
            return [], warnings

        chosen = self.by_bone_count.get(bones, [])
        if not chosen:
            available = ", ".join(str(count) for count in self.bone_counts)
            warnings.append(
                f"nenhuma das {len(self.paths)} animacao(oes) carregada(s) casa "
                f"com este modelo: ele tem {bones} osso(s) e as animacoes tem "
                f"{available}. Se voce sabe que elas pertencem a este modelo, "
                f"desligue o casamento por numero de ossos."
            )
        return chosen, warnings


def collect_inputs(
    paths: list[str], recursive: bool = True
) -> tuple[list[str], list[str], list[str]]:
    """Expande arquivos e pastas em `(modelos_p3m, animacoes_frm, gltf)`."""
    models: list[str] = []
    animations: list[str] = []
    gltfs: list[str] = []

    def classify(path: str) -> None:
        kind = classify_path(path)
        if kind == "p3m":
            models.append(path)
        elif kind == "frm":
            animations.append(path)
        elif kind == "gltf":
            gltfs.append(path)

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

    return sorted(models), sorted(animations), sorted(gltfs)


def convert_batch(
    model_paths: list[str],
    output_dir: str,
    options: ConvertOptions | None = None,
    animation_dir: str | None = None,
    animation_paths: list[str] | tuple[str, ...] = (),
    progress=None,
) -> list[ConvertResult]:
    """Converte varios P3M para GLB, numa pasta de saida.

    As animacoes podem vir de uma pasta (`animation_dir`) ou de uma lista
    explicita (`animation_paths`). Cada `.frm` e lido uma unica vez, mesmo com
    centenas de modelos.

    `progress` e um callable opcional `(indice, total, caminho)` chamado antes de
    cada arquivo, para a interface atualizar a barra de progresso.
    """
    options = options or ConvertOptions()

    paths = list(animation_paths)
    if animation_dir and os.path.isdir(animation_dir):
        paths.extend(
            os.path.join(animation_dir, name)
            for name in sorted(os.listdir(animation_dir))
            if name.lower().endswith(".frm")
        )
    index = AnimationIndex(paths)

    results: list[ConvertResult] = []
    total = len(model_paths)

    for position, model_path in enumerate(model_paths):
        if progress is not None:
            progress(position, total, model_path)
        stem = os.path.splitext(os.path.basename(model_path))[0]
        output_path = os.path.join(output_dir, stem + ".glb")
        chosen, warnings = index.select_for(
            model_path, options.match_animations_by_bones
        )
        result = convert_model(model_path, output_path, chosen, options)
        result.warnings[:0] = warnings
        results.append(result)

    if progress is not None:
        progress(total, total, "")
    return results
