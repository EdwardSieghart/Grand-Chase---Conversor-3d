"""Testes das preferencias em gc3d.ini e da escolha de onde grava-lo."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from gc3d import settings as settings_module
from gc3d.settings import CONFIG_NAME, Settings, config_path, executable_dir, fallback_dir


class TestLerEGravar(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="gc3d-prefs-")
        self.path = os.path.join(self.dir, CONFIG_NAME)

    def test_arquivo_ausente_da_os_padroes(self) -> None:
        prefs = Settings.load(self.path)
        self.assertEqual(prefs.pasta_saida, "")
        self.assertTrue(prefs.incluir_textura)
        self.assertTrue(prefs.juntar_tudo)

    def test_ida_e_volta(self) -> None:
        prefs = Settings.load(self.path)
        prefs.pasta_saida = os.path.join(self.dir, "saida")
        prefs.ultima_pasta_aberta = self.dir
        prefs.incluir_textura = False
        prefs.juntar_tudo = False
        prefs.janela = "1024x768"
        self.assertTrue(prefs.save())

        lido = Settings.load(self.path)
        self.assertEqual(lido.pasta_saida, prefs.pasta_saida)
        self.assertEqual(lido.ultima_pasta_aberta, self.dir)
        self.assertFalse(lido.incluir_textura)
        self.assertFalse(lido.juntar_tudo)
        self.assertEqual(lido.janela, "1024x768")

    def test_grava_em_portugues_e_le_de_volta(self) -> None:
        """O INI e para o usuario abrir e editar, entao diz sim e nao."""
        prefs = Settings.load(self.path)
        prefs.incluir_textura = True
        prefs.juntar_tudo = False
        prefs.save()

        with open(self.path, encoding="utf-8") as handle:
            texto = handle.read()
        self.assertIn("incluir_textura = sim", texto)
        self.assertIn("juntar_tudo = nao", texto)
        # E o leitor precisa entender o que o escritor produziu. Esta dupla ja
        # falhou: o configparser so aceita yes/no/true/false por padrao.
        self.assertTrue(Settings.load(self.path).incluir_textura)
        self.assertFalse(Settings.load(self.path).juntar_tudo)

    def test_aceita_true_false_de_quem_editou_a_mao(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[gc3d]\nincluir_textura = false\njuntar_tudo = true\n")
        prefs = Settings.load(self.path)
        self.assertFalse(prefs.incluir_textura)
        self.assertTrue(prefs.juntar_tudo)

    def test_caminho_de_windows_com_porcento_sobrevive(self) -> None:
        """Motivo do RawConfigParser: '%' e escape de interpolacao."""
        esperado = r"C:\Users\%USERNAME%\Documents\saida"
        prefs = Settings.load(self.path)
        prefs.pasta_saida = esperado
        prefs.save()
        self.assertEqual(Settings.load(self.path).pasta_saida, esperado)

    def test_arquivo_corrompido_nao_impede_de_abrir(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("isto nao e um INI {{{ \x00 lixo\n")
        prefs = Settings.load(self.path)
        self.assertTrue(prefs.incluir_textura)

    def test_valor_invalido_cai_no_padrao_sem_derrubar(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[gc3d]\nincluir_textura = talvez\n")
        self.assertTrue(Settings.load(self.path).incluir_textura)

    def test_secao_errada_cai_no_padrao(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[outra]\nincluir_textura = nao\n")
        self.assertTrue(Settings.load(self.path).incluir_textura)

    def test_save_em_pasta_inexistente_cria_o_caminho(self) -> None:
        alvo = os.path.join(self.dir, "a", "b", CONFIG_NAME)
        prefs = Settings.load(alvo)
        self.assertTrue(prefs.save())
        self.assertTrue(os.path.isfile(alvo))

    def test_save_devolve_falso_em_vez_de_estourar(self) -> None:
        """Preferencia perdida e aborrecimento; excecao e defeito."""
        prefs = Settings(path=os.path.join(self.dir, CONFIG_NAME))
        with mock.patch("builtins.open", side_effect=OSError("disco cheio")):
            self.assertFalse(prefs.save())


class TestOndeFicaOArquivo(unittest.TestCase):
    """A parte que sempre morde: qual pasta e a 'pasta do executavel'."""

    def test_appimage_ganha_de_sys_executable(self) -> None:
        """Num AppImage, sys.executable aponta para um /tmp somente leitura."""
        with tempfile.TemporaryDirectory() as pasta:
            appimage = os.path.join(pasta, "GrandChase3D.AppImage")
            with mock.patch.dict(os.environ, {"APPIMAGE": appimage}), mock.patch.object(
                sys, "executable", "/tmp/.mount_abc123/usr/bin/gc3d"
            ), mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(executable_dir(), pasta)

    def test_empacotado_usa_sys_executable(self) -> None:
        """E nao __file__, que aponta para a pasta temporaria de extracao."""
        with tempfile.TemporaryDirectory() as pasta:
            binario = os.path.join(pasta, "gc3d.exe")
            ambiente = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
            with mock.patch.dict(os.environ, ambiente, clear=True), mock.patch.object(
                sys, "executable", binario
            ), mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(executable_dir(), pasta)

    def test_pelo_codigo_fonte_usa_a_raiz_do_projeto(self) -> None:
        ambiente = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
        with mock.patch.dict(os.environ, ambiente, clear=True):
            raiz = executable_dir()
        self.assertTrue(os.path.isdir(os.path.join(raiz, "src", "gc3d")))

    def test_pasta_travada_cai_na_config_do_sistema(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("root escreve em pasta somente leitura")
        with tempfile.TemporaryDirectory() as travada, tempfile.TemporaryDirectory() as casa:
            os.chmod(travada, stat.S_IRUSR | stat.S_IXUSR)
            try:
                with mock.patch.object(
                    settings_module, "executable_dir", return_value=travada
                ), mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": casa}):
                    destino = config_path()
                self.assertTrue(destino.startswith(casa))
                self.assertEqual(os.path.basename(destino), CONFIG_NAME)
            finally:
                os.chmod(travada, stat.S_IRWXU)

    def test_ini_existente_ao_lado_ganha_mesmo_sem_escrita(self) -> None:
        """Programa levado num pendrive travado ainda respeita o INI que veio."""
        if os.geteuid() == 0:
            self.skipTest("root escreve em pasta somente leitura")
        with tempfile.TemporaryDirectory() as pasta:
            ini = os.path.join(pasta, CONFIG_NAME)
            with open(ini, "w", encoding="utf-8") as handle:
                handle.write("[gc3d]\npasta_saida = /tmp/veio-do-pendrive\n")
            os.chmod(pasta, stat.S_IRUSR | stat.S_IXUSR)
            try:
                with mock.patch.object(
                    settings_module, "executable_dir", return_value=pasta
                ):
                    self.assertEqual(config_path(), ini)
                    self.assertEqual(
                        Settings.load().pasta_saida, "/tmp/veio-do-pendrive"
                    )
            finally:
                os.chmod(pasta, stat.S_IRWXU)

    def test_pasta_de_reserva_por_sistema(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/cfg"}):
            if sys.platform != "win32":
                self.assertEqual(fallback_dir(), os.path.join("/tmp/cfg", "gc3d"))


class TestGravacaoNaInterface(unittest.TestCase):
    """Trava a regressao: preferencia mudada tem de chegar ao disco na hora.

    Gravar so no fechamento perdia tudo quando a janela era destruida sem
    `WM_DELETE_WINDOW` — sessao encerrada, gerenciador de janelas matando o
    processo, ou o proprio `xdotool windowclose`, que foi como o defeito
    apareceu. Aqui a janela e destruida DE PROPOSITO pelo caminho ruim.

    Precisa de tela: sem DISPLAY o teste e pulado, como o resto da suite faz.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise unittest.SkipTest("sem tela disponivel")
        try:
            import tkinter
        except ImportError as error:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter ausente: {error}")
        try:
            raiz = tkinter.Tk()
        except Exception as error:  # noqa: BLE001
            raise unittest.SkipTest(f"nao foi possivel abrir janela: {error}")
        raiz.destroy()

        import importlib.util

        raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "gc3d_gui_para_prefs", os.path.join(raiz_projeto, "gc3d_gui.py")
        )
        assert spec and spec.loader
        modulo = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(modulo)
        except Exception as error:  # noqa: BLE001
            raise unittest.SkipTest(f"nao foi possivel carregar a GUI: {error}")
        cls.gui = modulo

    def test_mudanca_chega_ao_disco_sem_fechar_a_janela(self) -> None:
        import tkinter

        pasta = tempfile.mkdtemp(prefix="gc3d-prefs-gui-")
        ini = os.path.join(pasta, CONFIG_NAME)

        raiz = tkinter.Tk()
        raiz.withdraw()
        try:
            app = self.gui.ConverterApp(raiz, settings=Settings(path=ini))
            raiz.update()
            self.assertFalse(os.path.isfile(ini), "nada devia estar gravado ainda")

            app.with_texture.set(False)
            app.output_dir.set(os.path.join(pasta, "escolhida"))
            app._save_settings_soon()

            # Espera o adiamento de 800 ms passar, mantendo a interface viva.
            fim = []
            raiz.after(1400, lambda: fim.append(True))
            while not fim:
                raiz.update()
                raiz.after(20)

            self.assertTrue(os.path.isfile(ini), "a mudanca nao foi gravada")
        finally:
            # Destroi pelo caminho RUIM, sem passar pelo _on_close.
            raiz.destroy()

        lido = Settings.load(ini)
        self.assertEqual(lido.pasta_saida, os.path.join(pasta, "escolhida"))
        self.assertFalse(lido.incluir_textura)


if __name__ == "__main__":
    unittest.main()
