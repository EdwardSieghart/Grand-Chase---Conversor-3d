"""Exportador GLB (glTF 2.0 binario).

Escolhemos GLB como formato de saida porque e um arquivo unico, autocontido
(geometria, esqueleto, animacoes e textura embutidas), e e importado nativamente
pelo Blender, Unity, Godot, Three.js e pelo visualizador do Windows, sem plugin.

Referencia: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html

As cenas recebidas **devem** estar em right-handed (chame
`Scene.to_right_handed()` antes), porque o glTF define Y-up right-handed. O
exportador nao faz a conversao por conta propria para nao esconder o passo de quem
le o codigo.

Varios esqueletos num arquivo
-----------------------------
`export_glb` aceita uma cena ou **uma lista de cenas**. Cada cena vira um grupo
independente dentro do mesmo GLB, com o seu proprio esqueleto (`skin`), as suas
malhas e as suas animacoes.

Isso existe porque juntar varios modelos do Grand Chase num unico arquivo e o caso
comum — corpo, rosto, cabelo e arma de um personagem — mas eles **nem sempre
compartilham o esqueleto**. Medindo os 127 modelos do conjunto de teste, ha 18
esqueletos distintos, e sete deles tem exatamente 15 ossos: a contagem de ossos
nao identifica o esqueleto. Forçar tudo num esqueleto unico misturaria bind poses
diferentes e deformaria a malha. O glTF permite varias `skins` no mesmo arquivo, e
e isso que usamos.

Mapeamento adotado
------------------
Hierarquia de nos, com um bloco por grupo:

    grupo 0:  joints 0..J0-1,  depois o no "root_0"
    grupo 1:  joints ...,      depois o no "root_1"
    ...
    depois:   um no por malha, cada um apontando para a skin do seu grupo

Como os joints do Grand Chase so tem translacao no bind pose, a inverse bind
matrix de cada joint e simplesmente uma translacao pelo negativo da sua posicao
mundial. As animacoes viram: um canal de `translation` no no "root" do grupo (o
deslocamento do personagem) e um canal de `rotation` por joint.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

from ..binary import BinaryWriter
from ..mathutil import mat4_to_quaternion
from ..scene import NO_JOINT, Mesh, Scene

__all__ = ["GlbOptions", "export_glb", "write_glb"]

# Constantes de componentType do glTF.
_UNSIGNED_BYTE = 5121
_UNSIGNED_SHORT = 5123
_UNSIGNED_INT = 5125
_FLOAT = 5126

_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963

_GLB_MAGIC = 0x46546C67  # "glTF"
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A  # "JSON"
_CHUNK_BIN = 0x004E4942  # "BIN\0"

GENERATOR = "Grand Chase 3D Importer (gc3d)"


@dataclass
class GlbOptions:
    """Opcoes de exportacao."""

    #: Textura aplicada as malhas que nao trazem a sua propria em
    #: `Mesh.texture_png`. Mantida para o caso de um modelo unico.
    texture_png: bytes | None = None
    #: Renderiza as faces dos dois lados. Ligado por padrao porque muitos
    #: modelos do Grand Chase sao modelados como superficies abertas.
    double_sided: bool = True
    #: "OPAQUE", "MASK" ou "BLEND". Se None, decide sozinho conforme a textura.
    alpha_mode: str | None = None
    #: Grava o JSON legivel (util para depuracao). Gera arquivo maior.
    pretty_json: bool = False


@dataclass
class _Group:
    """Um esqueleto com as suas malhas e animacoes, dentro do GLB."""

    scene: Scene
    #: Indice do primeiro no de joint deste grupo.
    joint_offset: int = 0
    #: Indice do no "root" deste grupo, ou None se nao houver esqueleto.
    root_node: int | None = None
    #: Indice da skin deste grupo, ou None.
    skin_index: int | None = None
    #: Indices dos nos de malha deste grupo.
    mesh_nodes: list[int] = field(default_factory=list)

    @property
    def num_joints(self) -> int:
        return len(self.scene.skeleton)


class _GltfBuilder:
    """Acumula o JSON e o buffer binario de um GLB."""

    def __init__(self) -> None:
        self.buffer = BinaryWriter()
        self.accessors: list[dict] = []
        self.buffer_views: list[dict] = []
        self.meshes: list[dict] = []
        self.nodes: list[dict] = []
        self.skins: list[dict] = []
        self.animations: list[dict] = []
        self.materials: list[dict] = []
        self.textures: list[dict] = []
        self.images: list[dict] = []
        self.samplers: list[dict] = []
        #: Indices dos nos que sao raiz da cena.
        self.scene_roots: list[int] = []
        #: Cache de textura -> indice de material, para nao duplicar a mesma
        #: imagem quando varias malhas usam o mesmo arquivo.
        self._material_cache: dict[bytes | None, int] = {}

    # ------------------------------------------------------------ acessores

    def add_buffer_view(self, data: bytes, target: int | None = None) -> int:
        """Copia `data` para o buffer e cria um bufferView apontando para ele."""
        # O glTF exige que byteOffset de um bufferView usado por accessor seja
        # multiplo do tamanho do componente; alinhar em 4 satisfaz todos os
        # tipos que usamos e e o que os validadores esperam.
        self.buffer.align(4)
        offset = self.buffer.tell()
        self.buffer.bytes(data)
        view: dict = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        }
        if target is not None:
            view["target"] = target
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def add_accessor(
        self,
        data: bytes,
        component_type: int,
        type_: str,
        count: int,
        minimum: list[float] | None = None,
        maximum: list[float] | None = None,
        target: int | None = None,
    ) -> int:
        view = self.add_buffer_view(data, target)
        accessor: dict = {
            "bufferView": view,
            "byteOffset": 0,
            "componentType": component_type,
            "count": count,
            "type": type_,
        }
        if minimum is not None:
            accessor["min"] = minimum
        if maximum is not None:
            accessor["max"] = maximum
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    # ---------------------------------------------------------------- saida

    def to_glb(self, pretty: bool = False) -> bytes:
        root: dict = {
            "asset": {"version": "2.0", "generator": GENERATOR},
            "scene": 0,
        }
        for key, value in (
            ("nodes", self.nodes),
            ("meshes", self.meshes),
            ("skins", self.skins),
            ("animations", self.animations),
            ("materials", self.materials),
            ("textures", self.textures),
            ("images", self.images),
            ("samplers", self.samplers),
            ("accessors", self.accessors),
            ("bufferViews", self.buffer_views),
        ):
            if value:
                root[key] = value

        bin_chunk = self.buffer.getvalue()
        # O comprimento declarado do buffer deve cobrir o padding do chunk.
        bin_padding = (-len(bin_chunk)) % 4
        root["buffers"] = [{"byteLength": len(bin_chunk) + bin_padding}]
        root["scenes"] = [{"nodes": self.scene_roots}]

        indent = 2 if pretty else None
        separators = None if pretty else (",", ":")
        json_bytes = json.dumps(
            root, indent=indent, separators=separators, ensure_ascii=False
        ).encode("utf-8")
        # O chunk JSON e preenchido com espacos; o BIN com zeros.
        json_bytes += b" " * ((-len(json_bytes)) % 4)
        bin_chunk += b"\0" * bin_padding

        total = 12 + 8 + len(json_bytes) + 8 + len(bin_chunk)
        out = bytearray()
        out += struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total)
        out += struct.pack("<II", len(json_bytes), _CHUNK_JSON)
        out += json_bytes
        out += struct.pack("<II", len(bin_chunk), _CHUNK_BIN)
        out += bin_chunk
        return bytes(out)


# ------------------------------------------------------------------- fachada


def export_glb(
    scenes: Scene | list[Scene], options: GlbOptions | None = None
) -> bytes:
    """Serializa uma cena, ou varias, num unico arquivo GLB.

    Cada cena da lista vira um grupo com esqueleto proprio. Todas precisam estar
    em right-handed.
    """
    options = options or GlbOptions()
    groups_input = [scenes] if isinstance(scenes, Scene) else list(scenes)
    groups_input = [s for s in groups_input if s.meshes or s.animations]
    if not groups_input:
        raise ValueError("nada para exportar: nenhuma malha e nenhuma animacao")

    for scene in groups_input:
        if not scene.right_handed:
            raise ValueError(
                "a cena ainda esta em left-handed; chame Scene.to_right_handed() "
                "antes de exportar para glTF"
            )

    builder = _GltfBuilder()
    groups = [_Group(scene=scene) for scene in groups_input]

    # 1. Nos de joint e no "root" de cada grupo, em blocos consecutivos.
    cursor = 0
    for index, group in enumerate(groups):
        group.joint_offset = cursor
        cursor = _add_joint_nodes(builder, group, index, len(groups))
    # 2. Nos de malha, depois de todos os esqueletos.
    mesh_counter = 0
    for group in groups:
        cursor, mesh_counter = _add_mesh_nodes(builder, group, cursor, mesh_counter)

    # 3. Malhas, materiais e skins.
    for group in groups:
        _add_meshes(builder, group, options)
        _add_skin(builder, group)
    # 4. Animacoes, que referenciam os nos ja criados.
    for group in groups:
        _add_animations(builder, group)

    roots: list[int] = [g.root_node for g in groups if g.root_node is not None]
    for group in groups:
        roots.extend(group.mesh_nodes)
    builder.scene_roots = roots

    return builder.to_glb(options.pretty_json)


def write_glb(
    scenes: Scene | list[Scene], path, options: GlbOptions | None = None
) -> int:
    """Exporta e grava em disco. Devolve o tamanho em bytes."""
    data = export_glb(scenes, options)
    with open(path, "wb") as handle:
        handle.write(data)
    return len(data)


# ---------------------------------------------------------------------- nos


def _add_joint_nodes(
    builder: _GltfBuilder, group: _Group, index: int, total_groups: int
) -> int:
    """Cria os nos de joint e o no raiz do grupo. Devolve o proximo indice livre."""
    scene = group.scene
    offset = group.joint_offset

    for position, joint in enumerate(scene.skeleton):
        node: dict = {"name": joint.name or f"bone_{position}"}
        if joint.children:
            # Os indices de filho sao locais ao esqueleto; viram indices de no.
            node["children"] = [offset + child for child in joint.children]
        if joint.translation != (0.0, 0.0, 0.0):
            node["translation"] = list(joint.translation)
        builder.nodes.append(node)

    if not scene.skeleton:
        group.root_node = None
        return offset

    # Com um grupo so, mantemos o nome "root" — e o que o importador procura ao
    # trazer o arquivo de volta. Com varios, cada um recebe um sufixo.
    name = "root" if total_groups == 1 else f"root_{index}"
    root_node: dict = {"name": name}
    roots = scene.root_joints()
    if roots:
        root_node["children"] = [offset + r for r in roots]
    builder.nodes.append(root_node)
    group.root_node = offset + group.num_joints
    return group.root_node + 1


def _add_mesh_nodes(
    builder: _GltfBuilder, group: _Group, cursor: int, mesh_counter: int
) -> tuple[int, int]:
    """Cria um no por malha do grupo.

    As malhas em si sao criadas depois (precisam dos acessores), mas o no ja tem
    de apontar para o indice que a malha vai receber. Como `_add_meshes` percorre
    os grupos na mesma ordem, basta manter um contador corrido — daí o
    `mesh_counter` entrar e sair da funcao.
    """
    for mesh in group.scene.meshes:
        builder.nodes.append({"name": f"mesh_{mesh.name}", "mesh": mesh_counter})
        group.mesh_nodes.append(cursor)
        cursor += 1
        mesh_counter += 1
    return cursor, mesh_counter


# ------------------------------------------------------------------ material


def _add_material(
    builder: _GltfBuilder, options: GlbOptions, texture_png: bytes | None, name: str
) -> int:
    """Cria (ou reaproveita) um material PBR, com textura embutida se houver."""
    cache_key = texture_png
    if cache_key in builder._material_cache:
        return builder._material_cache[cache_key]

    material: dict = {
        "name": name,
        "doubleSided": options.double_sided,
        "pbrMetallicRoughness": {
            # Modelos do Grand Chase sao pintados a mao: sem metalicidade e
            # com rugosidade alta evita brilho especular artificial.
            "metallicFactor": 0.0,
            "roughnessFactor": 0.9,
        },
    }

    has_alpha = False
    if texture_png:
        view = builder.add_buffer_view(texture_png)
        builder.images.append({"bufferView": view, "mimeType": "image/png"})
        if not builder.samplers:
            builder.samplers.append(
                {
                    "magFilter": 9729,  # LINEAR
                    "minFilter": 9987,  # LINEAR_MIPMAP_LINEAR
                    "wrapS": 10497,  # REPEAT
                    "wrapT": 10497,  # REPEAT
                }
            )
        builder.textures.append(
            {"sampler": 0, "source": len(builder.images) - 1}
        )
        material["pbrMetallicRoughness"]["baseColorTexture"] = {
            "index": len(builder.textures) - 1
        }
        has_alpha = _png_has_alpha(texture_png)

    alpha_mode = options.alpha_mode
    if alpha_mode is None:
        # MASK reproduz o alpha-test que o jogo usa em cabelo, capas e efeitos.
        alpha_mode = "MASK" if has_alpha else "OPAQUE"
    if alpha_mode != "OPAQUE":
        material["alphaMode"] = alpha_mode
        if alpha_mode == "MASK":
            material["alphaCutoff"] = 0.5

    builder.materials.append(material)
    index = len(builder.materials) - 1
    builder._material_cache[cache_key] = index
    return index


def _png_has_alpha(png: bytes) -> bool:
    """Le o colorType do chunk IHDR para saber se o PNG tem canal alfa."""
    # 8 bytes de assinatura + 4 de tamanho + 4 de tipo = IHDR comeca em 16;
    # colorType e o 10o byte do IHDR (offset 25 no arquivo).
    if len(png) < 26 or png[12:16] != b"IHDR":
        return False
    return png[25] in (4, 6)  # grayscale+alpha, RGBA


# ------------------------------------------------------------------- malhas


def _add_meshes(builder: _GltfBuilder, group: _Group, options: GlbOptions) -> None:
    num_joints = group.num_joints
    for mesh in group.scene.meshes:
        primitive = _build_primitive(builder, mesh, num_joints)
        # A textura da malha tem prioridade; `options.texture_png` e o fallback
        # para o caso de um modelo unico convertido pela via antiga.
        texture = (
            mesh.texture_png if mesh.texture_png is not None else options.texture_png
        )
        primitive["material"] = _add_material(
            builder, options, texture, f"mat_{mesh.name}"
        )
        builder.meshes.append(
            {"name": f"mesh_{mesh.name}", "primitives": [primitive]}
        )


def _build_primitive(builder: _GltfBuilder, mesh: Mesh, num_joints: int) -> dict:
    vertices = mesh.vertices
    count = len(vertices)

    positions = BinaryWriter()
    normals = BinaryWriter()
    uvs = BinaryWriter()
    joints = BinaryWriter()
    weights = BinaryWriter()

    min_pos = [float("inf")] * 3
    max_pos = [float("-inf")] * 3
    for vertex in vertices:
        px, py, pz = vertex.position
        positions.f32s((px, py, pz))
        if px < min_pos[0]:
            min_pos[0] = px
        if py < min_pos[1]:
            min_pos[1] = py
        if pz < min_pos[2]:
            min_pos[2] = pz
        if px > max_pos[0]:
            max_pos[0] = px
        if py > max_pos[1]:
            max_pos[1] = py
        if pz > max_pos[2]:
            max_pos[2] = pz

        normals.f32s(vertex.normal)
        uvs.f32s(vertex.uv)

        if num_joints:
            joint = vertex.joint
            if joint == NO_JOINT:
                joints.bytes(bytes((0, 0, 0, 0)))
                weights.f32s((0.0, 0.0, 0.0, 0.0))
            else:
                joints.bytes(bytes((joint & 0xFF, 0, 0, 0)))
                weights.f32s((vertex.weight, 0.0, 0.0, 0.0))

    if count == 0:
        min_pos = [0.0, 0.0, 0.0]
        max_pos = [0.0, 0.0, 0.0]

    attributes: dict = {
        "POSITION": builder.add_accessor(
            positions.getvalue(), _FLOAT, "VEC3", count, min_pos, max_pos,
            target=_TARGET_ARRAY_BUFFER,
        ),
        "NORMAL": builder.add_accessor(
            normals.getvalue(), _FLOAT, "VEC3", count,
            target=_TARGET_ARRAY_BUFFER,
        ),
        "TEXCOORD_0": builder.add_accessor(
            uvs.getvalue(), _FLOAT, "VEC2", count,
            target=_TARGET_ARRAY_BUFFER,
        ),
    }
    if num_joints:
        attributes["JOINTS_0"] = builder.add_accessor(
            joints.getvalue(), _UNSIGNED_BYTE, "VEC4", count,
            target=_TARGET_ARRAY_BUFFER,
        )
        attributes["WEIGHTS_0"] = builder.add_accessor(
            weights.getvalue(), _FLOAT, "VEC4", count,
            target=_TARGET_ARRAY_BUFFER,
        )

    # Usa u16 quando cabe (metade do tamanho); u32 nas malhas grandes.
    if count > 0xFFFF:
        index_data = struct.pack(f"<{len(mesh.indices)}I", *mesh.indices)
        index_type = _UNSIGNED_INT
    else:
        index_data = struct.pack(f"<{len(mesh.indices)}H", *mesh.indices)
        index_type = _UNSIGNED_SHORT
    indices_accessor = builder.add_accessor(
        index_data, index_type, "SCALAR", len(mesh.indices),
        target=_TARGET_ELEMENT_ARRAY_BUFFER,
    )

    return {
        "attributes": attributes,
        "indices": indices_accessor,
        "mode": 4,  # TRIANGLES
    }


# --------------------------------------------------------------------- skin


def _add_skin(builder: _GltfBuilder, group: _Group) -> None:
    num_joints = group.num_joints
    if not num_joints:
        return

    scene = group.scene
    offset = group.joint_offset

    # Inverse bind matrix = translacao pelo negativo da posicao mundial do
    # joint. Isso funciona porque o bind pose do Grand Chase e puramente
    # translacional (nenhuma rotacao ou escala nos ossos).
    writer = BinaryWriter()
    for index in range(num_joints):
        wx, wy, wz = scene.joint_world_translation(index)
        writer.f32s(
            (
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                -wx, -wy, -wz, 1.0,
            )
        )
    accessor = builder.add_accessor(writer.getvalue(), _FLOAT, "MAT4", num_joints)

    builder.skins.append(
        {
            "name": f"skin_{len(builder.skins)}",
            "inverseBindMatrices": accessor,
            "joints": [offset + i for i in range(num_joints)],
            "skeleton": group.root_node,
        }
    )
    group.skin_index = len(builder.skins) - 1
    for node_index in group.mesh_nodes:
        builder.nodes[node_index]["skin"] = group.skin_index


# ---------------------------------------------------------------- animacoes


def _add_animations(builder: _GltfBuilder, group: _Group) -> None:
    num_joints = group.num_joints
    if not num_joints or group.root_node is None:
        return
    offset = group.joint_offset

    for animation in group.scene.animations:
        if not animation.frames:
            continue

        times = animation.times()
        time_accessor = builder.add_accessor(
            struct.pack(f"<{len(times)}f", *times),
            _FLOAT,
            "SCALAR",
            len(times),
            [times[0]],
            [times[-1]],
        )

        samplers: list[dict] = []
        channels: list[dict] = []

        # Canal de deslocamento do personagem, no no "root" do grupo.
        translations = BinaryWriter()
        for frame in animation.frames:
            translations.f32s(frame.translation)
        translation_accessor = builder.add_accessor(
            translations.getvalue(), _FLOAT, "VEC3", len(animation.frames)
        )
        channels.append(
            {
                "sampler": len(samplers),
                "target": {"node": group.root_node, "path": "translation"},
            }
        )
        samplers.append(
            {
                "input": time_accessor,
                "output": translation_accessor,
                # O jogo usa curvas bezier com tangentes desconhecidas; como os
                # frames sao densos (55 Hz), linear e visualmente equivalente.
                "interpolation": "LINEAR",
            }
        )

        # Um canal de rotacao por joint.
        for joint_index in range(num_joints):
            rotations = BinaryWriter()
            usable = 0
            for frame in animation.frames:
                if joint_index < len(frame.transforms):
                    quat = mat4_to_quaternion(frame.transforms[joint_index])
                    usable += 1
                else:
                    quat = (0.0, 0.0, 0.0, 1.0)
                rotations.f32s(quat)
            if usable == 0:
                # A animacao tem menos ossos que o esqueleto: nao inventa canal.
                continue
            rotation_accessor = builder.add_accessor(
                rotations.getvalue(), _FLOAT, "VEC4", len(animation.frames)
            )
            channels.append(
                {
                    "sampler": len(samplers),
                    "target": {"node": offset + joint_index, "path": "rotation"},
                }
            )
            samplers.append(
                {
                    "input": time_accessor,
                    "output": rotation_accessor,
                    "interpolation": "LINEAR",
                }
            )

        builder.animations.append(
            {"name": animation.name, "samplers": samplers, "channels": channels}
        )
