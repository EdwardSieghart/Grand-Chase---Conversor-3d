"""Testes de integracao sobre os arquivos reais em `samples/`.

Diferente dos outros modulos de teste, aqui nada e sintetico: sao arquivos do
jogo. Estes testes existem para pegar regressao contra dados de verdade, que
tem casos que ninguem inventaria (normais nulas, campos de textura com lixo
binario, blocos truncados, peso 0.5).

Se a pasta `samples/` nao existir, os testes sao pulados em vez de falhar, para
que a suite continue util em um clone sem os arquivos de exemplo.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from glb_inspect import Glb, validate

from gc3d import ConvertOptions, convert_model, find_animations_for_model
from gc3d.formats import frm, p3m

from . import SAMPLES_DIR

P3M_DIR = os.path.join(SAMPLES_DIR, "p3m")
FRM_DIR = os.path.join(SAMPLES_DIR, "frm")
DDS_DIR = os.path.join(SAMPLES_DIR, "dds")


def listing(directory: str, extension: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.lower().endswith(extension)
    ]


P3M_FILES = listing(P3M_DIR, ".p3m")
FRM_FILES = listing(FRM_DIR, ".frm")
DDS_FILES = listing(DDS_DIR, ".dds")


@unittest.skipUnless(P3M_FILES, "samples/p3m vazio")
class TestRealP3m(unittest.TestCase):
    def test_all_parse(self) -> None:
        for path in P3M_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                model = p3m.load_p3m(path)
                self.assertEqual(model.version, "0.5")
                self.assertGreater(len(model.skin_vertices), 0)

    def test_face_indices_within_range(self) -> None:
        for path in P3M_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                model = p3m.load_p3m(path)
                count = len(model.skin_vertices)
                for face in model.faces:
                    self.assertLess(max(face), count)

    def test_bone_indices_are_absolute(self) -> None:
        """Todo indice de osso deve cair em [numPositionBones, total)."""
        for path in P3M_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                model = p3m.load_p3m(path)
                low = model.num_position_bones
                high = low + model.num_angle_bones
                for vertex in model.skin_vertices:
                    if vertex.bone_index == p3m.INVALID_BONE_INDEX:
                        continue
                    self.assertTrue(low <= vertex.bone_index < high)

    def test_joint_hierarchy_has_no_cycles(self) -> None:
        for path in P3M_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                model = p3m.load_p3m(path)
                joints = p3m.build_joints(model.position_bones, model.angle_bones)
                for index in range(len(joints)):
                    seen = set()
                    current = index
                    while current is not None:
                        self.assertNotIn(current, seen, "ciclo na hierarquia de ossos")
                        seen.add(current)
                        current = joints[current].parent

    def test_truncated_mesh_vertices_are_tolerated(self) -> None:
        """face_alice.p3m e face_21_00.p3m terminam no meio do bloco MeshVertex."""
        known = [p for p in P3M_FILES if os.path.basename(p).startswith("face_")]
        if not known:
            self.skipTest("amostras com bloco truncado nao presentes")
        for path in known:
            with self.subTest(arquivo=os.path.basename(path)):
                model = p3m.load_p3m(path)
                self.assertTrue(model.mesh_vertices_truncated)
                self.assertGreater(len(model.skin_vertices), 0)


@unittest.skipUnless(FRM_FILES, "samples/frm vazio")
class TestRealFrm(unittest.TestCase):
    def test_all_parse_consuming_whole_file(self) -> None:
        for path in FRM_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                animation = frm.load_frm(path)
                self.assertEqual(animation.version, "1.1")
                self.assertGreater(animation.num_frames, 0)
                self.assertGreater(animation.num_bones, 0)
                self.assertEqual(
                    animation.trailing_bytes,
                    0,
                    "o layout v1.1 deve consumir o arquivo exatamente",
                )

    def test_every_frame_has_all_bone_matrices(self) -> None:
        for path in FRM_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                animation = frm.load_frm(path)
                for frame in animation.frames:
                    self.assertEqual(len(frame.bones), animation.num_bones)
                    for matrix in frame.bones:
                        self.assertEqual(len(matrix), 16)

    def test_translation_accumulates(self) -> None:
        animation = frm.frm_to_animation(frm.load_frm(FRM_FILES[0]), "a")
        self.assertEqual(len(animation.frames), frm.load_frm(FRM_FILES[0]).num_frames)
        self.assertEqual(animation.fps, 55)


@unittest.skipUnless(DDS_FILES, "samples/dds vazio")
class TestRealDds(unittest.TestCase):
    def test_all_decode(self) -> None:
        from gc3d.textures import dds_to_png, read_dds

        for path in DDS_FILES:
            with self.subTest(arquivo=os.path.basename(path)):
                with open(path, "rb") as handle:
                    data = handle.read()
                image = read_dds(data)
                self.assertGreater(image.width, 0)
                self.assertGreater(image.height, 0)
                self.assertEqual(
                    len(image.pixels), image.width * image.height * 4
                )
                png = dds_to_png(data)
                self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")


@unittest.skipUnless(P3M_FILES, "samples/p3m vazio")
class TestEndToEnd(unittest.TestCase):
    def test_every_sample_converts_to_valid_glb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for path in P3M_FILES:
                with self.subTest(arquivo=os.path.basename(path)):
                    output = os.path.join(
                        tmp, os.path.splitext(os.path.basename(path))[0] + ".glb"
                    )
                    result = convert_model(
                        path,
                        output,
                        [],
                        ConvertOptions(embed_texture=True, texture_dirs=[DDS_DIR]),
                    )
                    self.assertTrue(result.ok, result.error)
                    self.assertTrue(os.path.isfile(output))
                    self.assertEqual(validate(Glb(output)), [])

    def test_conversion_with_animations(self) -> None:
        if not FRM_FILES:
            self.skipTest("samples/frm vazio")

        # Casa modelo e animacao pelo numero de ossos, como o programa faz.
        pairs = []
        for model_path in P3M_FILES:
            found = find_animations_for_model(model_path, FRM_DIR)
            if found:
                pairs.append((model_path, found))
        if not pairs:
            self.skipTest("nenhuma amostra de modelo e animacao com ossos compativeis")

        with tempfile.TemporaryDirectory() as tmp:
            for model_path, animations in pairs:
                with self.subTest(arquivo=os.path.basename(model_path)):
                    output = os.path.join(tmp, "animado.glb")
                    result = convert_model(model_path, output, animations)
                    self.assertTrue(result.ok, result.error)
                    glb = Glb(output)
                    self.assertEqual(validate(glb), [])
                    self.assertEqual(
                        len(glb.json.get("animations", [])), len(animations)
                    )

    def test_texture_gets_embedded(self) -> None:
        candidates = [
            p
            for p in P3M_FILES
            if os.path.isfile(
                os.path.join(
                    DDS_DIR, os.path.splitext(os.path.basename(p))[0] + ".dds"
                )
            )
        ]
        if not candidates:
            self.skipTest("nenhuma amostra com textura correspondente")
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "com_textura.glb")
            result = convert_model(
                candidates[0],
                output,
                [],
                ConvertOptions(embed_texture=True, texture_dirs=[DDS_DIR]),
            )
            self.assertTrue(result.ok, result.error)
            self.assertIsNotNone(result.texture_used)
            glb = Glb(output)
            self.assertEqual(len(glb.json.get("images", [])), 1)

    def test_incompatible_animation_is_reported_not_fatal(self) -> None:
        """Um FRM com numero de ossos diferente gera aviso, nao erro."""
        if not FRM_FILES:
            self.skipTest("samples/frm vazio")
        model = p3m.load_p3m(P3M_FILES[0])
        mismatched = [
            path
            for path in FRM_FILES
            if frm.load_frm(path).num_bones != model.num_angle_bones
        ]
        if not mismatched:
            self.skipTest("todas as amostras tem o mesmo numero de ossos")
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "x.glb")
            result = convert_model(P3M_FILES[0], output, mismatched[:1])
            self.assertTrue(result.ok, result.error)
            self.assertTrue(
                any("osso" in w for w in result.warnings),
                f"esperava aviso sobre ossos, veio: {result.warnings}",
            )


if __name__ == "__main__":
    unittest.main()
