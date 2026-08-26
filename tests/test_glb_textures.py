"""Testes do exportador GLB, da conversao de coordenadas e das texturas."""

from __future__ import annotations

import json
import struct
import unittest

from glb_inspect import Glb, validate  # de tools/, adicionado ao path em tests/__init__

from gc3d.formats.glb import GlbOptions, export_glb
from gc3d.scene import Animation, Joint, Keyframe, Mesh, Scene, Vertex
from gc3d.textures import DdsError, encode_png, read_dds


def build_scene() -> Scene:
    """Cena minima com dois joints, um triangulo e uma animacao."""
    scene = Scene()
    scene.skeleton = [
        Joint(name="bone_0", translation=(0.0, 0.0, 0.0), parent=None, children=[1]),
        Joint(name="bone_1", translation=(0.0, 2.0, 0.0), parent=0, children=[]),
    ]
    scene.meshes = [
        Mesh(
            name="teste",
            vertices=[
                Vertex((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0), 0, 1.0),
                Vertex((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0), 0, 1.0),
                Vertex((0.0, 1.0, 3.0), (0.0, 0.0, 1.0), (0.0, 1.0), 1, 1.0),
            ],
            indices=[0, 1, 2],
        )
    ]
    identity = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    scene.animations = [
        Animation(
            name="andar",
            frames=[
                Keyframe(translation=(0.0, 0.0, 0.0), transforms=[identity, identity]),
                Keyframe(translation=(1.0, 0.0, 5.0), transforms=[identity, identity]),
            ],
        )
    ]
    return scene


def tiny_png() -> bytes:
    """PNG RGBA 2x2 gerado pelo proprio codificador do projeto."""
    return encode_png(2, 2, bytes([255, 0, 0, 255] * 4))


class TestCoordinateConversion(unittest.TestCase):
    def test_export_requires_right_handed(self) -> None:
        with self.assertRaises(ValueError):
            export_glb(build_scene())

    def test_to_right_handed_negates_z_and_flips_winding(self) -> None:
        scene = build_scene().to_right_handed()
        self.assertEqual(scene.meshes[0].vertices[2].position, (0.0, 1.0, -3.0))
        self.assertEqual(scene.meshes[0].vertices[2].normal, (0.0, 0.0, -1.0))
        # O triangulo 0,1,2 deve virar 0,2,1.
        self.assertEqual(scene.meshes[0].indices, [0, 2, 1])
        self.assertEqual(scene.animations[0].frames[1].translation, (1.0, 0.0, -5.0))

    def test_to_right_handed_is_idempotent(self) -> None:
        scene = build_scene().to_right_handed()
        indices_once = list(scene.meshes[0].indices)
        scene.to_right_handed()
        self.assertEqual(scene.meshes[0].indices, indices_once)


class TestGlbStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.data = export_glb(build_scene().to_right_handed())

    def test_glb_container_header(self) -> None:
        magic, version, length = struct.unpack_from("<III", self.data, 0)
        self.assertEqual(magic, 0x46546C67)  # "glTF"
        self.assertEqual(version, 2)
        self.assertEqual(length, len(self.data))
        self.assertEqual(len(self.data) % 4, 0, "o GLB deve ser multiplo de 4 bytes")

    def test_passes_gltf_invariants(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.glb")
            with open(path, "wb") as handle:
                handle.write(self.data)
            problems = validate(Glb(path))
        self.assertEqual(problems, [])

    def test_node_layout(self) -> None:
        root = json.loads(self._json_chunk())
        nodes = root["nodes"]
        # 2 joints + no "root" + 1 no de malha
        self.assertEqual(len(nodes), 4)
        self.assertEqual(nodes[0]["name"], "bone_0")
        self.assertEqual(nodes[1]["name"], "bone_1")
        self.assertEqual(nodes[2]["name"], "root")
        self.assertEqual(nodes[2]["children"], [0], "root aponta para os joints sem pai")
        self.assertEqual(nodes[3]["mesh"], 0)
        self.assertEqual(nodes[3]["skin"], 0)
        self.assertEqual(root["skins"][0]["skeleton"], 2)
        self.assertEqual(root["skins"][0]["joints"], [0, 1])

    def test_scene_roots_exclude_child_joints(self) -> None:
        root = json.loads(self._json_chunk())
        self.assertEqual(root["scenes"][0]["nodes"], [2, 3])

    def test_inverse_bind_matrices_undo_world_translation(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.glb")
            with open(path, "wb") as handle:
                handle.write(self.data)
            glb = Glb(path)
            matrices = glb.accessor(glb.json["skins"][0]["inverseBindMatrices"])
        # joint 1 tem translacao mundial (0,2,0); a inverse bind e (0,-2,0).
        self.assertAlmostEqual(matrices[1][12], 0.0)
        self.assertAlmostEqual(matrices[1][13], -2.0)
        self.assertAlmostEqual(matrices[1][14], 0.0)

    def test_animation_channels(self) -> None:
        root = json.loads(self._json_chunk())
        animation = root["animations"][0]
        self.assertEqual(animation["name"], "andar")
        targets = [(c["target"]["node"], c["target"]["path"]) for c in animation["channels"]]
        self.assertIn((2, "translation"), targets, "o no root recebe o deslocamento")
        self.assertIn((0, "rotation"), targets)
        self.assertIn((1, "rotation"), targets)

    def test_attributes_present(self) -> None:
        root = json.loads(self._json_chunk())
        attributes = root["meshes"][0]["primitives"][0]["attributes"]
        for name in ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"):
            self.assertIn(name, attributes)

    def test_static_scene_has_no_skin(self) -> None:
        scene = build_scene()
        scene.skeleton = []
        scene.animations = []
        for vertex in scene.meshes[0].vertices:
            vertex.joint = -1
        data = export_glb(scene.to_right_handed())
        root = json.loads(_json_chunk_of(data))
        self.assertNotIn("skins", root)
        attributes = root["meshes"][0]["primitives"][0]["attributes"]
        self.assertNotIn("JOINTS_0", attributes)

    def test_texture_is_embedded(self) -> None:
        data = export_glb(
            build_scene().to_right_handed(), GlbOptions(texture_png=tiny_png())
        )
        root = json.loads(_json_chunk_of(data))
        self.assertEqual(len(root["images"]), 1)
        self.assertEqual(root["images"][0]["mimeType"], "image/png")
        self.assertIn("bufferView", root["images"][0])
        material = root["materials"][0]
        self.assertEqual(
            material["pbrMetallicRoughness"]["baseColorTexture"]["index"], 0
        )
        # PNG RGBA opaco -> nao precisa de alpha mode especial alem do padrao.
        self.assertIn(material.get("alphaMode", "OPAQUE"), ("OPAQUE", "MASK"))

    def _json_chunk(self) -> bytes:
        return _json_chunk_of(self.data)


def _json_chunk_of(data: bytes) -> bytes:
    length, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    return data[20 : 20 + length]


class TestPng(unittest.TestCase):
    def test_signature_and_chunks(self) -> None:
        png = encode_png(2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png[12:16], b"IHDR")
        # Chunk IEND: 4 bytes de tamanho (zero), o tag, e 4 bytes de CRC.
        self.assertEqual(png[-12:-8], b"\x00\x00\x00\x00")
        self.assertEqual(png[-8:-4], b"IEND")
        width, height = struct.unpack_from(">II", png, 16)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(png[24], 8, "profundidade de 8 bits")
        self.assertEqual(png[25], 6, "colorType 6 = RGBA")

    def test_rejects_wrong_buffer_size(self) -> None:
        with self.assertRaises(ValueError):
            encode_png(4, 4, b"\0" * 10)


def build_dxt1_dds(width: int, height: int, color0: int, color1: int) -> bytes:
    """DDS DXT1 minimo de um bloco, com todos os pixels usando a cor 0."""
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 76, 32)  # tamanho do pixel format
    struct.pack_into("<I", header, 80, 0x4)  # DDPF_FOURCC
    header[84:88] = b"DXT1"
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    body = b""
    for _ in range(blocks_x * blocks_y):
        body += struct.pack("<HHI", color0, color1, 0)  # indices todos 0
    return bytes(header) + body


class TestDds(unittest.TestCase):
    def test_dxt1_solid_red(self) -> None:
        # RGB565 vermelho puro = 0xF800
        image = read_dds(build_dxt1_dds(4, 4, 0xF800, 0x0000))
        self.assertEqual((image.width, image.height), (4, 4))
        self.assertEqual(image.source_format, "DXT1")
        self.assertEqual(len(image.pixels), 4 * 4 * 4)
        self.assertEqual(tuple(image.pixels[0:4]), (255, 0, 0, 255))

    def test_non_multiple_of_four_dimensions(self) -> None:
        image = read_dds(build_dxt1_dds(3, 3, 0xF800, 0x0000))
        self.assertEqual((image.width, image.height), (3, 3))
        self.assertEqual(len(image.pixels), 3 * 3 * 4)

    def test_rejects_non_dds(self) -> None:
        with self.assertRaises(DdsError):
            read_dds(b"not a dds file, padding padding padding" * 8)

    def test_rejects_truncated_body(self) -> None:
        data = build_dxt1_dds(8, 8, 0xF800, 0x0000)
        with self.assertRaises(DdsError):
            read_dds(data[:-8])


if __name__ == "__main__":
    unittest.main()
