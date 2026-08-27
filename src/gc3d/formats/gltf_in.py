"""Leitor de glTF 2.0, binario (`.glb`) e texto (`.gltf`).

E o lado de entrada da conversao inversa: permite editar um modelo no Blender e
trazer de volta para os formatos do jogo.

O importador do conversor antigo trazia um aviso no topo do arquivo — "GLTF
importing does not work properly yet" — e o motivo principal era assumir que os
keyframes ja vinham amostrados a 55 FPS. Nenhuma ferramenta de autoria faz isso:
o Blender exporta keyframes nos instantes em que o animador os criou, com
espacamento irregular. Aqui as animacoes sao **reamostradas** para a grade de
1/55 s que o FRM exige, interpolando conforme o modo declarado em cada sampler.

Cobertura
---------
* Container: `.glb` (chunks JSON + BIN) e `.gltf` (JSON com buffer externo,
  buffer em `data:` URI base64, ou sem buffer).
* Acessores: todos os `componentType`, com `normalized`, `byteStride` e
  `sparse`.
* Nos: transformacao por `matrix` ou por `translation`/`rotation`/`scale`.
* Malhas: todas as primitivas de todas as malhas, mescladas em uma so (o P3M
  v0.5 guarda uma unica malha).
* Skinning: `JOINTS_0`/`WEIGHTS_0`; escolhe a influencia de maior peso, porque o
  P3M v0.5 aceita um osso por vertice.
* Animacoes: interpolacao `LINEAR`, `STEP` e `CUBICSPLINE` (esta ultima usando os
  valores dos pontos, sem as tangentes).
"""

from __future__ import annotations

import base64
import json
import os
import struct
from dataclasses import dataclass, field

from ..mathutil import (
    Mat4,
    Quat,
    Vec3,
    mat4_from_trs,
    quat_normalize,
    quat_slerp,
    vec3_lerp,
)
from ..scene import (
    DEFAULT_FPS,
    NO_JOINT,
    Animation,
    Joint,
    Keyframe,
    Mesh,
    Scene,
    Vertex,
)

__all__ = [
    "InvalidGltfError",
    "GltfDocument",
    "read_gltf",
    "load_gltf",
    "gltf_to_scene",
    "extract_base_color_png",
    "extract_base_color_texture",
    "base_color_image_indices",
]

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

#: (formato do struct, tamanho em bytes, valor maximo para desnormalizar)
_COMPONENTS = {
    5120: ("b", 1, 127.0),
    5121: ("B", 1, 255.0),
    5122: ("h", 2, 32767.0),
    5123: ("H", 2, 65535.0),
    5125: ("I", 4, 4294967295.0),
    5126: ("f", 4, None),
}

_TYPE_COUNTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class InvalidGltfError(ValueError):
    """O arquivo nao e um glTF valido ou usa recurso nao suportado."""


# ------------------------------------------------------------------ container


@dataclass
class GltfDocument:
    """JSON e buffers de um glTF, com acesso aos acessores."""

    json: dict = field(default_factory=dict)
    #: Um bytes por buffer declarado, na mesma ordem.
    buffers: list[bytes] = field(default_factory=list)
    #: Caminho de origem, usado para resolver buffers e imagens externas.
    base_dir: str = ""

    # ---------------------------------------------------------- utilitarios

    def _list(self, key: str) -> list:
        value = self.json.get(key)
        return value if isinstance(value, list) else []

    @property
    def nodes(self) -> list:
        return self._list("nodes")

    @property
    def meshes(self) -> list:
        return self._list("meshes")

    @property
    def skins(self) -> list:
        return self._list("skins")

    @property
    def animations(self) -> list:
        return self._list("animations")

    @property
    def accessors(self) -> list:
        return self._list("accessors")

    @property
    def buffer_views(self) -> list:
        return self._list("bufferViews")

    # ------------------------------------------------------------ acessores

    def read_accessor(self, index: int) -> list:
        """Le um acessor e devolve lista de escalares ou de tuplas.

        Aplica `normalized`, respeita `byteStride` e resolve `sparse`.
        """
        if index >= len(self.accessors):
            raise InvalidGltfError(f"accessor {index} nao existe")
        accessor = self.accessors[index]

        component_type = accessor.get("componentType")
        if component_type not in _COMPONENTS:
            raise InvalidGltfError(f"componentType {component_type} desconhecido")
        fmt, size, maximum = _COMPONENTS[component_type]

        type_name = accessor.get("type", "SCALAR")
        if type_name not in _TYPE_COUNTS:
            raise InvalidGltfError(f"type {type_name!r} desconhecido")
        components = _TYPE_COUNTS[type_name]

        count = accessor.get("count", 0)
        normalized = bool(accessor.get("normalized", False))

        values: list
        if "bufferView" in accessor:
            values = self._read_view(
                accessor["bufferView"],
                accessor.get("byteOffset", 0),
                fmt,
                size,
                components,
                count,
            )
        else:
            # Acessor sem bufferView e valido: significa tudo zero.
            zero = 0 if fmt != "f" else 0.0
            values = [
                zero if components == 1 else tuple([zero] * components)
                for _ in range(count)
            ]

        if "sparse" in accessor:
            values = self._apply_sparse(values, accessor["sparse"], fmt, size, components)

        if normalized and maximum is not None:
            if components == 1:
                values = [max(-1.0, v / maximum) for v in values]
            else:
                values = [
                    tuple(max(-1.0, c / maximum) for c in v) for v in values
                ]

        return values

    def _read_view(
        self,
        view_index: int,
        byte_offset: int,
        fmt: str,
        size: int,
        components: int,
        count: int,
    ) -> list:
        if view_index >= len(self.buffer_views):
            raise InvalidGltfError(f"bufferView {view_index} nao existe")
        view = self.buffer_views[view_index]

        buffer_index = view.get("buffer", 0)
        if buffer_index >= len(self.buffers):
            raise InvalidGltfError(
                f"bufferView aponta para o buffer {buffer_index}, que nao foi carregado"
            )
        data = self.buffers[buffer_index]

        base = view.get("byteOffset", 0) + byte_offset
        element_size = components * size
        # byteStride so se aplica a dados intercalados; ausente significa
        # elementos consecutivos.
        stride = view.get("byteStride") or element_size

        needed = base + (count - 1) * stride + element_size if count else base
        if needed > len(data):
            raise InvalidGltfError(
                f"bufferView excede o buffer: precisa de {needed} bytes, o "
                f"buffer tem {len(data)}"
            )

        unpack = struct.Struct(f"<{components}{fmt}").unpack_from
        if components == 1:
            return [unpack(data, base + i * stride)[0] for i in range(count)]
        return [unpack(data, base + i * stride) for i in range(count)]

    def _apply_sparse(
        self, values: list, sparse: dict, fmt: str, size: int, components: int
    ) -> list:
        """Substitui os elementos listados no bloco `sparse`."""
        sparse_count = sparse.get("count", 0)
        if not sparse_count:
            return values

        index_info = sparse["indices"]
        index_fmt, index_size, _ = _COMPONENTS[index_info["componentType"]]
        indices = self._read_view(
            index_info["bufferView"],
            index_info.get("byteOffset", 0),
            index_fmt,
            index_size,
            1,
            sparse_count,
        )

        value_info = sparse["values"]
        replacements = self._read_view(
            value_info["bufferView"],
            value_info.get("byteOffset", 0),
            fmt,
            size,
            components,
            sparse_count,
        )

        result = list(values)
        for position, replacement in zip(indices, replacements):
            if 0 <= position < len(result):
                result[position] = replacement
        return result


# ------------------------------------------------------------------- leitura


def read_gltf(data: bytes, base_dir: str = "") -> GltfDocument:
    """Interpreta os bytes de um `.glb` ou de um `.gltf`."""
    if len(data) >= 12 and struct.unpack_from("<I", data, 0)[0] == _GLB_MAGIC:
        return _read_glb(data, base_dir)
    return _read_gltf_json(data, base_dir)


def _read_glb(data: bytes, base_dir: str) -> GltfDocument:
    magic, version, length = struct.unpack_from("<III", data, 0)
    if version != 2:
        raise InvalidGltfError(f"GLB versao {version}; apenas a 2 e suportada")
    if length > len(data):
        raise InvalidGltfError(
            f"GLB truncado: cabecalho declara {length} bytes, o arquivo tem {len(data)}"
        )

    document = GltfDocument(base_dir=base_dir)
    binary_chunk: bytes | None = None

    offset = 12
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        payload = data[offset + 8 : offset + 8 + chunk_length]
        if chunk_type == _CHUNK_JSON:
            document.json = json.loads(payload.decode("utf-8"))
        elif chunk_type == _CHUNK_BIN:
            binary_chunk = payload
        offset += 8 + chunk_length
        offset += (-offset) % 4

    if not document.json:
        raise InvalidGltfError("chunk JSON ausente no GLB")

    document.buffers = _load_buffers(document.json, binary_chunk, base_dir)
    return document


def _read_gltf_json(data: bytes, base_dir: str) -> GltfDocument:
    try:
        root = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidGltfError(
            f"nao e um glTF: nem GLB binario, nem JSON valido ({error})"
        ) from error
    if not isinstance(root, dict) or "asset" not in root:
        raise InvalidGltfError("JSON nao parece ser um glTF (falta o campo 'asset')")

    document = GltfDocument(json=root, base_dir=base_dir)
    document.buffers = _load_buffers(root, None, base_dir)
    return document


def _load_buffers(
    root: dict, binary_chunk: bytes | None, base_dir: str
) -> list[bytes]:
    buffers: list[bytes] = []
    for index, buffer in enumerate(root.get("buffers") or []):
        uri = buffer.get("uri")
        if uri is None:
            # Sem uri = o chunk BIN do GLB.
            if binary_chunk is None:
                raise InvalidGltfError(
                    f"buffer {index} referencia o chunk BIN, que esta ausente"
                )
            buffers.append(binary_chunk)
        elif uri.startswith("data:"):
            buffers.append(_decode_data_uri(uri))
        else:
            path = os.path.join(base_dir, _unquote_uri(uri))
            if not os.path.isfile(path):
                raise InvalidGltfError(
                    f"buffer externo nao encontrado: {path}. Se o modelo veio "
                    f"como .gltf + .bin, mantenha os dois arquivos juntos "
                    f"(ou exporte como .glb)."
                )
            with open(path, "rb") as handle:
                buffers.append(handle.read())
    return buffers


def _decode_data_uri(uri: str) -> bytes:
    header, _, payload = uri.partition(",")
    if header.endswith(";base64"):
        return base64.b64decode(payload)
    return payload.encode("utf-8")


def _unquote_uri(uri: str) -> str:
    from urllib.parse import unquote

    return unquote(uri)


def load_gltf(path) -> GltfDocument:
    """Le um `.glb` ou `.gltf` do disco."""
    with open(path, "rb") as handle:
        data = handle.read()
    return read_gltf(data, base_dir=os.path.dirname(os.path.abspath(path)))


# ------------------------------------------------------------------ esqueleto


def _node_translation(node: dict) -> Vec3:
    """Translacao de um no, venha ela de `matrix` ou de `translation`."""
    if "matrix" in node:
        matrix = node["matrix"]
        # glTF grava `matrix` em column-major; a translacao e a coluna 3.
        return (float(matrix[12]), float(matrix[13]), float(matrix[14]))
    translation = node.get("translation")
    if translation:
        return (float(translation[0]), float(translation[1]), float(translation[2]))
    return (0.0, 0.0, 0.0)


def _node_has_rotation_or_scale(node: dict) -> bool:
    """True se o no tem rotacao ou escala nao triviais.

    O bind pose do P3M e puramente translacional, entao rotacao ou escala em um
    no acima dos ossos nao pode ser representada e precisa ser avisada.
    """
    if "matrix" in node:
        matrix = node["matrix"]
        # Compara a submatriz 3x3 com a identidade.
        expected = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        actual = (
            matrix[0], matrix[1], matrix[2],
            matrix[4], matrix[5], matrix[6],
            matrix[8], matrix[9], matrix[10],
        )
        return any(abs(a - b) > 1e-6 for a, b in zip(actual, expected))
    rotation = node.get("rotation")
    if rotation and any(
        abs(a - b) > 1e-6 for a, b in zip(rotation, (0.0, 0.0, 0.0, 1.0))
    ):
        return True
    scale = node.get("scale")
    if scale and any(abs(s - 1.0) > 1e-6 for s in scale):
        return True
    return False


def _build_parent_map(nodes: list) -> dict[int, int]:
    parents: dict[int, int] = {}
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            parents[child] = index
    return parents


def _world_translation(
    node_index: int,
    nodes: list,
    parents: dict[int, int],
    stop_at: int | None = None,
) -> Vec3:
    """Translacao acumulada de um no, subindo pelos ancestrais.

    Precisa subir por **todos** os ancestrais, nao apenas pelos que sao ossos: o
    exportador do Blender coloca transformacoes em nos intermediarios (o objeto
    Armature), e ignora-las desloca o modelo inteiro.

    `stop_at` interrompe a acumulacao **antes** de somar aquele no. E usado para
    excluir o no raiz do esqueleto, que carrega a posicao do personagem no
    mundo: essa posicao pertence a animacao (`pos_y` do FRM), nao ao bind pose do
    P3M. Sem essa exclusao, um modelo que passou pelo Blender fica com o
    deslocamento contado duas vezes, porque o Blender assa o primeiro keyframe
    do movimento da raiz na pose de descanso.

    Apenas a translacao e acumulada: rotacao e escala de ancestrais nao tem como
    ser representadas no bind pose do P3M, e sao avisadas em outro ponto.
    """
    total = (0.0, 0.0, 0.0)
    current: int | None = node_index
    guard = 0
    limit = len(nodes) + 1
    while current is not None and current < len(nodes):
        if current == stop_at:
            break
        local = _node_translation(nodes[current])
        total = (total[0] + local[0], total[1] + local[1], total[2] + local[2])
        current = parents.get(current)
        guard += 1
        if guard > limit:  # hierarquia ciclica corrompida
            break
    return total


def _joint_order(document: GltfDocument) -> tuple[list[int], list[int]]:
    """Ordem canonica dos joints.

    Devolve `(skin_joints, final_order)`, ambas listas de indices de no:

    * `skin_joints` — a ordem de `skins[0].joints`. **Obrigatoria** para
      interpretar `JOINTS_0`, cujos valores sao indices nessa lista (nao indices
      de no, como se poderia supor).
    * `final_order` — a ordem em que os joints serao gravados na `Scene`. Quando
      todos os ossos tem nome `bone_N`, ordenamos por N para **preservar a
      numeracao original do Grand Chase**. Isso importa na pratica: permite
      trocar a malha no Blender e continuar usando os arquivos .frm que o jogo
      ja tem, porque os indices de osso continuam apontando para os mesmos
      ossos. O Blender reordena os joints ao exportar, e sem isso a numeracao
      mudaria a cada ida e volta.
    """
    skin_joints: list[int] = []
    if document.skins:
        skin_joints = list(document.skins[0].get("joints") or [])

    if not skin_joints:
        # Sem skin: tenta os nos chamados bone_N.
        numbered = []
        for index, node in enumerate(document.nodes):
            name = node.get("name") or ""
            if name.startswith("bone_") and name[5:].isdigit():
                numbered.append((int(name[5:]), index))
        numbered.sort()
        skin_joints = [index for _, index in numbered]

    if not skin_joints:
        return [], []

    # Reordena por bone_N quando a informacao esta completa e sem ambiguidade.
    numbered = []
    for node_index in skin_joints:
        node = document.nodes[node_index] if node_index < len(document.nodes) else {}
        name = node.get("name") or ""
        if name.startswith("bone_") and name[5:].isdigit():
            numbered.append((int(name[5:]), node_index))
    if len(numbered) == len(skin_joints) and len({n for n, _ in numbered}) == len(
        numbered
    ):
        numbered.sort()
        final_order = [node_index for _, node_index in numbered]
    else:
        final_order = list(skin_joints)

    return skin_joints, final_order


def _build_skeleton(
    document: GltfDocument, final_order: list[int], root_node: int | None = None
) -> tuple[list[Joint], dict[int, int], list[str]]:
    """Monta a lista de joints e o mapa `indice de no -> indice de joint`."""
    warnings: list[str] = []
    node_to_joint = {node: position for position, node in enumerate(final_order)}
    parents = _build_parent_map(document.nodes)
    nodes = document.nodes

    # O no raiz do esqueleto carrega a posicao do personagem no mundo, que
    # pertence a animacao e nao ao bind pose. So o excluimos se ele proprio nao
    # for um osso: em alguns arquivos o osso raiz e tambem a raiz da skin, e ai a
    # translacao dele e legitimamente parte do esqueleto.
    stop_at = root_node if root_node not in node_to_joint else None
    if stop_at is not None:
        offset = _node_translation(nodes[stop_at]) if stop_at < len(nodes) else (0.0, 0.0, 0.0)
        if max(abs(value) for value in offset) > 1e-6:
            warnings.append(
                f"o no raiz do esqueleto tem translacao "
                f"({offset[0]:.4f}, {offset[1]:.4f}, {offset[2]:.4f}), que foi "
                f"tratada como posicao no mundo e nao gravada no bind pose; no "
                f"jogo essa posicao vem da animacao"
            )

    # Translacao mundial de cada osso, acumulando os ancestrais ate o no raiz.
    world = {
        node_index: _world_translation(node_index, nodes, parents, stop_at)
        for node_index in final_order
    }

    rotated_ancestors = set()
    for node_index in final_order:
        current = parents.get(node_index)
        while current is not None:
            if current not in node_to_joint and _node_has_rotation_or_scale(
                nodes[current]
            ):
                rotated_ancestors.add(current)
            current = parents.get(current)
    if rotated_ancestors:
        warnings.append(
            f"{len(rotated_ancestors)} no(s) acima do esqueleto tem rotacao ou "
            f"escala; o bind pose do P3M so guarda translacao, entao essa parte "
            f"da transformacao sera perdida. Aplique as transformacoes "
            f"(Object > Apply > All Transforms) antes de exportar."
        )

    joints: list[Joint] = []
    for position, node_index in enumerate(final_order):
        node = nodes[node_index] if node_index < len(nodes) else {}

        # Procura o ancestral que tambem e osso; nos intermediarios sao ignorados
        # na hierarquia, mas suas translacoes ja entraram em `world`.
        parent_joint = None
        current = parents.get(node_index)
        while current is not None:
            if current in node_to_joint:
                parent_joint = node_to_joint[current]
                break
            current = parents.get(current)

        # A `Scene` guarda translacao relativa ao osso pai; a diferenca das
        # translacoes mundiais da exatamente isso, e absorve os nos
        # intermediarios que nao sao ossos.
        if parent_joint is None:
            translation = world[node_index]
        else:
            parent_world = world[final_order[parent_joint]]
            translation = (
                world[node_index][0] - parent_world[0],
                world[node_index][1] - parent_world[1],
                world[node_index][2] - parent_world[2],
            )

        children = []
        for child in _descendant_joints(node_index, nodes, node_to_joint):
            children.append(node_to_joint[child])

        joints.append(
            Joint(
                name=node.get("name") or f"bone_{position}",
                translation=translation,
                parent=parent_joint,
                children=children,
            )
        )
    return joints, node_to_joint, warnings


def _descendant_joints(
    node_index: int, nodes: list, node_to_joint: dict[int, int]
) -> list[int]:
    """Ossos filhos mais proximos, atravessando nos intermediarios."""
    result: list[int] = []
    stack = list(reversed((nodes[node_index].get("children") or [])))
    while stack:
        child = stack.pop()
        if child in node_to_joint:
            result.append(child)
        elif child < len(nodes):
            stack.extend(reversed(nodes[child].get("children") or []))
    return result


def _skeleton_root_node(document: GltfDocument, joint_nodes: list[int]) -> int | None:
    """No cujo canal de translacao representa o deslocamento do personagem.

    Prioridade: `skins[0].skeleton`, depois um no chamado `root`, depois o pai
    comum dos joints.
    """
    if document.skins and "skeleton" in document.skins[0]:
        return document.skins[0]["skeleton"]

    for index, node in enumerate(document.nodes):
        if (node.get("name") or "").lower().startswith("root"):
            return index

    if joint_nodes:
        parents = _build_parent_map(document.nodes)
        joint_set = set(joint_nodes)
        candidates = {
            parents[joint] for joint in joint_nodes if parents.get(joint) not in joint_set
        }
        candidates.discard(None)
        if len(candidates) == 1:
            return candidates.pop()
    return None


# --------------------------------------------------------------------- malha


def _read_primitive(
    document: GltfDocument, primitive: dict, skin_index_to_joint: dict[int, int]
) -> tuple[list[Vertex], list[int], list[str]]:
    warnings: list[str] = []
    attributes = primitive.get("attributes") or {}

    if "POSITION" not in attributes:
        return [], [], ["primitiva sem POSITION ignorada"]

    positions = document.read_accessor(attributes["POSITION"])
    count = len(positions)

    normals = (
        document.read_accessor(attributes["NORMAL"]) if "NORMAL" in attributes else []
    )
    uvs = (
        document.read_accessor(attributes["TEXCOORD_0"])
        if "TEXCOORD_0" in attributes
        else []
    )
    joints = (
        document.read_accessor(attributes["JOINTS_0"]) if "JOINTS_0" in attributes else []
    )
    weights = (
        document.read_accessor(attributes["WEIGHTS_0"])
        if "WEIGHTS_0" in attributes
        else []
    )

    if not normals:
        warnings.append("primitiva sem normais; serao gravadas normais nulas")
    if not uvs:
        warnings.append("primitiva sem coordenadas de textura (TEXCOORD_0)")

    multi_influence = 0
    unmapped = 0
    vertices: list[Vertex] = []
    for i in range(count):
        position = positions[i]
        normal = normals[i] if i < len(normals) else (0.0, 0.0, 0.0)
        uv = uvs[i] if i < len(uvs) else (0.0, 0.0)

        joint = NO_JOINT
        weight = 0.0
        if i < len(joints) and i < len(weights):
            raw_joints = joints[i]
            raw_weights = weights[i]
            if not isinstance(raw_joints, tuple):
                raw_joints = (raw_joints,)
            if not isinstance(raw_weights, tuple):
                raw_weights = (raw_weights,)

            # O P3M v0.5 aceita um osso por vertice: fica o de maior peso.
            best = max(range(len(raw_weights)), key=lambda k: raw_weights[k])
            if raw_weights[best] > 0.0:
                # Cuidado: o valor em JOINTS_0 e um indice no array
                # `skin.joints`, nao um indice de no. Confundir os dois funciona
                # por acidente quando os dois coincidem (o caso dos arquivos
                # gerados por este conversor) e gruda os vertices no osso errado
                # em arquivos de outras ferramentas, que reordenam os joints.
                skin_index = int(raw_joints[best])
                if skin_index in skin_index_to_joint:
                    joint = skin_index_to_joint[skin_index]
                    weight = float(raw_weights[best])
                else:
                    unmapped += 1
                if sum(1 for w in raw_weights if w > 0.001) > 1:
                    multi_influence += 1

        vertices.append(
            Vertex(
                position=(float(position[0]), float(position[1]), float(position[2])),
                normal=(float(normal[0]), float(normal[1]), float(normal[2])),
                uv=(float(uv[0]), float(uv[1])),
                joint=joint,
                weight=weight if joint != NO_JOINT else 0.0,
            )
        )

    if multi_influence:
        warnings.append(
            f"{multi_influence} vertice(s) tinham mais de um osso influente; "
            f"o P3M v0.5 guarda apenas um, e foi mantido o de maior peso"
        )
    if unmapped:
        warnings.append(
            f"{unmapped} vertice(s) apontavam para um osso fora da skin e ficaram "
            f"sem osso"
        )

    if "indices" in primitive:
        indices = [int(i) for i in document.read_accessor(primitive["indices"])]
    else:
        indices = list(range(count))

    mode = primitive.get("mode", 4)
    if mode != 4:
        warnings.append(
            f"primitiva com mode={mode} (nao TRIANGLES) ignorada; converta a "
            f"malha para triangulos antes de exportar"
        )
        return [], [], warnings

    return vertices, indices, warnings


def _read_meshes(
    document: GltfDocument, skin_index_to_joint: dict[int, int], name: str
) -> tuple[Mesh, list[str]]:
    """Le e mescla todas as primitivas num unico `Mesh`.

    O P3M v0.5 guarda uma malha com um material. Um glTF pode ter varias malhas
    e varias primitivas; mesclar preserva a geometria inteira, o que e o que
    importa. Os indices de cada bloco sao deslocados pelo total acumulado.
    """
    warnings: list[str] = []
    merged = Mesh(name=name)
    primitive_count = 0

    for mesh in document.meshes:
        for primitive in mesh.get("primitives") or []:
            vertices, indices, primitive_warnings = _read_primitive(
                document, primitive, skin_index_to_joint
            )
            warnings.extend(primitive_warnings)
            if not vertices:
                continue
            offset = len(merged.vertices)
            merged.vertices.extend(vertices)
            merged.indices.extend(index + offset for index in indices)
            primitive_count += 1

    if primitive_count > 1:
        warnings.append(
            f"{primitive_count} primitivas foram mescladas em uma unica malha "
            f"(o P3M v0.5 guarda apenas uma)"
        )
    return merged, warnings


# ----------------------------------------------------------------- animacoes


@dataclass
class _Channel:
    """Amostras de um canal de animacao, prontas para interpolar."""

    times: list[float]
    values: list
    interpolation: str = "LINEAR"

    def sample_vec3(self, time: float, default: Vec3) -> Vec3:
        raw = self._sample(time)
        if raw is None:
            return default
        return (float(raw[0]), float(raw[1]), float(raw[2]))

    def sample_quat(self, time: float, default: Quat) -> Quat:
        if not self.times:
            return default
        index, factor = self._locate(time)
        if factor is None:
            value = self._value_at(index)
            return quat_normalize(
                (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
            )
        a = self._value_at(index)
        b = self._value_at(index + 1)
        qa = quat_normalize((float(a[0]), float(a[1]), float(a[2]), float(a[3])))
        qb = quat_normalize((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
        if self.interpolation == "STEP":
            return qa
        return quat_slerp(qa, qb, factor)

    def _sample(self, time: float):
        if not self.times:
            return None
        index, factor = self._locate(time)
        if factor is None:
            return self._value_at(index)
        a = self._value_at(index)
        b = self._value_at(index + 1)
        if self.interpolation == "STEP":
            return a
        return vec3_lerp(
            (float(a[0]), float(a[1]), float(a[2])),
            (float(b[0]), float(b[1]), float(b[2])),
            factor,
        )

    def _value_at(self, index: int):
        # Em CUBICSPLINE cada keyframe ocupa 3 elementos: tangente de entrada,
        # valor, tangente de saida. Sem as tangentes a curva vira linear, o que
        # e aceitavel porque a saida sera reamostrada a 55 Hz.
        if self.interpolation == "CUBICSPLINE":
            return self.values[index * 3 + 1]
        return self.values[index]

    def _locate(self, time: float) -> tuple[int, float | None]:
        """Devolve `(indice, fator)`; fator None significa "valor exato"."""
        times = self.times
        if time <= times[0]:
            return 0, None
        if time >= times[-1]:
            return len(times) - 1, None
        # Busca binaria: animacoes longas tem centenas de keyframes.
        low, high = 0, len(times) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if times[middle] <= time:
                low = middle
            else:
                high = middle
        span = times[high] - times[low]
        if span <= 0.0:
            return low, None
        return low, (time - times[low]) / span


def _read_animation(
    document: GltfDocument,
    animation: dict,
    node_to_joint: dict[int, int],
    root_node: int | None,
    fps: int,
) -> tuple[Animation, list[str]]:
    warnings: list[str] = []
    samplers = animation.get("samplers") or []

    # canais[joint]["rotation"] = _Channel
    joint_channels: dict[int, dict[str, _Channel]] = {}
    root_translation: _Channel | None = None
    duration = 0.0

    for channel in animation.get("channels") or []:
        target = channel.get("target") or {}
        node_index = target.get("node")
        path = target.get("path")
        sampler_index = channel.get("sampler")
        if node_index is None or path is None or sampler_index is None:
            continue
        if sampler_index >= len(samplers):
            continue
        sampler = samplers[sampler_index]

        try:
            times = [float(t) for t in document.read_accessor(sampler["input"])]
            values = document.read_accessor(sampler["output"])
        except (InvalidGltfError, KeyError) as error:
            warnings.append(f"canal ignorado ({error})")
            continue
        if not times:
            continue
        duration = max(duration, times[-1])

        parsed = _Channel(
            times=times,
            values=values,
            interpolation=sampler.get("interpolation", "LINEAR"),
        )

        if node_index == root_node and path == "translation":
            root_translation = parsed
        elif node_index in node_to_joint:
            joint_channels.setdefault(node_to_joint[node_index], {})[path] = parsed
        elif path == "weights":
            warnings.append("canal de morph target ignorado (nao existe no FRM)")

    num_joints = len(node_to_joint)
    if duration <= 0.0:
        return (
            Animation(name=animation.get("name") or "animation", fps=fps),
            warnings + ["animacao sem duracao, ignorada"],
        )

    # Reamostragem para a grade do FRM. Esta e a parte que faltava no conversor
    # antigo: sem ela, uma animacao do Blender com keyframes esparsos gerava um
    # FRM com pouquissimos frames e velocidade errada.
    step = 1.0 / float(fps)
    frame_count = int(round(duration / step)) + 1
    resampled = Animation(name=animation.get("name") or "animation", fps=fps)

    identity: Quat = (0.0, 0.0, 0.0, 1.0)
    zero: Vec3 = (0.0, 0.0, 0.0)
    one: Vec3 = (1.0, 1.0, 1.0)

    for frame_index in range(frame_count):
        time = frame_index * step
        transforms: list[Mat4] = []
        for joint_index in range(num_joints):
            channels = joint_channels.get(joint_index)
            if channels is None:
                transforms.append(mat4_from_trs(zero, identity, one))
                continue
            translation = (
                channels["translation"].sample_vec3(time, zero)
                if "translation" in channels
                else zero
            )
            rotation = (
                channels["rotation"].sample_quat(time, identity)
                if "rotation" in channels
                else identity
            )
            scale = (
                channels["scale"].sample_vec3(time, one)
                if "scale" in channels
                else one
            )
            transforms.append(mat4_from_trs(translation, rotation, scale))

        translation_root = (
            root_translation.sample_vec3(time, zero) if root_translation else zero
        )
        resampled.frames.append(
            Keyframe(translation=translation_root, transforms=transforms)
        )

    original = max(
        (len(c.times) for channels in joint_channels.values() for c in channels.values()),
        default=0,
    )
    if original and abs(original - frame_count) > 1:
        warnings.append(
            f"animacao {resampled.name!r} reamostrada de ~{original} para "
            f"{frame_count} keyframes ({fps} FPS, {duration:.2f}s)"
        )

    return resampled, warnings


# ------------------------------------------------------------------ fachada


def gltf_to_scene(
    document: GltfDocument,
    name: str = "model",
    fps: int = DEFAULT_FPS,
    warnings: list[str] | None = None,
) -> Scene:
    """Converte um glTF em `Scene` right-handed.

    A cena volta marcada como right-handed. Para gravar P3M/FRM, chame
    `Scene.to_left_handed()` antes.
    """
    warn = warnings if warnings is not None else []
    scene = Scene(right_handed=True)

    skin_joints, final_order = _joint_order(document)
    root_node = _skeleton_root_node(document, final_order)
    scene.skeleton, node_to_joint, skeleton_warnings = _build_skeleton(
        document, final_order, root_node
    )
    warn.extend(skeleton_warnings)
    if not scene.skeleton:
        warn.append(
            "o glTF nao tem skin nem ossos: o P3M sera gravado como malha "
            "estatica com um osso"
        )

    # JOINTS_0 indexa `skin.joints`; traduzimos para o indice final do joint.
    skin_index_to_joint = {
        skin_index: node_to_joint[node_index]
        for skin_index, node_index in enumerate(skin_joints)
        if node_index in node_to_joint
    }
    if final_order and final_order != skin_joints:
        warn.append(
            "os ossos foram reordenados para seguir a numeracao bone_N do "
            "Grand Chase (o exportador de origem tinha usado outra ordem)"
        )

    mesh, mesh_warnings = _read_meshes(document, skin_index_to_joint, name)
    warn.extend(mesh_warnings)

    # A posicao no mundo tem que sair do bind pose tanto dos ossos quanto dos
    # vertices, senao o P3M e o FRM gravados a partir do mesmo glTF contariam o
    # deslocamento duas vezes e o modelo flutuaria no jogo.
    root_offset = _root_world_offset(document, root_node, node_to_joint)
    if mesh.vertices and max(abs(value) for value in root_offset) > 1e-6:
        for vertex in mesh.vertices:
            vertex.position = (
                vertex.position[0] - root_offset[0],
                vertex.position[1] - root_offset[1],
                vertex.position[2] - root_offset[2],
            )

    if mesh.vertices:
        scene.meshes.append(mesh)
        scene.unskinned_vertices = sum(
            1 for vertex in mesh.vertices if vertex.joint == NO_JOINT
        )

    for animation in document.animations:
        converted, animation_warnings = _read_animation(
            document, animation, node_to_joint, root_node, fps
        )
        warn.extend(animation_warnings)
        if converted.frames:
            scene.animations.append(converted)

    return scene


def _root_world_offset(
    document: GltfDocument, root_node: int | None, node_to_joint: dict[int, int]
) -> Vec3:
    """Translacao acumulada do no raiz do esqueleto, se ele nao for um osso."""
    if root_node is None or root_node in node_to_joint:
        return (0.0, 0.0, 0.0)
    parents = _build_parent_map(document.nodes)
    return _world_translation(root_node, document.nodes, parents)


def _image_bytes(document: GltfDocument, image_index: int) -> tuple[bytes | None, str]:
    """Devolve `(dados, mimeType)` de uma imagem do glTF.

    A imagem pode estar num bufferView, num `data:` URI ou num arquivo ao lado.
    O mimeType volta em minusculas, ou vazio se nao declarado.
    """
    images = document.json.get("images") or []
    if image_index >= len(images):
        return None, ""
    image = images[image_index]
    mime = (image.get("mimeType") or "").lower()

    if "bufferView" in image:
        view = document.buffer_views[image["bufferView"]]
        data = document.buffers[view.get("buffer", 0)]
        start = view.get("byteOffset", 0)
        return data[start : start + view["byteLength"]], mime

    uri = image.get("uri")
    if not uri:
        return None, mime
    if uri.startswith("data:"):
        return _decode_data_uri(uri), mime

    path = os.path.join(document.base_dir, _unquote_uri(uri))
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            return handle.read(), mime or _mime_from_extension(path)
    return None, mime


def _mime_from_extension(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(extension, "")


def base_color_image_indices(document: GltfDocument) -> list[int]:
    """Indices das imagens usadas como base color, em ordem de material.

    Serve para saber quantas texturas distintas o arquivo tem: o P3M v0.5 guarda
    apenas uma, e o usuario precisa ser avisado quando ha mais.
    """
    materials = document.json.get("materials") or []
    textures = document.json.get("textures") or []
    found: list[int] = []
    for material in materials:
        info = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if not info:
            continue
        texture_index = info.get("index", 0)
        if texture_index >= len(textures):
            continue
        source = textures[texture_index].get("source")
        if source is not None and source not in found:
            found.append(source)
    return found


def first_primitive_material(document: GltfDocument) -> int | None:
    """Material da primeira primitiva com geometria.

    E o material que corresponde a primeira malha do arquivo, e portanto o mais
    representativo quando o P3M so pode ter uma textura. Pegar `materials[0]` as
    cegas pode escolher o material de outra malha.
    """
    for mesh in document.meshes:
        for primitive in mesh.get("primitives") or []:
            if "POSITION" in (primitive.get("attributes") or {}):
                return primitive.get("material")
    return None


def extract_base_color_texture(
    document: GltfDocument,
) -> tuple[bytes | None, str, list[str]]:
    """Extrai a textura base color mais representativa do glTF.

    Devolve `(dados, mimeType, avisos)`. Os dados vem como estao no arquivo (PNG
    ou JPEG); quem chama decide o que fazer. Avisa quando o glTF tem mais de uma
    textura, porque o P3M v0.5 guarda apenas uma.
    """
    warnings: list[str] = []
    materials = document.json.get("materials") or []
    textures = document.json.get("textures") or []
    if not materials or not textures:
        return None, "", warnings

    all_images = base_color_image_indices(document)
    if len(all_images) > 1:
        warnings.append(
            f"o glTF tem {len(all_images)} texturas base color e o P3M v0.5 guarda "
            f"apenas uma; sera usada a da primeira malha"
        )

    material_index = first_primitive_material(document)
    if material_index is None or material_index >= len(materials):
        material_index = 0

    info = (
        (materials[material_index].get("pbrMetallicRoughness") or {})
        .get("baseColorTexture")
    )
    if not info:
        # A primeira malha nao tem textura, mas outra pode ter.
        if all_images:
            return _image_bytes(document, all_images[0]) + (warnings,)
        return None, "", warnings

    texture_index = info.get("index", 0)
    if texture_index >= len(textures):
        return None, "", warnings
    source = textures[texture_index].get("source")
    if source is None:
        return None, "", warnings

    data, mime = _image_bytes(document, source)
    return data, mime, warnings


def extract_base_color_png(document: GltfDocument) -> bytes | None:
    """Versao simples: devolve os bytes so quando a textura ja e PNG."""
    data, mime, _ = extract_base_color_texture(document)
    if data is None:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    if mime == "image/png":
        return data
    return None
