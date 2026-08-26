"""Testes da conversao inversa: glTF -> P3M/FRM.

Cobre o importador de glTF, os escritores de P3M e FRM, e o ciclo completo de ida
e volta. Os casos mais importantes aqui sao os que reproduzem armadilhas reais
encontradas na pratica:

* `JOINTS_0` indexa `skin.joints`, nao a lista de nos. Confundir os dois passa
  despercebido quando as duas ordens coincidem e gruda os vertices no osso errado
  em arquivos de outras ferramentas.
* Nos acima do esqueleto podem ter translacao, e ignora-la desloca o modelo todo.
* O no raiz do esqueleto carrega a posicao no mundo, que pertence a animacao e nao
  ao bind pose; conta-la duas vezes faz o modelo flutuar.
* Um modelo com mais de 255 ossos totais precisa do indice de osso em u32.
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest

from gc3d import ConvertOptions, convert_model, convert_to_gc
from gc3d.formats import frm as frm_format
from gc3d.formats import gltf_in
from gc3d.formats import p3m as p3m_format
from gc3d.formats.glb import export_glb
from gc3d.mathutil import mat4_from_trs, mat4_to_quaternion
from gc3d.scene import NO_JOINT, Animation, Joint, Keyframe, Mesh, Scene, Vertex

from . import SAMPLES_DIR

P3M_DIR = os.path.join(SAMPLES_DIR, "p3m")
FRM_DIR = os.path.join(SAMPLES_DIR, "frm")


# ----------------------------------------------------------- glTF sintetico


def build_glb(root: dict, binary: bytes = b"") -> bytes:
    """Empacota um dict glTF e um buffer num GLB valido."""
    json_bytes = json.dumps(root).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    binary += b"\0" * ((-len(binary)) % 4)
    total = 12 + 8 + len(json_bytes) + (8 + len(binary) if binary else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)
    out += json_bytes
    if binary:
        out += struct.pack("<II", len(binary), 0x004E4942)
        out += binary
    return bytes(out)


def minimal_skinned_gltf(
    joint_nodes_order: list[int] | None = None,
    root_translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    joint_names: list[str] | None = None,
) -> bytes:
    """glTF com 2 ossos, 3 vertices e um no raiz opcionalmente transladado.

    `joint_nodes_order` permite embaralhar `skin.joints` de proposito, para
    reproduzir o que o exportador do Blender faz.
    """
    positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    positions = [
        (p[0] + root_translation[0], p[1] + root_translation[1], p[2] + root_translation[2])
        for p in positions
    ]
    normals = [(0.0, 0.0, 1.0)] * 3
    uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    indices = [0, 1, 2]

    # Nos: 0 e 1 sao ossos, 2 e o "root", 3 e a malha.
    skin_joints = joint_nodes_order or [0, 1]
    names = joint_names or ["bone_0", "bone_1"]

    binary = bytearray()

    def add(data: bytes) -> tuple[int, int]:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(data)
        return offset, len(data)

    pos_off, pos_len = add(b"".join(struct.pack("<3f", *p) for p in positions))
    nor_off, nor_len = add(b"".join(struct.pack("<3f", *n) for n in normals))
    uv_off, uv_len = add(b"".join(struct.pack("<2f", *u) for u in uvs))
    # JOINTS_0: cada vertice usa o indice de skin 0, 0, 1
    joints_data = b"".join(struct.pack("<4B", j, 0, 0, 0) for j in (0, 0, 1))
    joi_off, joi_len = add(joints_data)
    wei_off, wei_len = add(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(3)))
    idx_off, idx_len = add(struct.pack("<3H", *indices))
    ibm_off, ibm_len = add(
        b"".join(
            struct.pack(
                "<16f",
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            )
            for _ in skin_joints
        )
    )

    views = [
        {"buffer": 0, "byteOffset": pos_off, "byteLength": pos_len},
        {"buffer": 0, "byteOffset": nor_off, "byteLength": nor_len},
        {"buffer": 0, "byteOffset": uv_off, "byteLength": uv_len},
        {"buffer": 0, "byteOffset": joi_off, "byteLength": joi_len},
        {"buffer": 0, "byteOffset": wei_off, "byteLength": wei_len},
        {"buffer": 0, "byteOffset": idx_off, "byteLength": idx_len},
        {"buffer": 0, "byteOffset": ibm_off, "byteLength": ibm_len},
    ]
    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [min(p[i] for p in positions) for i in range(3)],
            "max": [max(p[i] for p in positions) for i in range(3)],
        },
        {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
        {"bufferView": 3, "componentType": 5121, "count": 3, "type": "VEC4"},
        {"bufferView": 4, "componentType": 5126, "count": 3, "type": "VEC4"},
        {"bufferView": 5, "componentType": 5123, "count": 3, "type": "SCALAR"},
        {
            "bufferView": 6,
            "componentType": 5126,
            "count": len(skin_joints),
            "type": "MAT4",
        },
    ]

    nodes = [
        {"name": names[0]},
        {"name": names[1], "translation": [0.0, 2.0, 0.0]},
        {"name": "root", "children": [0], "translation": list(root_translation)},
        {"name": "mesh_test", "mesh": 0, "skin": 0},
    ]
    nodes[0]["children"] = [1]

    root = {
        "asset": {"version": "2.0", "generator": "teste"},
        "scene": 0,
        "scenes": [{"nodes": [2, 3]}],
        "nodes": nodes,
        "meshes": [
            {
                "name": "mesh_test",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                            "JOINTS_0": 3,
                            "WEIGHTS_0": 4,
                        },
                        "indices": 5,
                        "mode": 4,
                    }
                ],
            }
        ],
        "skins": [
            {"joints": skin_joints, "inverseBindMatrices": 6, "skeleton": 2}
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    return build_glb(root, bytes(binary))


class TestGltfContainer(unittest.TestCase):
    def test_reads_glb(self) -> None:
        document = gltf_in.read_gltf(minimal_skinned_gltf())
        self.assertEqual(document.json["asset"]["version"], "2.0")
        self.assertEqual(len(document.buffers), 1)

    def test_reads_gltf_json_with_data_uri(self) -> None:
        import base64

        payload = struct.pack("<3f", 1.0, 2.0, 3.0)
        root = {
            "asset": {"version": "2.0"},
            "buffers": [
                {
                    "byteLength": len(payload),
                    "uri": "data:application/octet-stream;base64,"
                    + base64.b64encode(payload).decode("ascii"),
                }
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": len(payload)}
            ],
            "accessors": [
                {"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}
            ],
        }
        document = gltf_in.read_gltf(json.dumps(root).encode("utf-8"))
        self.assertEqual(document.read_accessor(0), [(1.0, 2.0, 3.0)])

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(gltf_in.InvalidGltfError):
            gltf_in.read_gltf(b"isso nao e um gltf de jeito nenhum")

    def test_normalized_accessor_is_scaled(self) -> None:
        payload = struct.pack("<4B", 0, 255, 128, 255)
        root = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(payload)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": len(payload)}
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5121,
                    "count": 1,
                    "type": "VEC4",
                    "normalized": True,
                }
            ],
        }
        document = gltf_in.read_gltf(build_glb(root, payload))
        values = document.read_accessor(0)[0]
        self.assertAlmostEqual(values[0], 0.0)
        self.assertAlmostEqual(values[1], 1.0)
        self.assertAlmostEqual(values[2], 128 / 255)


class TestGltfSkeleton(unittest.TestCase):
    def test_joints_and_hierarchy(self) -> None:
        document = gltf_in.read_gltf(minimal_skinned_gltf())
        scene = gltf_in.gltf_to_scene(document, "t")
        self.assertEqual(len(scene.skeleton), 2)
        self.assertIsNone(scene.skeleton[0].parent)
        self.assertEqual(scene.skeleton[1].parent, 0)
        self.assertEqual(scene.skeleton[0].children, [1])
        self.assertEqual(scene.skeleton[1].translation, (0.0, 2.0, 0.0))

    def test_joints_0_indexes_skin_joints_not_nodes(self) -> None:
        """Ossos embaralhados: o vertice tem de continuar no osso certo.

        Com `skin.joints = [1, 0]`, o valor 0 em JOINTS_0 aponta para o **no 1**
        (bone_1), nao para o no 0. Tratar o valor como indice de no colocaria os
        vertices no osso errado, e o erro so aparece com arquivos de outras
        ferramentas, porque as duas ordens coincidem nos arquivos deste projeto.
        """
        document = gltf_in.read_gltf(minimal_skinned_gltf(joint_nodes_order=[1, 0]))
        scene = gltf_in.gltf_to_scene(document, "t")
        vertices = scene.meshes[0].vertices
        # Vertices 0 e 1 usam skin index 0 -> no 1 -> bone_1 -> joint 1.
        # Vertice 2 usa skin index 1 -> no 0 -> bone_0 -> joint 0.
        self.assertEqual([v.joint for v in vertices], [1, 1, 0])

    def test_bone_names_restore_canonical_order(self) -> None:
        """A numeracao bone_N deve sobreviver a reordenacao do exportador."""
        document = gltf_in.read_gltf(minimal_skinned_gltf(joint_nodes_order=[1, 0]))
        scene = gltf_in.gltf_to_scene(document, "t")
        # Apesar de skin.joints estar invertido, joint 0 deve ser bone_0.
        self.assertEqual(scene.skeleton[0].name, "bone_0")
        self.assertEqual(scene.skeleton[1].name, "bone_1")

    def test_root_node_translation_is_not_baked_into_bind_pose(self) -> None:
        """A posicao no mundo pertence a animacao, nao ao bind pose.

        O exportador do Blender assa o primeiro keyframe do movimento da raiz na
        pose de descanso. Se essa translacao entrasse no P3M, o jogo somaria o
        deslocamento duas vezes e o modelo flutuaria.
        """
        plain = gltf_in.gltf_to_scene(
            gltf_in.read_gltf(minimal_skinned_gltf()), "t"
        )
        shifted = gltf_in.gltf_to_scene(
            gltf_in.read_gltf(minimal_skinned_gltf(root_translation=(0.0, 5.0, 0.0))),
            "t",
        )
        for a, b in zip(plain.meshes[0].vertices, shifted.meshes[0].vertices):
            for x, y in zip(a.position, b.position):
                self.assertAlmostEqual(x, y, places=5)
        for a, b in zip(plain.skeleton, shifted.skeleton):
            for x, y in zip(a.translation, b.translation):
                self.assertAlmostEqual(x, y, places=5)

    def test_scene_is_right_handed(self) -> None:
        scene = gltf_in.gltf_to_scene(gltf_in.read_gltf(minimal_skinned_gltf()), "t")
        self.assertTrue(scene.right_handed)


class TestGltfAnimationResampling(unittest.TestCase):
    def _animated_gltf(self, times: list[float]) -> bytes:
        """glTF com um canal de rotacao nos instantes dados."""
        document = gltf_in.read_gltf(minimal_skinned_gltf())
        root = document.json
        binary = bytearray(document.buffers[0])

        def add(data: bytes) -> tuple[int, int]:
            while len(binary) % 4:
                binary.append(0)
            offset = len(binary)
            binary.extend(data)
            return offset, len(data)

        time_off, time_len = add(struct.pack(f"<{len(times)}f", *times))
        quats = b"".join(struct.pack("<4f", 0.0, 0.0, 0.0, 1.0) for _ in times)
        quat_off, quat_len = add(quats)

        root["bufferViews"].append(
            {"buffer": 0, "byteOffset": time_off, "byteLength": time_len}
        )
        root["bufferViews"].append(
            {"buffer": 0, "byteOffset": quat_off, "byteLength": quat_len}
        )
        time_accessor = len(root["accessors"])
        root["accessors"].append(
            {
                "bufferView": len(root["bufferViews"]) - 2,
                "componentType": 5126,
                "count": len(times),
                "type": "SCALAR",
                "min": [times[0]],
                "max": [times[-1]],
            }
        )
        quat_accessor = len(root["accessors"])
        root["accessors"].append(
            {
                "bufferView": len(root["bufferViews"]) - 1,
                "componentType": 5126,
                "count": len(times),
                "type": "VEC4",
            }
        )
        root["animations"] = [
            {
                "name": "andar",
                "samplers": [
                    {
                        "input": time_accessor,
                        "output": quat_accessor,
                        "interpolation": "LINEAR",
                    }
                ],
                "channels": [
                    {"sampler": 0, "target": {"node": 0, "path": "rotation"}}
                ],
            }
        ]
        root["buffers"][0]["byteLength"] = len(binary)
        return build_glb(root, bytes(binary))

    def test_sparse_keyframes_are_resampled_to_55_fps(self) -> None:
        """Reamostragem: e o que faltava no importador do conversor antigo.

        Com keyframes so em 0s e 1s, uma animacao de 1 segundo precisa virar
        56 frames a 55 FPS, nao 2.
        """
        document = gltf_in.read_gltf(self._animated_gltf([0.0, 1.0]))
        scene = gltf_in.gltf_to_scene(document, "t")
        self.assertEqual(len(scene.animations), 1)
        animation = scene.animations[0]
        self.assertEqual(animation.fps, 55)
        self.assertEqual(len(animation.frames), 56)
        self.assertAlmostEqual(animation.duration, 1.0, places=3)

    def test_every_frame_has_one_matrix_per_joint(self) -> None:
        document = gltf_in.read_gltf(self._animated_gltf([0.0, 0.5]))
        scene = gltf_in.gltf_to_scene(document, "t")
        for frame in scene.animations[0].frames:
            self.assertEqual(len(frame.transforms), len(scene.skeleton))


# ------------------------------------------------------------ escritores


def simple_left_handed_scene() -> Scene:
    scene = Scene(right_handed=False)
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
                Vertex((0.0, 3.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0), 1, 1.0),
            ],
            indices=[0, 1, 2],
        )
    ]
    return scene


class TestP3mWriter(unittest.TestCase):
    def test_written_file_reads_back(self) -> None:
        scene = simple_left_handed_scene()
        model = p3m_format.scene_to_p3m(scene)
        data = p3m_format.write_p3m(model)
        reread = p3m_format.read_p3m(data)

        self.assertEqual(reread.version, "0.5")
        self.assertEqual(reread.num_angle_bones, 2)
        self.assertEqual(len(reread.skin_vertices), 3)
        self.assertEqual(reread.faces, [(0, 1, 2)])
        self.assertEqual(reread.trailing_bytes, 0)

    def test_one_position_bone_per_angle_bone(self) -> None:
        model = p3m_format.scene_to_p3m(simple_left_handed_scene())
        self.assertEqual(model.num_position_bones, model.num_angle_bones)

    def test_vertex_position_is_relative_to_bone(self) -> None:
        scene = simple_left_handed_scene()
        model = p3m_format.scene_to_p3m(scene)
        # Vertice 2 esta em (0,3,0) e pertence ao joint 1, cuja posicao mundial
        # e (0,2,0): a posicao gravada deve ser (0,1,0).
        self.assertAlmostEqual(model.skin_vertices[2].position[1], 1.0, places=5)

    def test_scene_to_p3m_refuses_right_handed(self) -> None:
        scene = simple_left_handed_scene()
        scene.right_handed = True
        with self.assertRaises(ValueError):
            p3m_format.scene_to_p3m(scene)

    def test_u8_encoding_for_small_skeletons(self) -> None:
        model = p3m_format.scene_to_p3m(simple_left_handed_scene())
        self.assertEqual(model.bone_index_encoding, "u8")
        reread = p3m_format.read_p3m(p3m_format.write_p3m(model))
        self.assertEqual(reread.bone_index_encoding, "u8")

    def test_u32_encoding_above_255_total_bones(self) -> None:
        """Mais de 255 ossos totais nao cabem em um byte de indice."""
        scene = Scene(right_handed=False)
        count = 200  # 200 position + 200 angle = 400 > 255
        scene.skeleton = [Joint(name=f"bone_{i}") for i in range(count)]
        scene.meshes = [
            Mesh(
                name="grande",
                vertices=[
                    Vertex((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), count - 1, 1.0)
                ],
                indices=[],
            )
        ]
        model = p3m_format.scene_to_p3m(scene)
        self.assertEqual(model.bone_index_encoding, "u32")
        reread = p3m_format.read_p3m(p3m_format.write_p3m(model))
        self.assertEqual(reread.bone_index_encoding, "u32")
        self.assertEqual(
            reread.skin_vertices[0].bone_index, (count - 1) + count
        )

    def test_rejects_too_many_bones(self) -> None:
        scene = Scene(right_handed=False)
        scene.skeleton = [Joint(name=f"bone_{i}") for i in range(300)]
        with self.assertRaises(p3m_format.P3mLimitError):
            p3m_format.scene_to_p3m(scene)

    def test_rejects_too_many_vertices(self) -> None:
        scene = Scene(right_handed=False)
        scene.skeleton = [Joint(name="bone_0")]
        scene.meshes = [
            Mesh(
                name="enorme",
                vertices=[
                    Vertex((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), 0, 1.0)
                ]
                * 70000,
                indices=[],
            )
        ]
        with self.assertRaises(p3m_format.P3mLimitError):
            p3m_format.scene_to_p3m(scene)

    def test_unskinned_vertices_get_sentinel(self) -> None:
        scene = simple_left_handed_scene()
        for vertex in scene.meshes[0].vertices:
            vertex.joint = NO_JOINT
        model = p3m_format.scene_to_p3m(scene)
        for vertex in model.skin_vertices:
            self.assertEqual(vertex.bone_index, p3m_format.INVALID_BONE_INDEX)


class TestFrmWriter(unittest.TestCase):
    def _animation(self) -> Animation:
        identity = mat4_from_trs((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        return Animation(
            name="andar",
            fps=55,
            frames=[
                Keyframe(translation=(1.0, 10.0, 100.0), transforms=[identity]),
                Keyframe(translation=(3.0, 20.0, 200.0), transforms=[identity]),
                Keyframe(translation=(6.0, 30.0, 300.0), transforms=[identity]),
            ],
        )

    def test_round_trip_through_bytes(self) -> None:
        animation = self._animation()
        written = frm_format.write_frm(frm_format.animation_to_frm(animation, 1))
        reread = frm_format.read_frm(written)
        self.assertEqual(reread.version, "1.1")
        self.assertEqual(reread.num_frames, 3)
        self.assertEqual(reread.num_bones, 1)
        self.assertEqual(reread.trailing_bytes, 0)

    def test_plus_x_becomes_delta_again(self) -> None:
        """A escrita tem de reverter a acumulacao feita na leitura."""
        frm = frm_format.animation_to_frm(self._animation(), 1)
        self.assertAlmostEqual(frm.frames[0].plus_x, 1.0)
        self.assertAlmostEqual(frm.frames[1].plus_x, 2.0)
        self.assertAlmostEqual(frm.frames[2].plus_x, 3.0)

    def test_pos_y_and_pos_z_stay_absolute(self) -> None:
        frm = frm_format.animation_to_frm(self._animation(), 1)
        self.assertEqual([f.pos_y for f in frm.frames], [10.0, 20.0, 30.0])
        self.assertEqual([f.pos_z for f in frm.frames], [100.0, 200.0, 300.0])

    def test_translation_survives_round_trip(self) -> None:
        animation = self._animation()
        written = frm_format.write_frm(frm_format.animation_to_frm(animation, 1))
        recovered = frm_format.frm_to_animation(frm_format.read_frm(written), "x")
        for original, back in zip(animation.frames, recovered.frames):
            for a, b in zip(original.translation, back.translation):
                self.assertAlmostEqual(a, b, places=4)

    def test_refuses_wrong_fps(self) -> None:
        animation = self._animation()
        animation.fps = 30
        with self.assertRaises(frm_format.InvalidFrmError):
            frm_format.animation_to_frm(animation, 1)

    def test_missing_matrices_are_filled_with_identity(self) -> None:
        animation = self._animation()
        frm = frm_format.animation_to_frm(animation, 3)
        self.assertEqual(frm.num_bones, 3)
        for frame in frm.frames:
            self.assertEqual(len(frame.bones), 3)


# --------------------------------------------------------------- ida e volta


class TestRoundTripSynthetic(unittest.TestCase):
    def test_scene_survives_glb_and_back(self) -> None:
        scene = simple_left_handed_scene()
        identity = mat4_from_trs((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        scene.animations = [
            Animation(
                name="anda",
                fps=55,
                frames=[
                    Keyframe(translation=(0.0, 1.0, 0.0), transforms=[identity] * 2),
                    Keyframe(translation=(1.0, 1.0, 0.0), transforms=[identity] * 2),
                ],
            )
        ]

        original_positions = [v.position for v in scene.meshes[0].vertices]
        original_joints = [v.joint for v in scene.meshes[0].vertices]

        data = export_glb(scene.to_right_handed())
        recovered = gltf_in.gltf_to_scene(gltf_in.read_gltf(data), "t")
        recovered.to_left_handed()

        self.assertEqual(len(recovered.skeleton), 2)
        self.assertEqual(
            [v.joint for v in recovered.meshes[0].vertices], original_joints
        )
        for a, b in zip(original_positions, [v.position for v in recovered.meshes[0].vertices]):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=5)

    def test_left_and_right_handed_are_inverse(self) -> None:
        scene = simple_left_handed_scene()
        before = [v.position for v in scene.meshes[0].vertices]
        indices_before = list(scene.meshes[0].indices)
        scene.to_right_handed().to_left_handed()
        self.assertEqual([v.position for v in scene.meshes[0].vertices], before)
        self.assertEqual(scene.meshes[0].indices, indices_before)


@unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
class TestRoundTripRealFiles(unittest.TestCase):
    def _samples(self) -> list[str]:
        return [
            os.path.join(P3M_DIR, name)
            for name in sorted(os.listdir(P3M_DIR))
            if name.lower().endswith(".p3m")
        ]

    def test_every_sample_survives_round_trip(self) -> None:
        for model_path in self._samples():
            with self.subTest(arquivo=os.path.basename(model_path)):
                with tempfile.TemporaryDirectory() as tmp:
                    glb = os.path.join(tmp, "a.glb")
                    forward = convert_model(
                        model_path, glb, [], ConvertOptions(embed_texture=False)
                    )
                    self.assertTrue(forward.ok, forward.error)

                    back_dir = os.path.join(tmp, "back")
                    backward = convert_to_gc(glb, back_dir)
                    self.assertTrue(backward.ok, backward.error)

                    original = p3m_format.load_p3m(model_path)
                    rebuilt = p3m_format.load_p3m(os.path.join(back_dir, "a.p3m"))

                    self.assertEqual(
                        original.num_angle_bones, rebuilt.num_angle_bones
                    )
                    self.assertEqual(
                        len(original.skin_vertices), len(rebuilt.skin_vertices)
                    )
                    self.assertEqual(original.faces, rebuilt.faces)

                    # O joint resolvido tem de ser o mesmo; o indice absoluto
                    # muda porque a escrita usa um PositionBone por AngleBone.
                    joints_a = [
                        v.bone_index - original.num_position_bones
                        for v in original.skin_vertices
                    ]
                    joints_b = [
                        v.bone_index - rebuilt.num_position_bones
                        for v in rebuilt.skin_vertices
                    ]
                    self.assertEqual(joints_a, joints_b)

                    for va, vb in zip(original.skin_vertices, rebuilt.skin_vertices):
                        for x, y in zip(va.position, vb.position):
                            self.assertAlmostEqual(x, y, places=4)
                        for x, y in zip(va.uv, vb.uv):
                            self.assertAlmostEqual(x, y, places=5)

    @unittest.skipUnless(os.path.isdir(FRM_DIR), "samples/frm ausente")
    def test_animation_survives_round_trip(self) -> None:
        animations = [
            os.path.join(FRM_DIR, name)
            for name in sorted(os.listdir(FRM_DIR))
            if name.lower().endswith(".frm")
        ]
        pairs = []
        for model_path in self._samples():
            bones = p3m_format.load_p3m(model_path).num_angle_bones
            for animation_path in animations:
                if frm_format.load_frm(animation_path).num_bones == bones:
                    pairs.append((model_path, animation_path))
                    break
        if not pairs:
            self.skipTest("nenhum par compativel de modelo e animacao")

        for model_path, animation_path in pairs:
            with self.subTest(arquivo=os.path.basename(animation_path)):
                with tempfile.TemporaryDirectory() as tmp:
                    glb = os.path.join(tmp, "a.glb")
                    convert_model(
                        model_path,
                        glb,
                        [animation_path],
                        ConvertOptions(embed_texture=False),
                    )
                    back_dir = os.path.join(tmp, "back")
                    convert_to_gc(glb, back_dir)

                    stem = os.path.splitext(os.path.basename(animation_path))[0]
                    rebuilt_path = os.path.join(back_dir, f"a_{stem}.frm")
                    self.assertTrue(os.path.isfile(rebuilt_path))

                    original = frm_format.load_frm(animation_path)
                    rebuilt = frm_format.load_frm(rebuilt_path)
                    self.assertEqual(original.num_frames, rebuilt.num_frames)
                    self.assertEqual(original.num_bones, rebuilt.num_bones)

                    animation_a = frm_format.frm_to_animation(original, "a")
                    animation_b = frm_format.frm_to_animation(rebuilt, "b")
                    for fa, fb in zip(animation_a.frames, animation_b.frames):
                        for x, y in zip(fa.translation, fb.translation):
                            self.assertAlmostEqual(x, y, places=4)
                        for ma, mb in zip(fa.transforms, fb.transforms):
                            qa = mat4_to_quaternion(ma)
                            qb = mat4_to_quaternion(mb)
                            delta = min(
                                max(abs(x - y) for x, y in zip(qa, qb)),
                                max(abs(x + y) for x, y in zip(qa, qb)),
                            )
                            self.assertLess(delta, 1e-3)


if __name__ == "__main__":
    unittest.main()
