"""Testes de textura: busca do arquivo, leitura de PNG e escrita de DDS.

O formato de DDS escrito nao foi escolhido por gosto: copia o que o proprio jogo
usa. Medindo as 406 texturas do conjunto de teste, 281 delas ja sao sem compressao
(251 de 24 bits e 30 de 32 bits), com mascaras `R=0xFF0000 G=0xFF00 B=0xFF` — ou
seja, ordem de bytes BGR(A). Escrever nesse formato e sem perda e comprovadamente
lido pelo jogo.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from gc3d.textures import (
    DdsError,
    PngError,
    encode_png,
    image_to_dds,
    png_to_dds,
    read_dds,
    read_png,
    resolve_texture,
    write_dds,
)

from . import SAMPLES_DIR

P3M_DIR = os.path.join(SAMPLES_DIR, "p3m")
DDS_DIR = os.path.join(SAMPLES_DIR, "dds")


def checkerboard(width: int, height: int, alpha: bool = False) -> bytes:
    """Imagem RGBA de teste, opcionalmente com transparencia alternada."""
    out = bytearray()
    for y in range(height):
        for x in range(width):
            light = (x + y) % 2 == 0
            a = 255
            if alpha and not light:
                a = 0
            out += bytes((255 if light else 32, 128, 64, a))
    return bytes(out)


class TestPngDecoder(unittest.TestCase):
    """O decodificador existe para o caminho inverso: o glTF traz PNG embutido."""

    def test_round_trip_with_own_encoder(self) -> None:
        for size in ((1, 1), (2, 3), (4, 4), (17, 5)):
            with self.subTest(tamanho=size):
                pixels = checkerboard(*size)
                image = read_png(encode_png(size[0], size[1], pixels))
                self.assertEqual((image.width, image.height), size)
                self.assertEqual(bytes(image.pixels), pixels)

    def test_alpha_is_preserved(self) -> None:
        pixels = checkerboard(4, 4, alpha=True)
        image = read_png(encode_png(4, 4, pixels))
        self.assertEqual(bytes(image.pixels), pixels)
        self.assertTrue(image.has_alpha)

    def test_opaque_image_reports_no_alpha(self) -> None:
        """`has_alpha` tem de refletir transparencia real, nao o canal.

        Todo PNG que este projeto escreve e RGBA. Se `has_alpha` seguisse o tipo de
        cor, toda textura opaca viraria um DDS de 32 bits sem necessidade.
        """
        image = read_png(encode_png(4, 4, checkerboard(4, 4, alpha=False)))
        self.assertFalse(image.has_alpha)

    def test_rejects_non_png(self) -> None:
        with self.assertRaises(PngError):
            read_png(b"isso nao e um png nem de longe")

    def test_rejects_truncated(self) -> None:
        png = encode_png(4, 4, checkerboard(4, 4))
        with self.assertRaises((PngError, Exception)):
            read_png(png[:20])

    def test_rejects_interlaced(self) -> None:
        """PNG entrelacado nao e suportado, e o erro tem de dizer isso."""
        png = bytearray(encode_png(4, 4, checkerboard(4, 4)))
        # O byte de interlace e o ultimo do IHDR (offset 8+4+4+12 = 28).
        png[28] = 1
        with self.assertRaises(PngError) as ctx:
            read_png(bytes(png))
        self.assertIn("entrelac", str(ctx.exception).lower())


class TestDdsWriter(unittest.TestCase):
    def test_opaque_becomes_24_bit(self) -> None:
        data = write_dds(4, 4, checkerboard(4, 4), None)
        image = read_dds(data)
        self.assertEqual(image.source_format, "RGB24")
        self.assertFalse(image.has_alpha)

    def test_transparent_becomes_32_bit(self) -> None:
        data = write_dds(4, 4, checkerboard(4, 4, alpha=True), None)
        image = read_dds(data)
        self.assertEqual(image.source_format, "RGB32")
        self.assertTrue(image.has_alpha)

    def test_pixels_survive_round_trip(self) -> None:
        for alpha in (False, True):
            with self.subTest(alfa=alpha):
                pixels = checkerboard(8, 8, alpha)
                back = read_dds(write_dds(8, 8, pixels, None))
                self.assertEqual(bytes(back.pixels), pixels)

    def test_header_matches_the_game_format(self) -> None:
        """As mascaras e as flags tem de ser as mesmas dos arquivos do jogo."""
        data = write_dds(4, 4, checkerboard(4, 4), None)
        self.assertEqual(data[:4], b"DDS ")
        self.assertEqual(struct.unpack_from("<I", data, 4)[0], 124)
        height, width = struct.unpack_from("<II", data, 12)
        self.assertEqual((width, height), (4, 4))
        self.assertEqual(struct.unpack_from("<I", data, 28)[0], 0, "sem mipmaps")

        pf_flags = struct.unpack_from("<I", data, 80)[0]
        self.assertEqual(pf_flags, 0x40, "DDPF_RGB, como os 24 bits do jogo")
        bits, r, g, b, a = struct.unpack_from("<5I", data, 88)
        self.assertEqual(bits, 24)
        self.assertEqual((r, g, b, a), (0x00FF0000, 0x0000FF00, 0x000000FF, 0))

    def test_header_with_alpha_matches_the_game(self) -> None:
        data = write_dds(4, 4, checkerboard(4, 4, alpha=True), None)
        pf_flags = struct.unpack_from("<I", data, 80)[0]
        self.assertEqual(pf_flags, 0x41, "DDPF_RGB | DDPF_ALPHAPIXELS")
        bits, r, g, b, a = struct.unpack_from("<5I", data, 88)
        self.assertEqual(bits, 32)
        self.assertEqual((r, g, b, a), (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000))

    def test_body_is_bgr_order(self) -> None:
        """A ordem em memoria e B, G, R — consequencia das mascaras."""
        # Um pixel vermelho puro.
        data = write_dds(1, 1, bytes((255, 0, 0, 255)), False)
        body = data[128:]
        self.assertEqual(body[:3], bytes((0, 0, 255)))

    def test_rejects_wrong_buffer_size(self) -> None:
        with self.assertRaises(ValueError):
            write_dds(4, 4, b"\0" * 10, None)

    def test_png_to_dds(self) -> None:
        pixels = checkerboard(4, 4, alpha=True)
        image = read_dds(png_to_dds(encode_png(4, 4, pixels)))
        self.assertEqual(bytes(image.pixels), pixels)

    def test_image_to_dds_accepts_both(self) -> None:
        pixels = checkerboard(4, 4)
        as_png = encode_png(4, 4, pixels)
        as_dds = write_dds(4, 4, pixels, None)
        for source in (as_png, as_dds):
            with self.subTest():
                self.assertEqual(bytes(read_dds(image_to_dds(source)).pixels), pixels)

    def test_image_to_dds_rejects_unknown(self) -> None:
        with self.assertRaises(DdsError):
            image_to_dds(b"formato desconhecido qualquer coisa aqui")


@unittest.skipUnless(os.path.isdir(DDS_DIR), "samples/dds ausente")
class TestRealTexturesRewrite(unittest.TestCase):
    def _files(self) -> list[str]:
        return [
            os.path.join(DDS_DIR, name)
            for name in sorted(os.listdir(DDS_DIR))
            if name.lower().endswith(".dds")
        ]

    def test_rewriting_is_lossless(self) -> None:
        for path in self._files():
            with self.subTest(arquivo=os.path.basename(path)):
                with open(path, "rb") as handle:
                    original = read_dds(handle.read())
                source = bytes(original.pixels)
                back = read_dds(
                    write_dds(original.width, original.height, source, None)
                )
                self.assertEqual(
                    (back.width, back.height), (original.width, original.height)
                )
                self.assertEqual(bytes(back.pixels), source)

    def test_path_through_png_is_lossless(self) -> None:
        """E o caminho real: a textura chega no glTF como PNG."""
        for path in self._files():
            with self.subTest(arquivo=os.path.basename(path)):
                with open(path, "rb") as handle:
                    original = read_dds(handle.read())
                source = bytes(original.pixels)
                png = encode_png(original.width, original.height, source)
                back = read_dds(png_to_dds(png))
                self.assertEqual(bytes(back.pixels), source)


@unittest.skipUnless(os.path.isdir(P3M_DIR), "samples/p3m ausente")
class TestTextureResolution(unittest.TestCase):
    """A busca do arquivo de textura, com as regras tiradas dos dados reais."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def _model(self, name: str) -> str:
        """Copia uma amostra de P3M com o nome pedido."""
        source = next(
            os.path.join(P3M_DIR, n)
            for n in sorted(os.listdir(P3M_DIR))
            if n.lower().endswith(".p3m")
        )
        target = os.path.join(self.dir, name)
        with open(source, "rb") as origem, open(target, "wb") as destino:
            destino.write(origem.read())
        return target

    def _texture(self, name: str) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(write_dds(2, 2, checkerboard(2, 2), None))
        return path

    def test_exact_name_wins(self) -> None:
        model = self._model("abta999.p3m")
        expected = self._texture("abta999.dds")
        self._texture("abta.dds")
        match = resolve_texture(model, "")
        self.assertIsNotNone(match)
        self.assertEqual(match.path, expected)
        self.assertEqual(match.how, "nome")
        self.assertTrue(match.exact)

    def test_declared_name_wins_over_model_name(self) -> None:
        model = self._model("abta999.p3m")
        self._texture("abta999.dds")
        declared = self._texture("pele_especial.dds")
        match = resolve_texture(model, "pele_especial.dds")
        self.assertEqual(match.path, declared)
        self.assertEqual(match.how, "declarado")

    def test_suffix_is_stripped(self) -> None:
        """`abta93827_m.p3m` usa `abta93827.dds` — caso real do jogo."""
        model = self._model("abta93827_m.p3m")
        expected = self._texture("abta93827.dds")
        match = resolve_texture(model, "")
        self.assertEqual(match.path, expected)
        self.assertEqual(match.how, "sufixo")
        self.assertTrue(match.exact)

    def test_prefix_fallback_is_marked_inexact(self) -> None:
        """`face_04_00.p3m` sem `face_04_00.dds` cai numa variante, avisando.

        Os rostos do jogo tem uma textura por expressao e nem sempre existe a
        `_00`; todas servem a mesma malha, mas escolher uma e um chute.
        """
        model = self._model("face_04_00.p3m")
        self._texture("face_04_hited_01.dds")
        self._texture("face_04_joke_01.dds")
        match = resolve_texture(model, "")
        self.assertIsNotNone(match)
        self.assertEqual(match.how, "prefixo")
        self.assertFalse(match.exact)
        self.assertEqual(len(match.alternatives), 1)

    def test_returns_none_when_nothing_matches(self) -> None:
        model = self._model("xyz123.p3m")
        self._texture("outra_coisa.dds")
        self.assertIsNone(resolve_texture(model, ""))

    def test_searches_extra_directories(self) -> None:
        model = self._model("abta999.p3m")
        outra = os.path.join(self.dir, "texturas")
        os.makedirs(outra)
        path = os.path.join(outra, "abta999.dds")
        with open(path, "wb") as handle:
            handle.write(write_dds(2, 2, checkerboard(2, 2), None))
        match = resolve_texture(model, "", [outra])
        self.assertIsNotNone(match)
        self.assertEqual(match.path, path)

    def test_ignores_garbage_declared_name(self) -> None:
        """O campo de textura do P3M as vezes tem lixo binario."""
        model = self._model("abta999.p3m")
        expected = self._texture("abta999.dds")
        match = resolve_texture(model, "\x88\xc1p\x15")
        self.assertEqual(match.path, expected)
        self.assertEqual(match.how, "nome")

    def test_case_insensitive(self) -> None:
        """No Windows os nomes nao diferenciam caixa; no Linux, sim."""
        model = self._model("abta999.p3m")
        expected = self._texture("ABTA999.DDS")
        match = resolve_texture(model, "")
        self.assertIsNotNone(match)
        self.assertEqual(match.path, expected)


if __name__ == "__main__":
    unittest.main()
