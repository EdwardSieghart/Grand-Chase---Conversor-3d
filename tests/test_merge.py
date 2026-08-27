"""Testes da conversao unificada: varios modelos e animacoes num unico GLB.

O ponto central destes testes e que **contagem de ossos nao identifica um
esqueleto**. Medindo os 127 modelos do conjunto de teste ha 18 esqueletos
distintos, e sete deles tem exatamente 15 ossos. Juntar modelos de esqueletos
diferentes numa unica `skin` misturaria bind poses e deformaria a malha; por isso
o agrupamento usa translacoes e hierarquia, e o GLB recebe uma `skin` por grupo.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

from glb_inspect import Glb, validate

from gc3d import ConvertOptions, convert_merged, skeleton_signature
from gc3d.formats import p3m as p3m_format
from gc3d.formats.glb import export_glb
from gc3d.scene import Joint, Mesh, Scene, Vertex

from . import SAMPLES_DIR

P3M_DIR = os.path.join(SAMPLES_DIR, "p3m")
FRM_DIR = os.path.join(SAMPLES_DIR, "frm")
DDS_DIR = os.path.join(SAMPLES_DIR, "dds")


def samples() -> list[str]:
    if not os.path.isdir(P3M_DIR):
        return []
    return [
        os.path.join(P3M_DIR, name)
        for name in sorted(os.listdir(P3M_DIR))
        if name.lower().endswith(".p3m")
    ]


def animations() -> list[str]:
    if not os.path.isdir(FRM_DIR):
        return []
    return [
        os.path.join(FRM_DIR, name)
        for name in sorted(os.listdir(FRM_DIR))
        if name.lower().endswith(".frm")
    ]


def build_scene(num_joints: int, translation_y: float, name: str) -> Scene:
    """Cena minima com o numero de ossos e a altura pedidos."""
    scene = Scene(right_handed=True)
    scene.skeleton = [
        Joint(
            name=f"bone_{i}",
            translation=(0.0, translation_y * i, 0.0),
            parent=(i - 1) if i else None,
            children=[i + 1] if i + 1 < num_joints else [],
        )
        for i in range(num_joints)
    ]
    scene.meshes = [
        Mesh(
            name=name,
            vertices=[
                Vertex((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0), 0, 1.0),
                Vertex((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0), 0, 1.0),
                Vertex((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0), 0, 1.0),
            ],
            indices=[0, 1, 2],
        )
    ]
    return scene


class TestSkeletonSignature(unittest.TestCase):
    def test_same_skeleton_same_signature(self) -> None:
        a = build_scene(4, 0.5, "a")
        b = build_scene(4, 0.5, "b")
        self.assertEqual(skeleton_signature(a), skeleton_signature(b))

    def test_bone_count_alone_is_not_enough(self) -> None:
        """Mesmo numero de ossos, bind pose diferente: esqueletos diferentes."""
        a = build_scene(4, 0.5, "a")
        b = build_scene(4, 0.9, "b")
        self.assertNotEqual(skeleton_signature(a), skeleton_signature(b))

    def test_different_bone_count_differs(self) -> None:
        self.assertNotEqual(
            skeleton_signature(build_scene(4, 0.5, "a")),
            skeleton_signature(build_scene(5, 0.5, "b")),
        )

    @unittest.skipUnless(samples(), "samples/p3m ausente")
    def test_real_models_group_consistently(self) -> None:
        """A assinatura tem de ser estavel entre leituras do mesmo arquivo."""
        for path in samples()[:4]:
            with self.subTest(arquivo=os.path.basename(path)):
                first = skeleton_signature(
                    p3m_format.p3m_to_scene(p3m_format.load_p3m(path), "x")
                )
                second = skeleton_signature(
                    p3m_format.p3m_to_scene(p3m_format.load_p3m(path), "x")
                )
                self.assertEqual(first, second)


class TestExportMultipleScenes(unittest.TestCase):
    """O exportador precisa aceitar varias cenas num arquivo, com skins separadas."""

    def _write(self, scenes) -> Glb:
        data = export_glb(scenes)
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        tmp.write(data)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return Glb(tmp.name)

    def test_two_skeletons_two_skins(self) -> None:
        glb = self._write([build_scene(3, 0.5, "a"), build_scene(5, 0.7, "b")])
        self.assertEqual(validate(glb), [])
        self.assertEqual(len(glb.json["skins"]), 2)
        self.assertEqual(len(glb.json["skins"][0]["joints"]), 3)
        self.assertEqual(len(glb.json["skins"][1]["joints"]), 5)

    def test_joint_indices_do_not_overlap(self) -> None:
        glb = self._write([build_scene(3, 0.5, "a"), build_scene(5, 0.7, "b")])
        first = set(glb.json["skins"][0]["joints"])
        second = set(glb.json["skins"][1]["joints"])
        self.assertEqual(first & second, set(), "os blocos de joints devem ser disjuntos")

    def test_each_mesh_points_to_its_own_skin(self) -> None:
        glb = self._write([build_scene(3, 0.5, "a"), build_scene(5, 0.7, "b")])
        mesh_nodes = [n for n in glb.json["nodes"] if "mesh" in n]
        self.assertEqual(len(mesh_nodes), 2)
        self.assertEqual({n["skin"] for n in mesh_nodes}, {0, 1})

    def test_skeleton_points_to_group_root(self) -> None:
        glb = self._write([build_scene(3, 0.5, "a"), build_scene(5, 0.7, "b")])
        for index, skin in enumerate(glb.json["skins"]):
            root = glb.json["nodes"][skin["skeleton"]]
            self.assertTrue(
                (root.get("name") or "").startswith("root"),
                f"skin {index} deveria apontar para um no root, veio {root}",
            )

    def test_single_scene_still_names_root_plainly(self) -> None:
        """Com um grupo so, o no deve se chamar "root".

        O importador procura por esse nome ao trazer o arquivo de volta; mudar
        para "root_0" quebraria a ida e volta.
        """
        glb = self._write(build_scene(3, 0.5, "a"))
        names = [n.get("name") for n in glb.json["nodes"]]
        self.assertIn("root", names)

    def test_refuses_left_handed_scene(self) -> None:
        scene = build_scene(3, 0.5, "a")
        scene.right_handed = False
        with self.assertRaises(ValueError):
            export_glb([scene])

    def test_per_mesh_texture_becomes_per_mesh_material(self) -> None:
        from gc3d.textures import encode_png

        red = encode_png(2, 2, bytes([255, 0, 0, 255] * 4))
        blue = encode_png(2, 2, bytes([0, 0, 255, 255] * 4))
        a = build_scene(3, 0.5, "a")
        b = build_scene(3, 0.5, "b")
        a.meshes[0].texture_png = red
        b.meshes[0].texture_png = blue

        glb = self._write([a, b])
        self.assertEqual(validate(glb), [])
        self.assertEqual(len(glb.json["images"]), 2)
        self.assertEqual(len(glb.json["materials"]), 2)
        materials = {
            n["mesh"]: glb.json["meshes"][n["mesh"]]["primitives"][0]["material"]
            for n in glb.json["nodes"]
            if "mesh" in n
        }
        self.assertEqual(len(set(materials.values())), 2)

    def test_same_texture_is_not_duplicated(self) -> None:
        from gc3d.textures import encode_png

        shared = encode_png(2, 2, bytes([0, 255, 0, 255] * 4))
        a = build_scene(3, 0.5, "a")
        b = build_scene(3, 0.5, "b")
        a.meshes[0].texture_png = shared
        b.meshes[0].texture_png = shared

        glb = self._write([a, b])
        self.assertEqual(
            len(glb.json["images"]), 1, "a mesma imagem nao deve entrar duas vezes"
        )


@unittest.skipUnless(samples(), "samples/p3m ausente")
class TestConvertMerged(unittest.TestCase):
    def test_produces_one_file_with_every_mesh(self) -> None:
        models = samples()
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "tudo.glb")
            result = convert_merged(
                models, [], output, ConvertOptions(embed_texture=False)
            )
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.outputs, [output])

            glb = Glb(output)
            self.assertEqual(validate(glb), [])
            # Modelos sem skinning nao geram skin, mas geram malha.
            self.assertEqual(len(glb.json["meshes"]), len(models))

    def test_vertex_total_is_preserved(self) -> None:
        models = samples()
        expected = 0
        for path in models:
            expected += len(p3m_format.load_p3m(path).skin_vertices)

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "tudo.glb")
            convert_merged(models, [], output, ConvertOptions(embed_texture=False))
            glb = Glb(output)
            total = 0
            for mesh in glb.json["meshes"]:
                accessor = glb.json["accessors"][
                    mesh["primitives"][0]["attributes"]["POSITION"]
                ]
                total += accessor["count"]
        self.assertEqual(total, expected)

    def test_animations_go_to_matching_skeleton(self) -> None:
        if not animations():
            self.skipTest("samples/frm ausente")
        from gc3d.formats import frm as frm_format

        models = samples()
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "tudo.glb")
            result = convert_merged(
                models, animations(), output, ConvertOptions(embed_texture=False)
            )
            self.assertTrue(result.ok, result.error)
            glb = Glb(output)
            self.assertEqual(validate(glb), [])

            # Cada animacao deve mirar os nos de uma skin cujo numero de joints
            # bate com o numero de ossos do FRM.
            joint_sets = [set(skin["joints"]) for skin in glb.json.get("skins", [])]
            for animation in glb.json["animations"]:
                targets = {
                    c["target"]["node"]
                    for c in animation["channels"]
                    if c["target"]["path"] == "rotation"
                }
                if not targets:
                    continue
                self.assertTrue(
                    any(targets <= joints for joints in joint_sets),
                    f"a animacao {animation.get('name')} mira nos de mais de um "
                    f"esqueleto",
                )

    def test_no_animation_is_silently_dropped(self) -> None:
        if not animations():
            self.skipTest("samples/frm ausente")
        models = samples()
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "tudo.glb")
            result = convert_merged(
                models, animations(), output, ConvertOptions(embed_texture=False)
            )
            glb = Glb(output)
            self.assertEqual(
                len(glb.json.get("animations", [])),
                len(animations()),
                "toda animacao informada tem de aparecer no arquivo",
            )

    def test_requires_at_least_one_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_merged([], animations(), os.path.join(tmp, "x.glb"))
            self.assertFalse(result.ok)
            self.assertIn("modelo", (result.error or "").lower())

    def test_reports_multiple_skeletons(self) -> None:
        """Com esqueletos diferentes, o aviso tem de dizer isso."""
        models = samples()
        signatures = {
            skeleton_signature(
                p3m_format.p3m_to_scene(p3m_format.load_p3m(p), "x")
            )
            for p in models
        }
        if len(signatures) < 2:
            self.skipTest("as amostras compartilham o mesmo esqueleto")
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_merged(
                models,
                [],
                os.path.join(tmp, "tudo.glb"),
                ConvertOptions(embed_texture=False),
            )
            self.assertTrue(result.ok, result.error)
            self.assertTrue(
                any("esqueletos diferentes" in w for w in result.warnings),
                f"esperava aviso sobre esqueletos, veio: {result.warnings}",
            )

    @unittest.skipUnless(os.path.isdir(DDS_DIR), "samples/dds ausente")
    def test_each_model_keeps_its_own_texture(self) -> None:
        models = samples()
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "tudo.glb")
            result = convert_merged(
                models,
                [],
                output,
                ConvertOptions(embed_texture=True, texture_dirs=[DDS_DIR]),
            )
            self.assertTrue(result.ok, result.error)
            glb = Glb(output)
            self.assertEqual(validate(glb), [])
            self.assertGreater(
                len(glb.json.get("images", [])),
                1,
                "modelos com texturas diferentes devem gerar imagens diferentes",
            )


if __name__ == "__main__":
    unittest.main()
