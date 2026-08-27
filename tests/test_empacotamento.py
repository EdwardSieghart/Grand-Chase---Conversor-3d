"""Testes do empacotamento das pastas de distribuicao.

O que importa verificar aqui nao e a estetica da pasta, e sim que ela **funciona
sozinha**: o `app/` copiado precisa converter arquivos sem depender do repositorio,
e os lancadores precisam ter a logica de encontrar o executavel ou o Python.

Um pacote que monta bonito mas nao roda e pior que nenhum pacote.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

from . import PROJECT_ROOT

EMPACOTAR = os.path.join(PROJECT_ROOT, "build", "empacotar.py")
SAMPLES_P3M = os.path.join(PROJECT_ROOT, "samples", "p3m")


def load_packager():
    spec = importlib.util.spec_from_file_location("empacotar", EMPACOTAR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.path.isfile(EMPACOTAR), "build/empacotar.py ausente")
class TestPackagerPieces(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packager = load_packager()

    def test_reads_version_from_source(self) -> None:
        from gc3d import __version__

        self.assertEqual(self.packager.read_version(), __version__)

    def test_linux_launcher_tries_binary_then_python(self) -> None:
        script = self.packager.LINUX_GUI_LAUNCHER
        self.assertIn("./gc3d-gui", script)
        self.assertIn("app/gc3d_gui.py", script)
        # A ordem importa: o binario primeiro, porque nao exige Python.
        self.assertLess(script.index("./gc3d-gui"), script.index("app/gc3d_gui.py"))

    def test_windows_launcher_survives_missing_where(self) -> None:
        """`where` nao existe em todo ambiente; tem de haver plano B.

        Foi exatamente isso que o teste sob Wine expos: sem `where`, a versao
        anterior do lancador dizia que nao havia Python mesmo havendo.
        """
        script = self.packager.WINDOWS_GUI_LAUNCHER
        self.assertIn("where python", script)
        self.assertIn("python --version", script)

    def test_windows_launcher_prefers_exe(self) -> None:
        script = self.packager.WINDOWS_GUI_LAUNCHER
        self.assertIn("gc3d-gui.exe", script)
        self.assertLess(
            script.index("gc3d-gui.exe"), script.index("app\\gc3d_gui.py")
        )

    def test_readme_mentions_the_launcher_of_each_platform(self) -> None:
        self.assertIn("Converter.sh", self.packager.readme_text("linux", True))
        self.assertIn("Converter.bat", self.packager.readme_text("windows", True))

    def test_readme_says_whether_binary_is_included(self) -> None:
        com = self.packager.readme_text("linux", True)
        sem = self.packager.readme_text("linux", False)
        self.assertIn("inclui os executaveis", com)
        self.assertIn("NAO inclui executaveis", sem)

    def test_readme_warns_about_55_fps(self) -> None:
        """O FPS e a pegadinha que mais atrapalha quem usa no Blender."""
        for platform in ("linux", "windows"):
            with self.subTest(so=platform):
                self.assertIn("55", self.packager.readme_text(platform, True))


@unittest.skipUnless(os.path.isfile(EMPACOTAR), "build/empacotar.py ausente")
class TestPackagedAppRuns(unittest.TestCase):
    """O `app/` copiado tem de funcionar fora do repositorio."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.target = os.path.join(cls.tmp.name, "pacote")
        os.makedirs(cls.target)
        packager = load_packager()
        packager.copy_app(cls.target)
        cls.cli = os.path.join(cls.target, "app", "gc3d_cli.py")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_app_has_the_expected_files(self) -> None:
        for relative in (
            "app/gc3d_cli.py",
            "app/gc3d_gui.py",
            "app/src/gc3d/__init__.py",
            "app/src/gc3d/convert.py",
            "app/src/gc3d/formats/p3m.py",
            "app/src/gc3d/formats/gltf_in.py",
            "app/src/gc3d/textures.py",
        ):
            with self.subTest(arquivo=relative):
                self.assertTrue(
                    os.path.isfile(os.path.join(self.target, relative)), relative
                )

    def test_no_pycache_copied(self) -> None:
        """A copia nao deve levar `__pycache__` do repositorio.

        Faz a sua propria copia limpa de proposito: os outros testes desta classe
        executam o CLI a partir do pacote, e isso **gera** `__pycache__` ali. Medir
        a pasta compartilhada testaria o efeito dos vizinhos, nao a copia.
        """
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "limpo")
            os.makedirs(target)
            load_packager().copy_app(target)
            for root, dirs, _ in os.walk(target):
                self.assertNotIn("__pycache__", dirs, f"em {root}")

    def test_cli_runs_from_the_package(self) -> None:
        result = subprocess.run(
            [sys.executable, self.cli, "--version"],
            capture_output=True,
            text=True,
            cwd=self.tmp.name,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gc3d", result.stdout)

    @unittest.skipUnless(os.path.isdir(SAMPLES_P3M), "samples/p3m ausente")
    def test_conversion_works_from_the_package(self) -> None:
        """A prova real: converter usando so o que esta na pasta empacotada."""
        model = next(
            os.path.join(SAMPLES_P3M, name)
            for name in sorted(os.listdir(SAMPLES_P3M))
            if name.lower().endswith(".p3m")
        )
        with tempfile.TemporaryDirectory() as out:
            forward = subprocess.run(
                [sys.executable, self.cli, "convert", model, "-o", out, "--no-texture"],
                capture_output=True,
                text=True,
                cwd=self.tmp.name,
            )
            self.assertEqual(forward.returncode, 0, forward.stderr)
            produced = [n for n in os.listdir(out) if n.endswith(".glb")]
            self.assertEqual(len(produced), 1)

            # E a volta tambem, que e onde estao os escritores.
            back = os.path.join(out, "volta")
            backward = subprocess.run(
                [
                    sys.executable,
                    self.cli,
                    "convert",
                    os.path.join(out, produced[0]),
                    "-o",
                    back,
                ],
                capture_output=True,
                text=True,
                cwd=self.tmp.name,
            )
            self.assertEqual(backward.returncode, 0, backward.stderr)
            self.assertTrue(
                any(n.endswith(".p3m") for n in os.listdir(back)),
                f"nenhum .p3m gerado: {os.listdir(back)}",
            )


if __name__ == "__main__":
    unittest.main()
