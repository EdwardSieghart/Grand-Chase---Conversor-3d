"""Testes da selecao de animacoes e do parser de arrastar e soltar.

Estas duas coisas dividem um mesmo tema: são o ponto onde a interface traduz o
que o usuario fez em algo que o conversor entende. Erram em silencio se nao forem
testadas — um modelo sai sem animacao nenhuma, ou um caminho com espaco vira dois
caminhos quebrados.
"""

from __future__ import annotations

import importlib.util
import os
import struct
import tempfile
import unittest

from gc3d import AnimationIndex, ConvertOptions, convert_batch

from . import PROJECT_ROOT, SAMPLES_DIR

P3M_DIR = os.path.join(SAMPLES_DIR, "p3m")
FRM_DIR = os.path.join(SAMPLES_DIR, "frm")


def write_frm(path: str, num_frames: int, num_bones: int) -> None:
    """Grava um FRM v1.1 minimo com a contagem de ossos pedida."""
    identity = struct.pack(
        "<16f",
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    )
    data = bytearray(b"Frm Ver 1.1\0")
    data += struct.pack("<HH", num_frames, num_bones)
    for _ in range(num_frames):
        data += struct.pack("<B", 0)
        data += struct.pack("<f", 0.0)
        data += struct.pack("<f", 0.0)
        data += identity * num_bones
    for _ in range(num_frames):
        data += struct.pack("<f", 0.0)
    with open(path, "wb") as handle:
        handle.write(data)


class TestAnimationIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        # Duas animacoes de 15 ossos, uma de 23, e um arquivo corrompido.
        self.a15 = os.path.join(self.dir, "a15.frm")
        self.b15 = os.path.join(self.dir, "b15.frm")
        self.c23 = os.path.join(self.dir, "c23.frm")
        self.bad = os.path.join(self.dir, "ruim.frm")
        write_frm(self.a15, 3, 15)
        write_frm(self.b15, 4, 15)
        write_frm(self.c23, 5, 23)
        with open(self.bad, "wb") as handle:
            handle.write(b"nao e um frm")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_groups_by_bone_count(self) -> None:
        index = AnimationIndex([self.a15, self.b15, self.c23])
        self.assertEqual(index.bone_counts, [15, 23])
        self.assertEqual(len(index.by_bone_count[15]), 2)
        self.assertEqual(len(index.by_bone_count[23]), 1)
        self.assertEqual(len(index), 3)

    def test_unreadable_files_are_reported_not_fatal(self) -> None:
        index = AnimationIndex([self.a15, self.bad])
        self.assertEqual(len(index), 1)
        self.assertEqual(len(index.unreadable), 1)
        self.assertEqual(os.path.basename(index.unreadable[0][0]), "ruim.frm")

    def test_empty_index_selects_nothing_without_warning(self) -> None:
        index = AnimationIndex([])
        chosen, warnings = index.select_for("qualquer.p3m")
        self.assertEqual(chosen, [])
        self.assertEqual(warnings, [])

    @unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
    def test_matches_by_bone_count(self) -> None:
        from gc3d.formats import p3m

        model = os.path.join(P3M_DIR, "abta003.p3m")
        bones = p3m.load_p3m(model).num_angle_bones
        self.assertEqual(bones, 15, "a amostra deveria ter 15 ossos")

        index = AnimationIndex([self.a15, self.b15, self.c23])
        chosen, warnings = index.select_for(model, match_by_bones=True)
        self.assertEqual(len(chosen), 2)
        self.assertEqual(warnings, [])

    @unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
    def test_no_match_explains_why(self) -> None:
        """Sem casamento, o aviso tem de dizer o motivo e a saida.

        Antes disso, o modelo saia sem animacao nenhuma e a causa ficava
        invisivel — parecia que o programa nao suportava varias animacoes.
        """
        model = os.path.join(P3M_DIR, "abta003.p3m")  # 15 ossos
        index = AnimationIndex([self.c23])  # so 23 ossos
        chosen, warnings = index.select_for(model, match_by_bones=True)
        self.assertEqual(chosen, [])
        self.assertEqual(len(warnings), 1)
        mensagem = warnings[0]
        self.assertIn("15", mensagem, "deve dizer quantos ossos o modelo tem")
        self.assertIn("23", mensagem, "deve dizer quantos ossos as animacoes tem")
        self.assertIn("desligue", mensagem, "deve dizer o que fazer")

    @unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
    def test_without_matching_takes_everything(self) -> None:
        model = os.path.join(P3M_DIR, "abta003.p3m")
        index = AnimationIndex([self.a15, self.b15, self.c23])
        chosen, warnings = index.select_for(model, match_by_bones=False)
        self.assertEqual(len(chosen), 3)
        self.assertEqual(warnings, [])

    def test_unreadable_model_warns_instead_of_crashing(self) -> None:
        broken = os.path.join(self.dir, "quebrado.p3m")
        with open(broken, "wb") as handle:
            handle.write(b"nao e um p3m")
        index = AnimationIndex([self.a15])
        chosen, warnings = index.select_for(broken, match_by_bones=True)
        self.assertEqual(chosen, [])
        self.assertEqual(len(warnings), 1)


@unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
class TestMultipleAnimationsInOneGlb(unittest.TestCase):
    """Varias animacoes tem de caber num unico GLB, e todas devem chegar la."""

    def test_all_matching_animations_go_into_one_file(self) -> None:
        import sys

        sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))
        from glb_inspect import Glb, validate

        if not os.path.isdir(FRM_DIR):
            self.skipTest("samples/frm ausente")

        with tempfile.TemporaryDirectory() as tmp:
            # Três animações de 15 ossos, para casar com abta003.
            paths = []
            for i in range(3):
                path = os.path.join(tmp, f"anim{i}.frm")
                write_frm(path, 5 + i, 15)
                paths.append(path)

            model = os.path.join(P3M_DIR, "abta003.p3m")
            results = convert_batch(
                [model],
                tmp,
                ConvertOptions(embed_texture=False),
                animation_paths=paths,
            )
            self.assertTrue(results[0].ok, results[0].error)

            glb = Glb(os.path.join(tmp, "abta003.glb"))
            self.assertEqual(validate(glb), [])
            self.assertEqual(
                len(glb.json.get("animations", [])),
                3,
                "as três animações devem estar no mesmo GLB",
            )

    def test_batch_reads_each_animation_once(self) -> None:
        """O índice evita reler os mesmos .frm para cada modelo."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.frm")
            write_frm(path, 3, 15)

            leituras = {"n": 0}
            from gc3d import convert as convert_module

            original = convert_module.frm_format.load_frm

            def contando(p):  # noqa: ANN001
                leituras["n"] += 1
                return original(p)

            convert_module.frm_format.load_frm = contando
            try:
                models = [
                    os.path.join(P3M_DIR, name)
                    for name in sorted(os.listdir(P3M_DIR))
                    if name.lower().endswith(".p3m")
                ]
                convert_batch(
                    models,
                    tmp,
                    ConvertOptions(embed_texture=False),
                    animation_paths=[path],
                )
            finally:
                convert_module.frm_format.load_frm = original

            # O arquivo deve ser lido uma vez na indexacao, mais uma por modelo
            # que o inclua de fato — nunca uma vez por modelo apenas para
            # descobrir a contagem de ossos.
            self.assertLessEqual(
                leituras["n"],
                1 + len(models),
                f"o .frm foi lido {leituras['n']} vezes para {len(models)} modelos",
            )


class TestDropDataParser(unittest.TestCase):
    """O tkdnd entrega os caminhos como uma lista Tcl, com chaves nos que tem espaco.

    As pastas deste projeto tem espaco no nome ("GRAND CHASE", "Lança Uno.p3m"),
    entao um `split()` ingenuo quebraria justamente o caso comum.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # A GUI importa tkinter no topo; carregamos o modulo direto do arquivo
        # para poder testar o parser sem abrir janela.
        spec = importlib.util.spec_from_file_location(
            "gc3d_gui_para_teste", os.path.join(PROJECT_ROOT, "gc3d_gui.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001
            raise unittest.SkipTest(f"nao foi possivel carregar a GUI: {error}")
        cls.parse = staticmethod(module.ConverterApp._parse_drop_data)

    def test_simple_paths(self) -> None:
        self.assertEqual(
            self.parse("/tmp/a.p3m /tmp/b.frm"), ["/tmp/a.p3m", "/tmp/b.frm"]
        )

    def test_single_path_with_spaces(self) -> None:
        self.assertEqual(
            self.parse("{/run/media/GRAND CHASE/Lança Uno.p3m}"),
            ["/run/media/GRAND CHASE/Lança Uno.p3m"],
        )

    def test_several_paths_with_spaces(self) -> None:
        self.assertEqual(
            self.parse("{/a b/c.p3m} {/d e/f.frm}"), ["/a b/c.p3m", "/d e/f.frm"]
        )

    def test_mixed_quoted_and_bare(self) -> None:
        self.assertEqual(
            self.parse("{/a b/c.p3m} /simples.frm {/x y/z.glb}"),
            ["/a b/c.p3m", "/simples.frm", "/x y/z.glb"],
        )

    def test_empty(self) -> None:
        self.assertEqual(self.parse(""), [])
        self.assertEqual(self.parse("   "), [])

    def test_windows_paths(self) -> None:
        self.assertEqual(
            self.parse(r"{C:\Grand Chase\Models\a.p3m} C:\tmp\b.frm"),
            [r"C:\Grand Chase\Models\a.p3m", r"C:\tmp\b.frm"],
        )

    def test_newline_separated(self) -> None:
        self.assertEqual(
            self.parse("/tmp/a.p3m\n/tmp/b.frm"), ["/tmp/a.p3m", "/tmp/b.frm"]
        )


if __name__ == "__main__":
    unittest.main()
