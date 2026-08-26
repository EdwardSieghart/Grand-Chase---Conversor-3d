"""Testes do parser P3M.

Os dados de teste sao montados byte a byte em `build_p3m_bytes`, o que deixa
explicito o layout que o parser deve entender e permite testar casos que nao
aparecem nos arquivos de exemplo (indice u32, vertice sem osso, truncamento).
"""

from __future__ import annotations

import struct
import unittest

from gc3d.formats import p3m
from gc3d.scene import NO_JOINT

HEADER = b"Perfact 3D Model (Ver 0.5)\0"
INVALID = 0xFF


def pack_children(children: list[int]) -> bytes:
    """10 bytes de indices de filhos, preenchidos com 0xFF."""
    padded = list(children) + [INVALID] * (10 - len(children))
    return bytes(padded[:10])


def build_p3m_bytes(
    position_bones: list[tuple[tuple[float, float, float], list[int]]],
    angle_bones: list[tuple[tuple[float, float, float], float, list[int]]],
    faces: list[tuple[int, int, int]],
    skin_vertices: list[tuple[tuple[float, float, float], float, bytes, tuple, tuple]],
    mesh_vertices: list[tuple] | None = None,
    texture_name: str = "",
    header: bytes = HEADER,
    trailing: bytes = b"",
) -> bytes:
    out = bytearray(header)
    out += bytes((len(position_bones), len(angle_bones)))

    for position, children in position_bones:
        out += struct.pack("<3f", *position)
        out += pack_children(children)
        out += b"\xff\xff"

    for position, scale, children in angle_bones:
        out += struct.pack("<3f", *position)
        out += struct.pack("<f", scale)
        out += pack_children(children)
        out += b"\xff\xff"

    out += struct.pack("<HH", len(skin_vertices), len(faces))
    raw_texture = texture_name.encode("latin-1")
    out += raw_texture + b"\0" * (260 - len(raw_texture))

    for face in faces:
        out += struct.pack("<3H", *face)

    for position, weight, bone_bytes, normal, uv in skin_vertices:
        out += struct.pack("<3f", *position)
        out += struct.pack("<f", weight)
        out += bone_bytes
        out += struct.pack("<3f", *normal)
        out += struct.pack("<2f", *uv)

    for position, normal, uv in mesh_vertices or []:
        out += struct.pack("<3f", *position)
        out += struct.pack("<3f", *normal)
        out += struct.pack("<2f", *uv)

    out += trailing
    return bytes(out)


def simple_p3m(**kwargs) -> bytes:
    """Um P3M minimo valido: 2 position bones, 2 angle bones, 1 triangulo."""
    defaults = dict(
        position_bones=[
            ((0.0, 0.0, 0.0), [0]),
            ((1.0, 0.0, 0.0), [1]),
        ],
        angle_bones=[
            ((0.0, 0.0, 0.0), 0.0, [1]),
            ((0.0, 0.0, 0.0), 0.0, []),
        ],
        faces=[(0, 1, 2)],
        skin_vertices=[
            ((1.0, 0.0, 0.0), 1.0, bytes((2, 2, 255, 255)), (1.0, 0.0, 0.0), (0.0, 0.0)),
            ((0.0, 1.0, 0.0), 1.0, bytes((2, 2, 255, 255)), (0.0, 1.0, 0.0), (0.5, 0.5)),
            ((0.0, 0.0, 1.0), 1.0, bytes((3, 3, 255, 255)), (0.0, 0.0, 1.0), (1.0, 1.0)),
        ],
        mesh_vertices=[
            ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0)),
            ((0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.5, 0.5)),
            ((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (1.0, 1.0)),
        ],
    )
    defaults.update(kwargs)
    return build_p3m_bytes(**defaults)  # type: ignore[arg-type]


class TestVersionDetection(unittest.TestCase):
    def test_detects_v05(self) -> None:
        self.assertEqual(p3m.detect_version(simple_p3m()), "0.5")

    def test_rejects_non_p3m(self) -> None:
        with self.assertRaises(p3m.InvalidP3mError):
            p3m.detect_version(b"not a p3m file at all, really not")

    def test_rejects_too_small(self) -> None:
        with self.assertRaises(p3m.InvalidP3mError):
            p3m.detect_version(b"Perfact")

    def test_unsupported_version_is_explicit(self) -> None:
        data = simple_p3m(header=b"Perfact 3D Model (Ver 0.7)\0")
        with self.assertRaises(p3m.UnsupportedVersionError) as ctx:
            p3m.read_p3m(data)
        self.assertEqual(ctx.exception.version, "0.7")


class TestStructureParsing(unittest.TestCase):
    def test_counts_and_fields(self) -> None:
        model = p3m.read_p3m(simple_p3m(texture_name="pele.dds"))
        self.assertEqual(model.version, "0.5")
        self.assertEqual(model.num_position_bones, 2)
        self.assertEqual(model.num_angle_bones, 2)
        self.assertEqual(len(model.skin_vertices), 3)
        self.assertEqual(len(model.mesh_vertices), 3)
        self.assertEqual(len(model.faces), 1)
        self.assertEqual(model.faces[0], (0, 1, 2))
        self.assertEqual(model.texture_name, "pele.dds")
        self.assertEqual(model.trailing_bytes, 0)
        self.assertFalse(model.mesh_vertices_truncated)

    def test_children_sentinels_are_dropped(self) -> None:
        model = p3m.read_p3m(simple_p3m())
        self.assertEqual(model.position_bones[0].children, [0])
        self.assertEqual(model.position_bones[1].children, [1])
        self.assertEqual(model.angle_bones[0].children, [1])
        self.assertEqual(model.angle_bones[1].children, [])

    def test_skin_vertex_is_40_bytes(self) -> None:
        # Confere pelo tamanho total do arquivo: se o parser assumisse 36 bytes,
        # sobrariam 4 bytes por vertice.
        data = simple_p3m()
        model = p3m.read_p3m(data)
        self.assertEqual(p3m.SKIN_VERTEX_SIZE, 40)
        self.assertEqual(model.trailing_bytes, 0)

    def test_trailing_bytes_are_reported_not_fatal(self) -> None:
        # Arquivos oficiais tem bytes extras no fim; devem ser ignorados.
        model = p3m.read_p3m(simple_p3m(trailing=b"\x00" * 42))
        self.assertEqual(model.trailing_bytes, 42)
        self.assertEqual(len(model.skin_vertices), 3)

    def test_missing_mesh_vertices_is_tolerated(self) -> None:
        # Dois arquivos oficiais terminam no meio deste bloco.
        model = p3m.read_p3m(simple_p3m(mesh_vertices=[]))
        self.assertTrue(model.mesh_vertices_truncated)
        self.assertEqual(model.mesh_vertices, [])
        self.assertEqual(len(model.skin_vertices), 3)

    def test_face_index_out_of_range_is_rejected(self) -> None:
        # Sintoma classico de layout desalinhado.
        with self.assertRaises(p3m.InvalidP3mError):
            p3m.read_p3m(simple_p3m(faces=[(0, 1, 99)]))


class TestBoneIndexEncoding(unittest.TestCase):
    def test_u8_encoding_detected(self) -> None:
        model = p3m.read_p3m(simple_p3m())
        self.assertEqual(model.bone_index_encoding, "u8")
        self.assertEqual([v.bone_index for v in model.skin_vertices], [2, 2, 3])

    def test_u32_encoding_detected(self) -> None:
        # Modelo com mais de 255 ossos: o indice nao cabe em um byte.
        position_bones = [((0.0, 0.0, 0.0), [i]) for i in range(200)]
        angle_bones = [((0.0, 0.0, 0.0), 0.0, []) for _ in range(200)]
        # Indice absoluto 300 = angle bone 100.
        skin = [
            (
                (0.0, 0.0, 0.0),
                1.0,
                struct.pack("<I", 300),
                (0.0, 1.0, 0.0),
                (0.0, 0.0),
            )
        ]
        data = build_p3m_bytes(position_bones, angle_bones, [], skin, [])
        model = p3m.read_p3m(data)
        self.assertEqual(model.bone_index_encoding, "u32")
        self.assertEqual(model.skin_vertices[0].bone_index, 300)

    def test_all_invalid_indices_produce_static_mesh(self) -> None:
        # Props convertidos de outros formatos vem com 0xFF em todos os vertices.
        skin = [
            ((0.0, 0.0, 0.0), 1.0, b"\xff\xff\xff\xff", (0.0, 1.0, 0.0), (0.0, 0.0)),
            ((1.0, 0.0, 0.0), 1.0, b"\xff\xff\xff\xff", (0.0, 1.0, 0.0), (0.0, 0.0)),
            ((0.0, 1.0, 0.0), 1.0, b"\xff\xff\xff\xff", (0.0, 1.0, 0.0), (0.0, 0.0)),
        ]
        data = build_p3m_bytes(
            [((0.0, 0.0, 0.0), [0])],
            [((0.0, 0.0, 0.0), 0.0, [])],
            [(0, 1, 2)],
            skin,
            [],
        )
        model = p3m.read_p3m(data)
        scene = p3m.p3m_to_scene(model, "prop")
        self.assertEqual(scene.skeleton, [], "malha sem skinning nao deve ter esqueleto")
        self.assertEqual(scene.unskinned_vertices, 3)
        self.assertTrue(all(v.joint == NO_JOINT for v in scene.meshes[0].vertices))


class TestJointHierarchy(unittest.TestCase):
    def test_flattening_matches_reference_semantics(self) -> None:
        # Mesmo caso usado como referencia no conversor antigo:
        # AngleBone -> PositionBone -> AngleBone.
        position_bones = [
            p3m.PositionBone((1.0, 1.0, 1.0), [0, 1]),
            p3m.PositionBone((2.0, 2.0, 2.0), [2]),
            p3m.PositionBone((3.0, 3.0, 3.0), [3]),
        ]
        angle_bones = [
            p3m.AngleBone((0.0, 0.0, 0.0), 0.0, [1]),
            p3m.AngleBone((0.0, 0.0, 0.0), 0.0, []),
            p3m.AngleBone((0.0, 0.0, 0.0), 0.0, [2]),
            p3m.AngleBone((0.0, 0.0, 0.0), 0.0, []),
        ]
        joints = p3m.build_joints(position_bones, angle_bones)

        self.assertEqual(len(joints), 4, "um joint por angle bone")
        self.assertEqual(joints[0].translation, (1.0, 1.0, 1.0))
        self.assertEqual(joints[1].translation, (1.0, 1.0, 1.0))
        self.assertEqual(joints[2].translation, (2.0, 2.0, 2.0))
        self.assertEqual(joints[3].translation, (3.0, 3.0, 3.0))
        self.assertEqual(joints[0].children, [2])
        self.assertEqual(joints[2].children, [3])
        self.assertIsNone(joints[0].parent)
        self.assertIsNone(joints[1].parent)
        self.assertEqual(joints[2].parent, 0)
        self.assertEqual(joints[3].parent, 2)

    def test_world_translation_accumulates_through_parents(self) -> None:
        model = p3m.read_p3m(simple_p3m())
        scene = p3m.p3m_to_scene(model, "m")
        # joint 0 recebe (0,0,0); joint 1 recebe (1,0,0) e tem joint 0 como pai.
        self.assertEqual(scene.joint_world_translation(0), (0.0, 0.0, 0.0))
        self.assertEqual(scene.joint_world_translation(1), (1.0, 0.0, 0.0))


class TestSceneConversion(unittest.TestCase):
    def test_vertex_position_offset_by_bone_world_translation(self) -> None:
        model = p3m.read_p3m(simple_p3m())
        scene = p3m.p3m_to_scene(model, "m")
        mesh = scene.meshes[0]
        # Vertice 0: bone_index 2 - npos 2 = joint 0, cuja posicao mundial e 0.
        self.assertEqual(mesh.vertices[0].position, (1.0, 0.0, 0.0))
        self.assertEqual(mesh.vertices[0].joint, 0)
        # Vertice 2: bone_index 3 - 2 = joint 1, posicao mundial (1,0,0).
        self.assertEqual(mesh.vertices[2].position, (1.0, 0.0, 1.0))
        self.assertEqual(mesh.vertices[2].joint, 1)

    def test_indices_are_flattened_faces(self) -> None:
        scene = p3m.p3m_to_scene(p3m.read_p3m(simple_p3m()), "m")
        self.assertEqual(scene.meshes[0].indices, [0, 1, 2])

    def test_weight_is_preserved(self) -> None:
        skin = [
            ((0.0, 0.0, 0.0), 0.5, bytes((2, 2, 255, 255)), (0.0, 1.0, 0.0), (0.0, 0.0)),
        ]
        data = build_p3m_bytes(
            [((0.0, 0.0, 0.0), [0]), ((0.0, 0.0, 0.0), [1])],
            [((0.0, 0.0, 0.0), 0.0, []), ((0.0, 0.0, 0.0), 0.0, [])],
            [],
            skin,
            [],
        )
        scene = p3m.p3m_to_scene(p3m.read_p3m(data), "m")
        self.assertEqual(scene.meshes[0].vertices[0].weight, 0.5)


if __name__ == "__main__":
    unittest.main()
