"""Testes do despacho do executavel unico entre interface e linha de comando."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import gc3d_app


class TestQuemAtende(unittest.TestCase):
    def test_sem_argumentos_e_a_interface(self) -> None:
        self.assertFalse(gc3d_app.wants_cli([]))

    def test_subcomandos_sao_linha_de_comando(self) -> None:
        for comando in ("convert", "batch", "info", "config"):
            with self.subTest(comando=comando):
                self.assertTrue(gc3d_app.wants_cli([comando, "a.p3m"]))

    def test_opcoes_sao_linha_de_comando(self) -> None:
        for opcao in ("--version", "--help", "-h"):
            with self.subTest(opcao=opcao):
                self.assertTrue(gc3d_app.wants_cli([opcao]))

    def test_arquivos_soltos_abrem_a_interface(self) -> None:
        """Arrastar arquivos sobre o icone entrega caminhos como argumentos.

        Quem faz isso quer a janela. Nao ha ambiguidade porque a linha de comando
        sempre exige um subcomando antes dos caminhos.
        """
        self.assertFalse(gc3d_app.wants_cli(["abta000.p3m"]))
        self.assertFalse(gc3d_app.wants_cli(["a.p3m", "b.frm", "c.glb"]))
        self.assertFalse(
            gc3d_app.wants_cli([r"C:\Users\eu\Grand Chase\modelo.p3m"])
        )

    def test_subcomando_desconhecido_vai_para_a_interface(self) -> None:
        """Melhor abrir a janela do que uma mensagem de erro de argparse."""
        self.assertFalse(gc3d_app.wants_cli(["converter"]))


class TestDespacho(unittest.TestCase):
    def test_sem_argumentos_chama_a_interface_sem_precarga(self) -> None:
        with mock.patch.object(gc3d_app, "run_gui", return_value=0) as gui:
            self.assertEqual(gc3d_app.main([]), 0)
        gui.assert_called_once_with([])

    def test_caminhos_viram_precarga_da_interface(self) -> None:
        with mock.patch.object(gc3d_app, "run_gui", return_value=0) as gui:
            gc3d_app.main(["a.p3m", "b.frm"])
        gui.assert_called_once_with(["a.p3m", "b.frm"])

    def test_subcomando_vai_para_a_linha_de_comando(self) -> None:
        with mock.patch.object(gc3d_app, "run_cli", return_value=3) as cli:
            self.assertEqual(gc3d_app.main(["info", "a.p3m"]), 3)
        cli.assert_called_once_with(["info", "a.p3m"])

    def test_codigo_de_saida_da_linha_de_comando_e_repassado(self) -> None:
        """O .exe precisa devolver o codigo certo para scripts e para o CI."""
        with mock.patch.object(gc3d_app, "attach_console", return_value=True):
            with mock.patch("gc3d_cli.main", return_value=1) as cli:
                self.assertEqual(gc3d_app.main(["info", "inexistente.p3m"]), 1)
        cli.assert_called_once()


class TestConsole(unittest.TestCase):
    def test_fora_do_windows_nao_faz_nada(self) -> None:
        if sys.platform == "win32":
            self.skipTest("especifico de nao-Windows")
        self.assertTrue(gc3d_app.attach_console())

    def test_no_windows_sem_empacotar_nao_faz_nada(self) -> None:
        """Rodando por 'python gc3d_app.py' o console ja e do processo."""
        with mock.patch.object(sys, "platform", "win32"):
            # sys.frozen ausente = nao empacotado
            if hasattr(sys, "frozen"):
                self.skipTest("rodando empacotado")
            self.assertTrue(gc3d_app.attach_console())

    def test_a_versao_sai_pela_linha_de_comando(self) -> None:
        """Teste de fim a fim do caminho que o CI verifica no Windows real."""
        import contextlib
        import io

        from gc3d import __version__

        capturado = io.StringIO()
        with mock.patch.object(gc3d_app, "attach_console", return_value=True):
            with contextlib.redirect_stdout(capturado):
                with self.assertRaises(SystemExit) as saida:
                    gc3d_app.main(["--version"])
        self.assertEqual(saida.exception.code, 0)
        self.assertIn(__version__, capturado.getvalue())

    def test_sem_console_avisa_em_janela_e_devolve_erro(self) -> None:
        """Atalho grafico com argumentos nao pode sumir calado."""
        with mock.patch.object(gc3d_app, "attach_console", return_value=False):
            with mock.patch.object(gc3d_app, "_report_without_console") as aviso:
                self.assertEqual(gc3d_app.main(["info", "a.p3m"]), 1)
        aviso.assert_called_once()


if __name__ == "__main__":
    unittest.main()
