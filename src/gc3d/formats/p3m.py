"""Leitor do formato P3M (Perfact 3D Model) do Grand Chase.

O P3M guarda a geometria de um modelo: malha, hierarquia de ossos e skinning.
Usa sistema de coordenadas left-handed Y-up.

Estado da implementacao
-----------------------
A versao **0.5** esta implementada e validada byte a byte contra os 127 arquivos
oficiais do conjunto de teste (ver `docs/VALIDACAO.md`). E a versao usada por
praticamente todo o conteudo do Grand Chase Classic.

As demais versoes (0.6, 0.7, 0.8, 1.0) estao documentadas em
`docs/ESPECIFICACAO_FORMATOS.md` mas ainda nao implementadas; ao encontra-las o
leitor levanta `UnsupportedVersionError` com uma mensagem explicita, em vez de
produzir geometria silenciosamente corrompida.

Observacoes importantes descobertas na validacao
-----------------------------------------------
* O `SkinVertex` da v0.5 tem **40 bytes**, nao 36. O bloco de indices de osso
  ocupa 4 bytes: `boneIndex`, uma copia redundante de `boneIndex`, e dois bytes
  0xFF nao usados.
* O bloco de `MeshVertex` pode estar **truncado ou ausente**. Dois arquivos
  oficiais (`face_alice.p3m`, `face_21_00.p3m`) terminam no meio dele. Como
  esses vertices nao sao usados na conversao (o skinning vem dos SkinVertex),
  tratamos a ausencia como normal.
* Muitos arquivos tem **bytes sobrando** no final (tipicamente 42 por
  AngleBone). Sao ignorados, igual ao conversor antigo.
* `boneIndex` do vertice e **absoluto**: vale `indice_do_angle_bone +
  numero_de_position_bones`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..binary import BinaryReader, BinaryWriter, TruncatedDataError
from ..scene import NO_JOINT, Joint, Mesh, Scene, Vertex

__all__ = [
    "P3M_HEADER_PREFIX",
    "P3M_HEADER_V05",
    "P3M_HEADER_SIZE",
    "TEXTURE_NAME_SIZE",
    "INVALID_BONE_INDEX",
    "MAX_BONE_CHILDREN",
    "MAX_BONES",
    "MAX_VERTICES",
    "PositionBone",
    "AngleBone",
    "SkinVertex",
    "MeshVertex",
    "P3mFile",
    "UnsupportedVersionError",
    "InvalidP3mError",
    "P3mLimitError",
    "detect_version",
    "read_p3m",
    "load_p3m",
    "p3m_to_scene",
    "build_joints",
    "scene_to_p3m",
    "write_p3m",
    "save_p3m",
]

#: Prefixo do cabecalho. O erro de grafia ("Perfact") esta no formato original.
P3M_HEADER_PREFIX = b"Perfact 3D Model (Ver "
#: Cabecalho completo da v0.5, incluindo o NUL terminador.
P3M_HEADER_V05 = b"Perfact 3D Model (Ver 0.5)\0"
P3M_HEADER_SIZE = len(P3M_HEADER_V05)  # 27
TEXTURE_NAME_SIZE = 260

#: Valor sentinela usado nos arrays de filhos e nos indices de osso nao usados.
INVALID_BONE_INDEX = 0xFF
#: Cada osso tem espaco fixo para 10 filhos.
MAX_BONE_CHILDREN = 10
#: O contador de ossos e um u8, e 0xFF e reservado como sentinela.
MAX_BONES = 255
#: Os contadores de vertice e de face sao u16.
MAX_VERTICES = 0xFFFF
MAX_FACES = 0xFFFF

POSITION_BONE_SIZE = 24
ANGLE_BONE_SIZE = 28
SKIN_VERTEX_SIZE = 40
MESH_VERTEX_SIZE = 32

#: Versoes que este leitor sabe interpretar.
SUPPORTED_VERSIONS = ("0.5",)


class InvalidP3mError(ValueError):
    """O arquivo nao e um P3M reconhecivel."""


class UnsupportedVersionError(InvalidP3mError):
    """O arquivo e um P3M, mas de uma versao ainda nao implementada."""

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(
            f"P3M versao {version!r} ainda nao implementado. "
            f"Versoes suportadas: {', '.join(SUPPORTED_VERSIONS)}. "
            f"O layout desta versao esta descrito em docs/ESPECIFICACAO_FORMATOS.md."
        )


class P3mLimitError(ValueError):
    """A cena nao cabe nos limites do formato P3M v0.5."""


# ---------------------------------------------------------------- estruturas


@dataclass
class PositionBone:
    """Deslocamento aplicado a um conjunto de AngleBones filhos.

    Nao e um osso de verdade: funciona como um "offset" nomeado que informa onde
    seus AngleBones filhos ficam em relacao ao osso pai.
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: Indices de AngleBones filhos (valores 0xFF ja removidos).
    children: list[int] = field(default_factory=list)


@dataclass
class AngleBone:
    """Osso real do esqueleto: e o que os vertices e os keyframes referenciam.

    No arquivo os campos `position` e `scale` existem mas sao sempre zero nos
    modelos oficiais; a posicao efetiva vem do PositionBone pai.
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: float = 0.0
    #: Indices de PositionBones filhos (valores 0xFF ja removidos).
    children: list[int] = field(default_factory=list)


@dataclass
class SkinVertex:
    """Vertice com influencia de osso. 40 bytes no arquivo."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    weight: float = 1.0
    #: Indice absoluto do osso: `angle_bone_index + num_position_bones`.
    #: Resolvido por `_resolve_bone_indices` a partir de `bone_index_bytes`.
    bone_index: int = INVALID_BONE_INDEX
    #: Os 4 bytes crus do campo de indice de osso. Duas convencoes existem e
    #: sao distinguidas por analise do arquivo inteiro; ver
    #: `_resolve_bone_indices`.
    bone_index_bytes: bytes = b"\xff\xff\xff\xff"
    normal: tuple[float, float, float] = (0.0, 0.0, 0.0)
    uv: tuple[float, float] = (0.0, 0.0)


@dataclass
class MeshVertex:
    """Vertice sem skinning. Presente no arquivo mas nao usado pelo jogo."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 0.0, 0.0)
    uv: tuple[float, float] = (0.0, 0.0)


@dataclass
class P3mFile:
    """Conteudo cru de um arquivo P3M, sem nenhuma interpretacao."""

    version: str = "0.5"
    version_header: str = ""
    position_bones: list[PositionBone] = field(default_factory=list)
    angle_bones: list[AngleBone] = field(default_factory=list)
    texture_name: str = ""
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    skin_vertices: list[SkinVertex] = field(default_factory=list)
    mesh_vertices: list[MeshVertex] = field(default_factory=list)
    #: Bytes nao consumidos no fim do arquivo. Informativo.
    trailing_bytes: int = 0
    #: True se o bloco de MeshVertex estava incompleto ou ausente.
    mesh_vertices_truncated: bool = False
    #: Como o indice de osso do vertice estava codificado: "u8" ou "u32".
    #: Detectado a partir dos dados; ver `_resolve_bone_indices`.
    bone_index_encoding: str = "u8"

    @property
    def num_position_bones(self) -> int:
        return len(self.position_bones)

    @property
    def num_angle_bones(self) -> int:
        return len(self.angle_bones)


# ------------------------------------------------------------------- leitura


def detect_version(data: bytes) -> str:
    """Devolve a versao declarada no cabecalho, ex. "0.5".

    Levanta `InvalidP3mError` se o prefixo do cabecalho nao casar.
    """
    if len(data) < P3M_HEADER_SIZE:
        raise InvalidP3mError(
            f"arquivo muito pequeno para ser um P3M: {len(data)} bytes "
            f"(cabecalho tem {P3M_HEADER_SIZE})"
        )
    if not data.startswith(P3M_HEADER_PREFIX):
        raise InvalidP3mError(
            "cabecalho P3M nao encontrado; os primeiros bytes sao "
            f"{data[:16]!r}"
        )
    header = data[:P3M_HEADER_SIZE].split(b"\0", 1)[0].decode("latin-1")
    # Extrai o que esta entre "Ver " e ")".
    start = header.rfind("Ver ")
    end = header.rfind(")")
    if start < 0 or end < 0 or end <= start:
        raise InvalidP3mError(f"cabecalho P3M mal formado: {header!r}")
    return header[start + 4 : end].strip()


def read_p3m(data: bytes) -> P3mFile:
    """Interpreta os bytes de um arquivo P3M."""
    version = detect_version(data)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedVersionError(version)
    return _read_v05(data)


def _read_v05(data: bytes) -> P3mFile:
    reader = BinaryReader(data)
    p3m = P3mFile(version="0.5")
    p3m.version_header = reader.cstring(P3M_HEADER_SIZE)

    num_position_bones = reader.u8()
    num_angle_bones = reader.u8()

    for _ in range(num_position_bones):
        position = reader.vec3()
        children_raw = reader.bytes(MAX_BONE_CHILDREN)
        reader.skip(2)  # padding de alinhamento, sempre 0xFFFF
        p3m.position_bones.append(
            PositionBone(
                position=position,
                children=[c for c in children_raw if c != INVALID_BONE_INDEX],
            )
        )

    for _ in range(num_angle_bones):
        position = reader.vec3()
        scale = reader.f32()
        children_raw = reader.bytes(MAX_BONE_CHILDREN)
        reader.skip(2)  # padding de alinhamento
        p3m.angle_bones.append(
            AngleBone(
                position=position,
                scale=scale,
                children=[c for c in children_raw if c != INVALID_BONE_INDEX],
            )
        )

    num_vertices = reader.u16()
    num_faces = reader.u16()
    p3m.texture_name = reader.cstring(TEXTURE_NAME_SIZE)

    for _ in range(num_faces):
        a, b, c = reader.u16s(3)
        p3m.faces.append((a, b, c))

    for _ in range(num_vertices):
        position = reader.vec3()
        weight = reader.f32()
        bone_index_bytes = reader.bytes(4)
        normal = reader.vec3()
        uv = reader.vec2()
        p3m.skin_vertices.append(
            SkinVertex(
                position=position,
                weight=weight,
                bone_index_bytes=bone_index_bytes,
                normal=normal,
                uv=uv,
            )
        )
    _resolve_bone_indices(p3m)

    # O bloco de MeshVertex e opcional na pratica: arquivos oficiais existem com
    # ele truncado. Lemos o que houver e registramos o fato.
    for _ in range(num_vertices):
        if reader.remaining < MESH_VERTEX_SIZE:
            p3m.mesh_vertices_truncated = True
            break
        position = reader.vec3()
        normal = reader.vec3()
        uv = reader.vec2()
        p3m.mesh_vertices.append(MeshVertex(position=position, normal=normal, uv=uv))

    p3m.trailing_bytes = reader.remaining
    _validate(p3m, num_vertices)
    return p3m


def _resolve_bone_indices(p3m: P3mFile) -> None:
    """Descobre como o arquivo codifica o indice de osso e preenche `bone_index`.

    O campo ocupa 4 bytes, mas existem duas convencoes em circulacao:

    ``u8`` (padrao dos arquivos oficiais)
        `(indice, indice, 0xFF, 0xFF)` — o indice no primeiro byte, repetido no
        segundo, e dois bytes nao usados.

    ``u32`` (variante v0.5.2, necessaria quando o modelo passa de 255 ossos)
        os 4 bytes formam um inteiro little-endian.

    Nao ha nada no cabecalho que diga qual das duas esta em uso, entao decidimos
    pelos dados: em ambas as convencoes o indice e absoluto e portanto deve cair
    em `[num_position_bones, num_position_bones + num_angle_bones)`. Testamos as
    duas hipoteses contra **todos** os vertices e adotamos a que fecha. Com
    milhares de vertices, a chance de a hipotese errada fechar e desprezivel.

    A convencao u8 tem prioridade quando as duas fecham, porque e a dos arquivos
    originais do jogo.
    """
    vertices = p3m.skin_vertices
    if not vertices:
        p3m.bone_index_encoding = "u8"
        return

    low = p3m.num_position_bones
    high = low + p3m.num_angle_bones

    u8_values = [v.bone_index_bytes[0] for v in vertices]
    if all(low <= value < high for value in u8_values):
        for vertex, value in zip(vertices, u8_values):
            vertex.bone_index = value
        p3m.bone_index_encoding = "u8"
        return

    u32_values = [
        int.from_bytes(v.bone_index_bytes, "little") for v in vertices
    ]
    if all(low <= value < high for value in u32_values):
        for vertex, value in zip(vertices, u32_values):
            vertex.bone_index = value
        p3m.bone_index_encoding = "u32"
        return

    # Nenhuma hipotese fecha. Mantem a leitura u8 e deixa `_validate` reportar
    # com detalhes, que e mais util que um erro generico aqui.
    for vertex, value in zip(vertices, u8_values):
        vertex.bone_index = value
    p3m.bone_index_encoding = "u8"


def _validate(p3m: P3mFile, num_vertices: int) -> None:
    """Checagens de sanidade que apontam parsing desalinhado.

    Um layout errado quase sempre gera indice de face fora do intervalo, entao
    esta verificacao e uma rede de seguranca barata e eficaz.
    """
    if len(p3m.skin_vertices) != num_vertices:
        raise InvalidP3mError(
            f"esperava {num_vertices} skin vertices, leu {len(p3m.skin_vertices)}"
        )
    count = len(p3m.skin_vertices)
    for i, face in enumerate(p3m.faces):
        if max(face) >= count:
            raise InvalidP3mError(
                f"face {i} referencia vertice {max(face)} mas a malha tem "
                f"apenas {count} vertices (layout provavelmente desalinhado)"
            )
    total_bones = p3m.num_position_bones + p3m.num_angle_bones
    for i, vertex in enumerate(p3m.skin_vertices):
        if vertex.bone_index == INVALID_BONE_INDEX:
            continue
        if not (p3m.num_position_bones <= vertex.bone_index < total_bones):
            raise InvalidP3mError(
                f"vertice {i} aponta para o osso {vertex.bone_index}, fora do "
                f"intervalo esperado [{p3m.num_position_bones}, {total_bones})"
            )


def load_p3m(path) -> P3mFile:
    """Le um arquivo P3M do disco."""
    with open(path, "rb") as handle:
        return read_p3m(handle.read())


# ---------------------------------------------------------------- conversao


def build_joints(
    position_bones: list[PositionBone], angle_bones: list[AngleBone]
) -> list[Joint]:
    """Achata a hierarquia dual do Grand Chase em uma lista simples de joints.

    O Grand Chase alterna dois tipos de no:

        AngleBone --filho--> PositionBone --filho--> AngleBone --> ...

    O AngleBone carrega a rotacao (e e o que os vertices e os keyframes
    referenciam); o PositionBone carrega apenas o deslocamento dos seus filhos.
    Um esqueleto convencional (glTF, Blender, FBX) tem um unico tipo de no com
    translacao e rotacao juntas.

    A conversao entao e: **um joint por AngleBone**, herdando a translacao do
    PositionBone que o lista como filho, e ligando joint a joint atraves do
    PositionBone intermediario.
    """
    joints = [Joint(name=f"bone_{i}") for i in range(len(angle_bones))]

    # 1. A translacao de cada joint vem do PositionBone que o contem.
    for pbone in position_bones:
        for child in pbone.children:
            if child < len(joints):
                joints[child].translation = pbone.position

    # 2. Os filhos de um joint sao os filhos dos PositionBones filhos dele.
    for index, abone in enumerate(angle_bones):
        for pbone_index in abone.children:
            if pbone_index >= len(position_bones):
                continue
            for grandchild in position_bones[pbone_index].children:
                if grandchild < len(joints):
                    joints[index].children.append(grandchild)

    # 3. O pai e a relacao inversa dos filhos.
    for index, joint in enumerate(joints):
        for child in joint.children:
            joints[child].parent = index

    return joints


def p3m_to_scene(p3m: P3mFile, name: str = "model") -> Scene:
    """Converte um `P3mFile` cru em uma `Scene` (ainda left-handed).

    Dois casos precisam de tratamento especial, ambos observados em arquivos
    reais:

    * **Modelo totalmente sem skinning**: todos os vertices trazem
      `bone_index == 0xFF`. Acontece com props e armas convertidas de outros
      formatos. A cena e devolvida sem esqueleto, para virar uma malha estatica
      no glTF em vez de uma malha com skin de peso zero (que nao tem
      comportamento definido na especificacao).
    * **Modelo parcialmente sem skinning**: apenas alguns vertices sem osso.
      Esses vertices sao amarrados ao primeiro joint raiz com peso 1, para que
      acompanhem o modelo em vez de ficarem para tras durante a animacao.
    """
    scene = Scene()
    scene.skeleton = build_joints(p3m.position_bones, p3m.angle_bones)

    # Pre-calcula as translacoes mundiais: sao usadas por todos os vertices.
    world = scene.world_translations()
    num_position_bones = p3m.num_position_bones

    vertices: list[Vertex] = []
    skinned = 0
    for skin_vertex in p3m.skin_vertices:
        joint = skin_vertex.bone_index - num_position_bones
        if 0 <= joint < len(world):
            offset = world[joint]
            # A posicao gravada no P3M e relativa ao osso; somamos a posicao
            # mundial do osso para obter a posicao no espaco da cena. A inverse
            # bind matrix do GLB desfaz exatamente esse deslocamento.
            position = (
                skin_vertex.position[0] + offset[0],
                skin_vertex.position[1] + offset[1],
                skin_vertex.position[2] + offset[2],
            )
            weight = skin_vertex.weight
            skinned += 1
        else:
            joint = NO_JOINT
            position = skin_vertex.position
            weight = 0.0

        vertices.append(
            Vertex(
                position=position,
                normal=skin_vertex.normal,
                uv=skin_vertex.uv,
                joint=joint,
                weight=weight,
            )
        )

    if vertices and skinned == 0:
        # Nenhum vertice tem osso: malha estatica.
        scene.skeleton = []
    elif skinned < len(vertices):
        roots = scene.root_joints()
        fallback = roots[0] if roots else 0
        for vertex in vertices:
            if vertex.joint == NO_JOINT:
                vertex.joint = fallback
                vertex.weight = 1.0

    indices: list[int] = []
    for face in p3m.faces:
        indices.extend(face)

    scene.meshes.append(
        Mesh(
            name=name,
            vertices=vertices,
            indices=indices,
            texture_name=p3m.texture_name,
        )
    )
    scene.unskinned_vertices = len(vertices) - skinned
    return scene


# ------------------------------------------------------------------- escrita


def scene_to_p3m(scene: Scene, texture_name: str = "") -> P3mFile:
    """Converte uma `Scene` left-handed em um `P3mFile` v0.5.

    Reconstrucao da hierarquia dual
    -------------------------------
    O P3M precisa de duas listas de ossos, e a `Scene` tem uma. A reconstrucao
    usa **um PositionBone por AngleBone**, em correspondencia 1 para 1:

        PositionBone[i] = posicao do joint i, filhos = [i]
        AngleBone[i]    = filhos = joint[i].children

    Isso difere um pouco dos arquivos originais, onde um mesmo PositionBone as
    vezes serve a dois AngleBones raiz. Mas o que importa para o jogo e a lista
    de AngleBones — e ela que vertices e keyframes referenciam — e essa fica
    identica, na mesma ordem e com os mesmos indices. A leitura de volta
    reproduz exatamente a `Scene` de origem, o que os testes de ida e volta
    verificam.

    Levanta `P3mLimitError` quando a cena nao cabe no formato.
    """
    if scene.right_handed:
        raise ValueError(
            "a cena esta em right-handed; chame Scene.to_left_handed() antes de "
            "gravar P3M"
        )

    joints = scene.skeleton
    if len(joints) > MAX_BONES:
        raise P3mLimitError(
            f"o modelo tem {len(joints)} ossos e o P3M v0.5 aceita no maximo "
            f"{MAX_BONES}. Reduza o esqueleto antes de exportar."
        )

    mesh = scene.meshes[0] if scene.meshes else Mesh()
    if len(mesh.vertices) > MAX_VERTICES:
        raise P3mLimitError(
            f"a malha tem {len(mesh.vertices)} vertices e o P3M v0.5 aceita no "
            f"maximo {MAX_VERTICES} (o contador e um u16). Reduza a malha "
            f"(decimate) ou divida em partes."
        )
    face_count = len(mesh.indices) // 3
    if face_count > MAX_FACES:
        raise P3mLimitError(
            f"a malha tem {face_count} triangulos e o P3M v0.5 aceita no maximo "
            f"{MAX_FACES}."
        )

    p3m = P3mFile(version="0.5")
    p3m.version_header = P3M_HEADER_V05[:-1].decode("latin-1")
    p3m.texture_name = texture_name

    for index, joint in enumerate(joints):
        p3m.position_bones.append(
            PositionBone(position=joint.translation, children=[index])
        )
        p3m.angle_bones.append(
            AngleBone(
                position=(0.0, 0.0, 0.0),
                scale=0.0,
                children=[c for c in joint.children if c < MAX_BONES][
                    :MAX_BONE_CHILDREN
                ],
            )
        )

    num_position_bones = len(p3m.position_bones)
    world = scene.world_translations()

    # O indice de osso gravado no vertice e absoluto (joint + numPositionBones),
    # logo o maior valor possivel e 2 * numJoints - 1. Quando isso passa de 255
    # nao cabe em um byte, e e obrigatorio usar a codificacao u32 — a mesma que
    # os arquivos com muitos ossos usam. Escolher errado aqui gera indices
    # truncados e vertices grudados no osso errado.
    total_bones = num_position_bones + len(p3m.angle_bones)
    use_u32 = total_bones > MAX_BONES
    p3m.bone_index_encoding = "u32" if use_u32 else "u8"

    for vertex in mesh.vertices:
        joint = vertex.joint
        if 0 <= joint < len(world):
            offset = world[joint]
            # Espelha exatamente a leitura, que soma esse offset.
            position = (
                vertex.position[0] - offset[0],
                vertex.position[1] - offset[1],
                vertex.position[2] - offset[2],
            )
            bone_index = joint + num_position_bones
            weight = vertex.weight if vertex.weight > 0.0 else 1.0
            index_bytes = _pack_bone_index(bone_index, use_u32)
        else:
            position = vertex.position
            bone_index = INVALID_BONE_INDEX
            weight = 1.0
            index_bytes = bytes([INVALID_BONE_INDEX] * 4)

        p3m.skin_vertices.append(
            SkinVertex(
                position=position,
                weight=weight,
                bone_index=bone_index,
                bone_index_bytes=index_bytes,
                normal=vertex.normal,
                uv=vertex.uv,
            )
        )
        # O bloco MeshVertex nao e usado pelo jogo, mas os arquivos oficiais o
        # trazem; gravamos para manter o arquivo com a mesma forma.
        p3m.mesh_vertices.append(
            MeshVertex(
                position=vertex.position, normal=vertex.normal, uv=vertex.uv
            )
        )

    for i in range(0, len(mesh.indices) - 2, 3):
        p3m.faces.append(
            (mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2])
        )

    return p3m


def write_p3m(p3m: P3mFile) -> bytes:
    """Serializa um `P3mFile` nos bytes de um arquivo P3M v0.5."""
    writer = BinaryWriter()
    writer.bytes(P3M_HEADER_V05)
    writer.u8(len(p3m.position_bones))
    writer.u8(len(p3m.angle_bones))

    for pbone in p3m.position_bones:
        writer.f32s(pbone.position)
        writer.bytes(_pack_children(pbone.children))
        # Padding de alinhamento: os arquivos originais trazem 0xFFFF.
        writer.bytes(b"\xff\xff")

    for abone in p3m.angle_bones:
        writer.f32s(abone.position)
        writer.f32(abone.scale)
        writer.bytes(_pack_children(abone.children))
        writer.bytes(b"\xff\xff")

    writer.u16(len(p3m.skin_vertices))
    writer.u16(len(p3m.faces))
    writer.cstring(p3m.texture_name, TEXTURE_NAME_SIZE)

    for face in p3m.faces:
        writer.u16s(face)

    for vertex in p3m.skin_vertices:
        writer.f32s(vertex.position)
        writer.f32(vertex.weight)
        writer.bytes(vertex.bone_index_bytes)
        writer.f32s(vertex.normal)
        writer.f32s(vertex.uv)

    for mesh_vertex in p3m.mesh_vertices:
        writer.f32s(mesh_vertex.position)
        writer.f32s(mesh_vertex.normal)
        writer.f32s(mesh_vertex.uv)

    return writer.getvalue()


def _pack_children(children: list[int]) -> bytes:
    """10 bytes de indices de filhos, preenchidos com o sentinela 0xFF."""
    padded = list(children[:MAX_BONE_CHILDREN])
    padded += [INVALID_BONE_INDEX] * (MAX_BONE_CHILDREN - len(padded))
    return bytes(value & 0xFF for value in padded)


def _pack_bone_index(bone_index: int, use_u32: bool) -> bytes:
    """Os 4 bytes do campo de indice de osso, na codificacao escolhida.

    `u8`  — `(indice, indice, 0xFF, 0xFF)`, como nos arquivos oficiais.
    `u32` — inteiro little-endian, obrigatorio acima de 255 ossos totais.
    """
    if use_u32:
        return struct.pack("<I", bone_index)
    return bytes(
        (
            bone_index & 0xFF,
            bone_index & 0xFF,
            INVALID_BONE_INDEX,
            INVALID_BONE_INDEX,
        )
    )


def save_p3m(p3m: P3mFile, path) -> int:
    """Grava um `P3mFile` em disco. Devolve o tamanho em bytes."""
    data = write_p3m(p3m)
    with open(path, "wb") as handle:
        handle.write(data)
    return len(data)
