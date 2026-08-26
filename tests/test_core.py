"""Testes do leitor/escritor binario e da matematica 3D."""

from __future__ import annotations

import math
import struct
import unittest

from gc3d.binary import BinaryReader, BinaryWriter, TruncatedDataError
from gc3d.mathutil import (
    FLIP_Z,
    MAT4_IDENTITY,
    mat4_flip_z_conjugate,
    mat4_multiply,
    mat4_to_quaternion,
    vec3_flip_z,
    vec3_normalize,
)


class TestBinaryReader(unittest.TestCase):
    def test_le_scalars(self) -> None:
        data = struct.pack("<BHIf", 0xAB, 0x1234, 0xDEADBEEF, 1.5)
        reader = BinaryReader(data)
        self.assertEqual(reader.u8(), 0xAB)
        self.assertEqual(reader.u16(), 0x1234)
        self.assertEqual(reader.u32(), 0xDEADBEEF)
        self.assertAlmostEqual(reader.f32(), 1.5)
        self.assertTrue(reader.eof)

    def test_vectors(self) -> None:
        reader = BinaryReader(struct.pack("<5f", 1.0, 2.0, 3.0, 0.25, 0.75))
        self.assertEqual(reader.vec3(), (1.0, 2.0, 3.0))
        self.assertEqual(reader.vec2(), (0.25, 0.75))

    def test_cstring_stops_at_nul(self) -> None:
        # Campo de tamanho fixo com lixo depois do NUL, como no P3M real.
        reader = BinaryReader(b"textura.dds\0LIXOLIXO")
        self.assertEqual(reader.cstring(20), "textura.dds")
        self.assertTrue(reader.eof)

    def test_cstring_without_nul(self) -> None:
        reader = BinaryReader(b"abcd")
        self.assertEqual(reader.cstring(4), "abcd")

    def test_truncated_raises_with_context(self) -> None:
        reader = BinaryReader(b"\x01\x02")
        with self.assertRaises(TruncatedDataError) as ctx:
            reader.u32()
        self.assertEqual(ctx.exception.needed, 4)
        self.assertEqual(ctx.exception.available, 2)
        self.assertEqual(ctx.exception.offset, 0)

    def test_peek_does_not_advance(self) -> None:
        reader = BinaryReader(b"abcdef")
        self.assertEqual(reader.peek(3), b"abc")
        self.assertEqual(reader.tell(), 0)

    def test_remaining_and_skip(self) -> None:
        reader = BinaryReader(b"0123456789")
        reader.skip(4)
        self.assertEqual(reader.remaining, 6)
        reader.seek(0)
        self.assertEqual(reader.remaining, 10)


class TestBinaryWriter(unittest.TestCase):
    def test_round_trip(self) -> None:
        writer = BinaryWriter()
        writer.u8(7)
        writer.u16(1000)
        writer.u32(70000)
        writer.f32(-2.5)
        writer.f32s((1.0, 2.0))
        writer.cstring("tex", 8)

        reader = BinaryReader(writer.getvalue())
        self.assertEqual(reader.u8(), 7)
        self.assertEqual(reader.u16(), 1000)
        self.assertEqual(reader.u32(), 70000)
        self.assertAlmostEqual(reader.f32(), -2.5)
        self.assertEqual(reader.f32s(2), (1.0, 2.0))
        self.assertEqual(reader.cstring(8), "tex")

    def test_align_pads_to_multiple(self) -> None:
        writer = BinaryWriter()
        writer.bytes(b"abc")
        writer.align(4)
        self.assertEqual(len(writer), 4)
        writer.align(4)
        self.assertEqual(len(writer), 4, "align nao deve adicionar nada se ja alinhado")


class TestVectors(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(vec3_normalize((0.0, 3.0, 0.0)), (0.0, 1.0, 0.0))
        length = 1.0
        result = vec3_normalize((2.0, -3.0, 6.0))  # comprimento 7
        self.assertAlmostEqual(
            math.sqrt(sum(c * c for c in result)), length, places=6
        )

    def test_normalize_degenerate_returns_zero(self) -> None:
        # P3M reais tem normais nulas; nao pode dividir por zero.
        self.assertEqual(vec3_normalize((0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))

    def test_flip_z(self) -> None:
        self.assertEqual(vec3_flip_z((1.0, 2.0, 3.0)), (1.0, 2.0, -3.0))


def rotation_y(angle: float) -> tuple[float, ...]:
    """Matriz column-major de rotacao em torno de Y."""
    c, s = math.cos(angle), math.sin(angle)
    return (
        c, 0.0, -s, 0.0,
        0.0, 1.0, 0.0, 0.0,
        s, 0.0, c, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


class TestMatrices(unittest.TestCase):
    def test_identity_is_neutral(self) -> None:
        matrix = rotation_y(0.7)
        product = mat4_multiply(MAT4_IDENTITY, matrix)
        for a, b in zip(product, matrix):
            self.assertAlmostEqual(a, b, places=6)

    def test_multiply_matches_manual(self) -> None:
        # Rotacoes em torno do mesmo eixo somam angulos.
        a = rotation_y(0.3)
        b = rotation_y(0.4)
        expected = rotation_y(0.7)
        product = mat4_multiply(a, b)
        for x, y in zip(product, expected):
            self.assertAlmostEqual(x, y, places=6)

    def test_flip_z_is_involutive(self) -> None:
        product = mat4_multiply(FLIP_Z, FLIP_Z)
        for a, b in zip(product, MAT4_IDENTITY):
            self.assertAlmostEqual(a, b, places=9)

    def test_flip_z_conjugate_equals_explicit_product(self) -> None:
        matrix = rotation_y(0.6)
        fast = mat4_flip_z_conjugate(matrix)
        slow = mat4_multiply(mat4_multiply(FLIP_Z, matrix), FLIP_Z)
        for a, b in zip(fast, slow):
            self.assertAlmostEqual(a, b, places=9)

    def test_flip_z_conjugate_reverses_rotation_sense(self) -> None:
        # Espelhar Z inverte a mao do sistema, logo uma rotacao em torno de Y
        # por +t passa a ser -t. E exatamente isso que corrige as animacoes.
        angle = 0.9
        conjugated = mat4_flip_z_conjugate(rotation_y(angle))
        expected = rotation_y(-angle)
        for a, b in zip(conjugated, expected):
            self.assertAlmostEqual(a, b, places=6)


class TestQuaternions(unittest.TestCase):
    def test_identity(self) -> None:
        self.assertEqual(mat4_to_quaternion(MAT4_IDENTITY), (0.0, 0.0, 0.0, 1.0))

    def test_rotation_about_y(self) -> None:
        angle = math.pi / 2
        x, y, z, w = mat4_to_quaternion(rotation_y(angle))
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, math.sin(angle / 2), places=6)
        self.assertAlmostEqual(z, 0.0, places=6)
        self.assertAlmostEqual(w, math.cos(angle / 2), places=6)

    def test_always_unit_length(self) -> None:
        for angle in (0.1, 1.0, 2.0, 3.0, -2.5):
            q = mat4_to_quaternion(rotation_y(angle))
            self.assertAlmostEqual(
                math.sqrt(sum(c * c for c in q)), 1.0, places=6
            )

    def test_degenerate_matrix_returns_identity(self) -> None:
        # FRM v1.2 traz matrizes zeradas em muitos arquivos oficiais; devolver
        # identidade evita NaN propagando para a animacao inteira.
        zeros = tuple([0.0] * 16)
        self.assertEqual(mat4_to_quaternion(zeros), (0.0, 0.0, 0.0, 1.0))

    def test_scale_is_removed(self) -> None:
        # Escala uniforme nao deve alterar o quaternion extraido.
        angle = 0.8
        matrix = list(rotation_y(angle))
        for column in range(3):
            for row in range(3):
                matrix[column * 4 + row] *= 3.0
        scaled = mat4_to_quaternion(tuple(matrix))
        plain = mat4_to_quaternion(rotation_y(angle))
        for a, b in zip(scaled, plain):
            self.assertAlmostEqual(a, b, places=5)


if __name__ == "__main__":
    unittest.main()
