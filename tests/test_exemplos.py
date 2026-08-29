"""Testes do zip de exemplos que acompanha a Release.

O que importa aqui nao e a estetica do zip, e sim que ele **sirva ao primeiro
teste do usuario**: os arquivos dentro precisam converter de verdade, e as
texturas precisam casar com os modelos escolhidos. Um zip de exemplos cujo
primeiro comando falha e pior que nenhum zip.

Substitui os testes do antigo `build/empacotar.py`, que verificava pastas por
sistema e lancadores `Converter.sh`/`Converter.bat`. Aquilo existia porque havia
dois executaveis e um modo de reserva rodando pelo Python; com um executavel
unico por sistema, nada daquilo tem mais o que testar.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from . import PROJECT_ROOT

EXEMPLOS = os.path.join(PROJECT_ROOT, "build", "exemplos.py")
SAMPLES = os.path.join(PROJECT_ROOT, "samples")
APP = os.path.join(PROJECT_ROOT, "gc3d_app.py")


def carregar_modulo():
    spec = importlib.util.spec_from_file_location("exemplos", EXEMPLOS)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@unittest.skipUnless(os.path.isfile(EXEMPLOS), "build/exemplos.py ausente")
class TestPecas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modulo = carregar_modulo()

    def test_le_a_versao_do_codigo(self) -> None:
        from gc3d import __version__

        self.assertEqual(self.modulo.ler_versao(), __version__)

    @unittest.skipUnless(os.path.isdir(SAMPLES), "samples/ ausente")
    def test_escolhe_modelos_e_animacao(self) -> None:
        nomes = [nome for _caminho, nome in self.modulo.escolher_exemplos()]
        self.assertEqual(sum(1 for n in nomes if n.endswith(".p3m")), 2)
        self.assertEqual(sum(1 for n in nomes if n.endswith(".frm")), 1)

    @unittest.skipUnless(os.path.isdir(SAMPLES), "samples/ ausente")
    def test_as_texturas_casam_com_os_modelos(self) -> None:
        """A regra que faz o primeiro teste do usuario sair com cor.

        As texturas nao sao escolhidas por contagem: o conversor acha a textura
        sozinho quando ela tem o mesmo nome do modelo. Um .dds de outro
        personagem seria peso morto, e a ausencia da textura certa faria o
        modelo aparecer sem cor no Blender, parecendo defeito do conversor.
        """
        nomes = [nome for _caminho, nome in self.modulo.escolher_exemplos()]
        modelos = {os.path.splitext(n)[0] for n in nomes if n.endswith(".p3m")}
        texturas = {os.path.splitext(n)[0] for n in nomes if n.endswith(".dds")}
        self.assertTrue(texturas, "nenhuma textura foi incluida")
        self.assertTrue(
            texturas <= modelos,
            f"texturas sem modelo correspondente: {texturas - modelos}",
        )

    @unittest.skipUnless(os.path.isdir(SAMPLES), "samples/ ausente")
    def test_nomes_no_zip_sao_planos(self) -> None:
        """Sem 'samples/p3m/' na frente: o usuario descompacta e ve os arquivos."""
        for _caminho, nome in self.modulo.escolher_exemplos():
            with self.subTest(nome=nome):
                self.assertNotIn("/", nome)
                self.assertNotIn("\\", nome)


@unittest.skipUnless(os.path.isfile(EXEMPLOS), "build/exemplos.py ausente")
class TestLeiaMe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modulo = carregar_modulo()
        cls.texto = cls.modulo.texto_leia_me("9.9.9", ["abta000.p3m", "abta000.dds"])

    def test_diz_a_versao(self) -> None:
        self.assertIn("9.9.9", self.texto)

    def test_deixa_claro_que_o_programa_nao_esta_aqui(self) -> None:
        """O zip so tem arquivos de teste; confundir isso gera 'nao abre'."""
        self.assertIn("NAO contem o programa", self.texto)

    def test_aponta_o_arquivo_de_cada_sistema(self) -> None:
        self.assertIn("GrandChase3D-9.9.9.exe", self.texto)
        self.assertIn("GrandChase3D-9.9.9-x86_64.AppImage", self.texto)

    def test_avisa_dos_55_quadros(self) -> None:
        """O FPS e a pegadinha que mais atrapalha quem usa no Blender."""
        self.assertIn("55", self.texto)

    def test_explica_onde_ficam_as_configuracoes(self) -> None:
        self.assertIn("gc3d.ini", self.texto)
        self.assertIn("config", self.texto)

    def test_lista_os_arquivos_que_recebeu(self) -> None:
        self.assertIn("abta000.p3m", self.texto)
        self.assertIn("abta000.dds", self.texto)


@unittest.skipUnless(os.path.isfile(EXEMPLOS), "build/exemplos.py ausente")
@unittest.skipUnless(os.path.isdir(SAMPLES), "samples/ ausente")
class TestZipGerado(unittest.TestCase):
    """Monta o zip de verdade, num destino temporario."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.modulo = carregar_modulo()
        cls.tmp = tempfile.TemporaryDirectory()
        # Redireciona a saida para nao sujar release/ do repositorio ao testar.
        with mock.patch.object(cls.modulo, "RELEASE_DIR", cls.tmp.name):
            with mock.patch("builtins.print"):
                codigo = cls.modulo.main()
        assert codigo == 0, f"main() devolveu {codigo}"
        zips = [n for n in os.listdir(cls.tmp.name) if n.endswith(".zip")]
        assert len(zips) == 1, zips
        cls.caminho = os.path.join(cls.tmp.name, zips[0])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_nome_traz_a_versao(self) -> None:
        from gc3d import __version__

        self.assertIn(__version__, os.path.basename(self.caminho))

    def test_tem_leia_me_e_licenca(self) -> None:
        with zipfile.ZipFile(self.caminho) as zip_lido:
            nomes = zip_lido.namelist()
        self.assertIn("LEIA-ME.txt", nomes)
        self.assertIn("LICENSE", nomes)

    def test_continua_pequeno(self) -> None:
        """Trava contra o zip virar um repositorio de assets com o tempo."""
        tamanho = os.path.getsize(self.caminho)
        self.assertLess(
            tamanho,
            2 * 1024 * 1024,
            f"o zip de exemplos cresceu para {tamanho / 1024:.0f} KB",
        )

    def test_o_zip_nao_tem_nada_inesperado(self) -> None:
        permitidos = (".p3m", ".frm", ".dds")
        with zipfile.ZipFile(self.caminho) as zip_lido:
            for nome in zip_lido.namelist():
                if nome in ("LEIA-ME.txt", "LICENSE"):
                    continue
                with self.subTest(nome=nome):
                    self.assertTrue(
                        nome.lower().endswith(permitidos),
                        f"arquivo inesperado no zip: {nome}",
                    )

    def test_os_exemplos_convertem_de_verdade(self) -> None:
        """A prova real: descompacta e converte, como o usuario faria.

        Se este teste falhar, o primeiro comando do LEIA-ME nao funciona — que e
        o unico motivo de o zip existir.
        """
        with tempfile.TemporaryDirectory() as area:
            with zipfile.ZipFile(self.caminho) as zip_lido:
                zip_lido.extractall(area)

            modelo = next(
                n for n in sorted(os.listdir(area)) if n.lower().endswith(".p3m")
            )
            saida = os.path.join(area, "saida")

            ida = subprocess.run(
                [sys.executable, APP, "convert", os.path.join(area, modelo),
                 "-o", saida],
                capture_output=True,
                text=True,
                cwd=area,
            )
            self.assertEqual(ida.returncode, 0, ida.stderr)
            glbs = [n for n in os.listdir(saida) if n.endswith(".glb")]
            self.assertEqual(len(glbs), 1, f"esperava um .glb, veio {glbs}")

            # E a volta, que e onde ficam os escritores dos formatos do jogo.
            volta = os.path.join(area, "volta")
            retorno = subprocess.run(
                [sys.executable, APP, "convert", os.path.join(saida, glbs[0]),
                 "-o", volta],
                capture_output=True,
                text=True,
                cwd=area,
            )
            self.assertEqual(retorno.returncode, 0, retorno.stderr)
            produzidos = os.listdir(volta)
            self.assertTrue(
                any(n.endswith(".p3m") for n in produzidos),
                f"nenhum .p3m gerado: {produzidos}",
            )
            # A textura tem de voltar em DDS, que e o formato que o jogo le, e so
            # aparece porque o .dds certo estava no zip.
            self.assertTrue(
                any(n.endswith(".dds") for n in produzidos),
                f"nenhuma textura .dds gerada: {produzidos}",
            )


if __name__ == "__main__":
    unittest.main()
