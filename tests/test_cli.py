"""Testes da interface de linha de comando.

Chama o `gc3d_cli.py` como o usuario chamaria, em um subprocesso, para pegar
problemas que os testes de biblioteca nao pegam: erro de import, argumento com
nome errado, codigo de saida trocado.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

from . import PROJECT_ROOT

CLI = os.path.join(PROJECT_ROOT, "gc3d_cli.py")
SAMPLES_P3M = os.path.join(PROJECT_ROOT, "samples", "p3m")
SAMPLES_FRM = os.path.join(PROJECT_ROOT, "samples", "frm")
SAMPLES_DDS = os.path.join(PROJECT_ROOT, "samples", "dds")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, CLI, *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def first_sample(directory: str, extension: str) -> str | None:
    if not os.path.isdir(directory):
        return None
    names = sorted(n for n in os.listdir(directory) if n.lower().endswith(extension))
    return os.path.join(directory, names[0]) if names else None


class TestCliBasics(unittest.TestCase):
    def test_help_works(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("convert", result.stdout)
        self.assertIn("batch", result.stdout)
        self.assertIn("info", result.stdout)

    def test_version_works(self) -> None:
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gc3d", result.stdout)

    def test_missing_subcommand_fails(self) -> None:
        self.assertNotEqual(run_cli().returncode, 0)


@unittest.skipUnless(os.path.isdir(SAMPLES_P3M), "samples/p3m ausente")
class TestCliConvert(unittest.TestCase):
    def setUp(self) -> None:
        self.model = first_sample(SAMPLES_P3M, ".p3m")
        if not self.model:
            self.skipTest("nenhuma amostra .p3m")

    def test_info_on_model(self) -> None:
        result = run_cli("info", self.model)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P3M v0.5", result.stdout)
        self.assertIn("angle bones", result.stdout)

    def test_info_on_animation(self) -> None:
        animation = first_sample(SAMPLES_FRM, ".frm")
        if not animation:
            self.skipTest("nenhuma amostra .frm")
        result = run_cli("info", animation)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FRM v1.1", result.stdout)

    def test_info_on_bad_file_returns_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "ruim.p3m")
            with open(bad, "wb") as handle:
                handle.write(b"nao e um p3m")
            result = run_cli("info", bad)
            self.assertNotEqual(result.returncode, 0)

    def test_convert_to_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("convert", self.model, "-o", tmp, "--no-texture")
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = os.path.splitext(os.path.basename(self.model))[0] + ".glb"
            self.assertIn(expected, os.listdir(tmp))

    def test_convert_to_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "saida_customizada.glb")
            result = run_cli("convert", self.model, "-o", target, "--no-texture")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.isfile(target))

    def test_convert_with_texture_dir(self) -> None:
        if not os.path.isdir(SAMPLES_DDS):
            self.skipTest("samples/dds ausente")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(
                "convert", self.model, "-o", tmp, "--texture-dir", SAMPLES_DDS, "-v"
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_convert_with_anim_dir(self) -> None:
        if not os.path.isdir(SAMPLES_FRM):
            self.skipTest("samples/frm ausente")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(
                "convert", self.model, "-o", tmp, "--anim-dir", SAMPLES_FRM, "--no-texture"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("compativel", result.stdout)

    def test_convert_nonexistent_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("convert", os.path.join(tmp, "nao_existe.p3m"), "-o", tmp)
            self.assertNotEqual(result.returncode, 0)


@unittest.skipUnless(os.path.isdir(SAMPLES_P3M), "samples/p3m ausente")
class TestCliBatch(unittest.TestCase):
    def test_batch_converts_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("batch", SAMPLES_P3M, "-o", tmp, "--no-texture")
            self.assertEqual(result.returncode, 0, result.stderr)
            produced = [n for n in os.listdir(tmp) if n.endswith(".glb")]
            expected = [n for n in os.listdir(SAMPLES_P3M) if n.endswith(".p3m")]
            self.assertEqual(len(produced), len(expected))
            self.assertIn("concluido", result.stdout)

    def test_batch_requires_output(self) -> None:
        self.assertNotEqual(run_cli("batch", SAMPLES_P3M).returncode, 0)

    def test_batch_on_empty_folder_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as out:
            result = run_cli("batch", empty, "-o", out)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nenhum arquivo", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
