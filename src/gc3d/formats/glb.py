"""Exportador GLB (glTF 2.0 binario).

Escolhemos GLB como formato de saida porque e um arquivo unico, autocontido
(geometria, esqueleto, animacoes e textura embutidas), e e importado nativamente
pelo Blender, Unity, Godot, Three.js e pelo visualizador do Windows, sem plugin.

Referencia: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html

A cena recebida **deve** estar em right-handed (chame `Scene.to_right_handed()`
antes), porque o glTF define Y-up right-handed. O exportador nao faz a conversao
por conta propria para nao esconder o passo de quem le o codigo.

Mapeamento adotado
------------------
Hierarquia de nos:

    0 .. J-1    um no por joint, na mesma ordem de `Scene.skeleton`
    J           no "root", pai de todos os joints sem pai
    J+1 ...     um no por malha, cada um apontando para a skin

Como os joints do Grand Chase so tem translacao no bind pose, a inverse bind
matrix de cada joint e simplesmente uma translacao pelo negativo da sua posicao
mundial. As animacoes viram: um canal de `translation` no no "root" (o
deslocamento do personagem) e um canal de `rotation` por joint.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from ..binary import BinaryWriter
from ..mathutil import mat4_to_quaternion
from ..scene import NO_JOINT, Scene

__all__ = ["GlbOptions", "export_glb", "write_glb"]

# Constantes de componentType do glTF.
_UNSIGNED_BYTE = 5121
_UNSIGNED_SHORT = 5123
_UNSIGNED_INT = 5125
_FLOAT = 5126

_GLB_MAGIC = 0x46546C67  # "glTF"
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A  # "JSON"
_CHUNK_BIN = 0x004E4942  # "BIN\0"

GENERATOR = "Grand Chase 3D Importer (gc3d)"


@dataclass
class GlbOptions:
    """Opcoes de exportacao."""

    #: Bytes de uma imagem PNG a ser embutida como textura base color.
    texture_png: bytes | None = None
    #: Renderiza as faces dos dois lados. Ligado por padrao porque muitos
    #: modelos do Grand Chase sao modelados como superficies abertas.
    double_sided: bool = True
    #: "OPAQUE", "MASK" ou "BLEND". Se None, decide sozinho conforme a textura.
    alpha_mode: str | None = None
    #: Grava tambem o JSON legivel ao lado (util para depuracao).
    pretty_json: bool = False


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
        #: Indices dos nos que sao raiz da cena. Preenchido antes de `to_glb`.
        self.scene_roots: list[int] = []

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
        if self.nodes:
            root["nodes"] = self.nodes
        if self.meshes:
            root["meshes"] = self.meshes
        if self.skins:
            root["skins"] = self.skins
        if self.animations:
            root["animations"] = self.animations
        if self.materials:
            root["materials"] = self.materials
        if self.textures:
            root["textures"] = self.textures
        if self.images:
            root["images"] = self.images
        if self.samplers:
            root["samplers"] = self.samplers
        if self.accessors:
            root["accessors"] = self.accessors
        if self.buffer_views:
            root["bufferViews"] = self.buffer_views

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


def export_glb(scene: Scene, options: GlbOptions | None = None) -> bytes:
    """Serializa uma `Scene` right-handed em bytes de um arquivo GLB."""
    options = options or GlbOptions()
    if not scene.right_handed:
        raise ValueError(
            "a cena ainda esta em left-handed; chame Scene.to_right_handed() "
            "antes de exportar para glTF"
        )

    builder = _GltfBuilder()
    num_joints = len(scene.skeleton)

    material_index = _add_material(builder, options)
    _add_nodes(builder, scene, num_joints)
    _add_meshes(builder, scene, num_joints, material_index)
    skin_index = _add_skin(builder, scene, num_joints)
    _attach_skin_to_mesh_nodes(builder, scene, num_joints, skin_index)
    _add_animations(builder, scene, num_joints)

    # Raizes da cena: o no root do esqueleto e os nos de malha.
    roots: list[int] = []
    if num_joints:
        roots.append(num_joints)
    mesh_node_start = num_joints + 1 if num_joints else 0
    roots.extend(range(mesh_node_start, mesh_node_start + len(scene.meshes)))
    builder.scene_roots = roots

    return builder.to_glb(options.pretty_json)


def write_glb(scene: Scene, path, options: GlbOptions | None = None) -> int:
    """Exporta a cena e grava em disco. Devolve o tamanho em bytes."""
    data = export_glb(scene, options)
    with open(path, "wb") as handle:
        handle.write(data)
    return len(data)


# ------------------------------------------------------------------ material


def _add_material(builder: _GltfBuilder, options: GlbOptions) -> int | None:
    """Cria um material PBR simples, com textura embutida se houver."""
    material: dict = {
        "name": "gc3d_material",
        "doubleSided": options.double_sided,
        "pbrMetallicRoughness": {
            # Modelos do Grand Chase sao pintados a mao: sem metalicidade e
            # com rugosidade alta evita brilho especular artificial.
            "metallicFactor": 0.0,
            "roughnessFactor": 0.9,
        },
    }

    has_alpha = False
    if options.texture_png:
        view = builder.add_buffer_view(options.texture_png)
        builder.images.append({"bufferView": view, "mimeType": "image/png"})
        builder.samplers.append(
            {
                "magFilter": 9729,  # LINEAR
                "minFilter": 9987,  # LINEAR_MIPMAP_LINEAR
                "wrapS": 10497,  # REPEAT
                "wrapT": 10497,  # REPEAT
            }
        )
        builder.textures.append({"sampler": 0, "source": 0})
        material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
        has_alpha = _png_has_alpha(options.texture_png)

    alpha_mode = options.alpha_mode
    if alpha_mode is None:
        # MASK reproduz o alpha-test que o jogo usa em cabelo, capas e efeitos.
        alpha_mode = "MASK" if has_alpha else "OPAQUE"
    if alpha_mode != "OPAQUE":
        material["alphaMode"] = alpha_mode
        if alpha_mode == "MASK":
            material["alphaCutoff"] = 0.5

    builder.materials.append(material)
    return 0


def _png_has_alpha(png: bytes) -> bool:
    """Le o colorType do chunk IHDR para saber se o PNG tem canal alfa."""
    # 8 bytes de assinatura + 4 de tamanho + 4 de tipo = IHDR comeca em 16;
    # colorType e o 10o byte do IHDR (offset 25 no arquivo).
    if len(png) < 26 or png[12:16] != b"IHDR":
        return False
    color_type = png[25]
    return color_type in (4, 6)  # grayscale+alpha, RGBA


# ---------------------------------------------------------------------- nos


def _add_nodes(builder: _GltfBuilder, scene: Scene, num_joints: int) -> None:
    for index, joint in enumerate(scene.skeleton):
        node: dict = {"name": joint.name or f"bone_{index}"}
        if joint.children:
            node["children"] = list(joint.children)
        if joint.translation != (0.0, 0.0, 0.0):
            node["translation"] = list(joint.translation)
        builder.nodes.append(node)

    if num_joints:
        root_node: dict = {"name": "root"}
        roots = scene.root_joints()
        if roots:
            root_node["children"] = roots
        builder.nodes.append(root_node)

    for mesh_index, mesh in enumerate(scene.meshes):
        builder.nodes.append(
            {"name": f"mesh_{mesh.name}", "mesh": mesh_index}
        )


def _attach_skin_to_mesh_nodes(
    builder: _GltfBuilder, scene: Scene, num_joints: int, skin_index: int | None
) -> None:
    if skin_index is None:
        return
    start = num_joints + 1 if num_joints else 0
    for offset in range(len(scene.meshes)):
        builder.nodes[start + offset]["skin"] = skin_index


# ------------------------------------------------------------------- malhas


def _add_meshes(
    builder: _GltfBuilder, scene: Scene, num_joints: int, material_index: int | None
) -> None:
    for mesh in scene.meshes:
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
                target=34962,
            ),
            "NORMAL": builder.add_accessor(
                normals.getvalue(), _FLOAT, "VEC3", count, target=34962
            ),
            "TEXCOORD_0": builder.add_accessor(
                uvs.getvalue(), _FLOAT, "VEC2", count, target=34962
            ),
        }
        if num_joints:
            attributes["JOINTS_0"] = builder.add_accessor(
                joints.getvalue(), _UNSIGNED_BYTE, "VEC4", count, target=34962
            )
            attributes["WEIGHTS_0"] = builder.add_accessor(
                weights.getvalue(), _FLOAT, "VEC4", count, target=34962
            )

        # Usa u16 quando cabe (metade do tamanho); u32 nas malhas grandes.
        if count > 0xFFFF:
            index_data = struct.pack(f"<{len(mesh.indices)}I", *mesh.indices)
            index_type = _UNSIGNED_INT
        else:
            index_data = struct.pack(f"<{len(mesh.indices)}H", *mesh.indices)
            index_type = _UNSIGNED_SHORT
        indices_accessor = builder.add_accessor(
            index_data, index_type, "SCALAR", len(mesh.indices), target=34963
        )

        primitive: dict = {
            "attributes": attributes,
            "indices": indices_accessor,
            "mode": 4,  # TRIANGLES
        }
        if material_index is not None:
            primitive["material"] = material_index

        builder.meshes.append(
            {"name": f"mesh_{mesh.name}", "primitives": [primitive]}
        )


# --------------------------------------------------------------------- skin


def _add_skin(builder: _GltfBuilder, scene: Scene, num_joints: int) -> int | None:
    if not num_joints:
        return None

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
    accessor = builder.add_accessor(
        writer.getvalue(), _FLOAT, "MAT4", num_joints
    )

    builder.skins.append(
        {
            "name": "gc3d_skin",
            "inverseBindMatrices": accessor,
            "joints": list(range(num_joints)),
            "skeleton": num_joints,  # o no "root"
        }
    )
    return 0


# ---------------------------------------------------------------- animacoes


def _add_animations(builder: _GltfBuilder, scene: Scene, num_joints: int) -> None:
    if not num_joints:
        return
    root_node = num_joints

    for animation in scene.animations:
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

        # Canal de deslocamento do personagem, no no "root".
        translations = BinaryWriter()
        for frame in animation.frames:
            translations.f32s(frame.translation)
        translation_accessor = builder.add_accessor(
            translations.getvalue(), _FLOAT, "VEC3", len(animation.frames)
        )
        channels.append(
            {
                "sampler": len(samplers),
                "target": {"node": root_node, "path": "translation"},
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
                    "target": {"node": joint_index, "path": "rotation"},
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
            {
                "name": animation.name,
                "samplers": samplers,
                "channels": channels,
            }
        )
