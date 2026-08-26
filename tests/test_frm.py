"""Testes do parser FRM.

Cobre as duas versoes implementadas (1.0 e 1.1), a ordem column-major das
matrizes, a semantica incremental de `plus_x` e a posicao do bloco de `pos_z` no
fim do arquivo — os quatro pontos onde e mais facil errar o formato.
"""

from __future__ import annotations

import struct
import unittest

from gc3d.formats import frm
from gc3d.scene import DEFAULT_FPS

HEADER_V11 = b"Frm Ver 1.1\0"


def identity_matrix_bytes() -> bytes:
    """Matriz identidade em column-major."""
    return struct.pack(
        "<16f",
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


def matrix_with_translation(tx: float, ty: float, tz: float) -> bytes:
    """Identidade com translacao. Em column-major a translacao e a coluna 3."""
    return struct.pack(
        "<16f",
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        tx, ty, tz, 1.0,
    )


def build_frm_v11(frames: list[tuple[int, float, float, list[bytes]]], pos_z: list[float]) -> bytes:
    num_bones = len(frames[0][3]) if frames else 0
    out = bytearray(HEADER_V11)
    out += struct.pack("<HH", len(frames), num_bones)
    for option, plus_x, pos_y, matrices in frames:
        out += struct.pack("<B", option)
        out += struct.pack("<f", plus_x)
        out += struct.pack("<f", pos_y)
        for matrix in matrices:
            out += matrix
    # O bloco de pos_z vem depois de TODOS os frames.
    for value in pos_z:
        out += struct.pack("<f", value)
    return bytes(out)


def build_frm_v10(frames: list[tuple[int, float, float, list[bytes]]]) -> bytes:
    num_bones = len(frames[0][3]) if frames else 0
    out = bytearray(struct.pack("<BB", len(frames), num_bones))
    for option, plus_x, pos_y, matrices in frames:
        out += struct.pack("<B", option)
        out += struct.pack("<f", plus_x)
        out += struct.pack("<f", pos_y)
        for matrix in matrices:
            out += matrix
    return bytes(out)


class TestVersionDetection(unittest.TestCase):
    def test_v11_header(self) -> None:
        data = build_frm_v11([(0, 0.0, 0.0, [identity_matrix_bytes()])], [0.0])
        self.assertEqual(frm.detect_version(data), "1.1")

    def test_v10_has_no_header(self) -> None:
        data = build_frm_v10([(0, 0.0, 0.0, [identity_matrix_bytes()])])
        self.assertEqual(frm.detect_version(data), "1.0")

    def test_v12_detected_and_refused(self) -> None:
        data = b"Frm Ver 1.2\0" + b"\0" * 64
        self.assertEqual(frm.detect_version(data), "1.2")
        with self.assertRaises(frm.UnsupportedFrmVersionError):
            frm.read_frm(data)

    def test_v12_origin_uses_uppercase_frm(self) -> None:
        data = b"FRM Ver 1.2\0" + b"\0" * 64
        self.assertEqual(frm.detect_version(data), "1.2_Origin")


class TestParsingV11(unittest.TestCase):
    def test_counts_and_no_leftover_bytes(self) -> None:
        data = build_frm_v11(
            [
                (0, 1.0, 5.0, [identity_matrix_bytes(), identity_matrix_bytes()]),
                (0, 2.0, 6.0, [identity_matrix_bytes(), identity_matrix_bytes()]),
            ],
            [10.0, 20.0],
        )
        animation = frm.read_frm(data)
        self.assertEqual(animation.version, "1.1")
        self.assertEqual(animation.num_frames, 2)
        self.assertEqual(animation.num_bones, 2)
        self.assertEqual(
            animation.trailing_bytes, 0, "o layout deve consumir o arquivo inteiro"
        )

    def test_pos_z_block_is_at_end_of_file(self) -> None:
        data = build_frm_v11(
            [
                (0, 0.0, 0.0, [identity_matrix_bytes()]),
                (0, 0.0, 0.0, [identity_matrix_bytes()]),
                (0, 0.0, 0.0, [identity_matrix_bytes()]),
            ],
            [1.5, 2.5, 3.5],
        )
        animation = frm.read_frm(data)
        self.assertEqual([f.pos_z for f in animation.frames], [1.5, 2.5, 3.5])

    def test_matrices_are_column_major(self) -> None:
        # Se o parser lesse row-major, a translacao apareceria nos indices 3,7,11
        # em vez de 12,13,14.
        data = build_frm_v11(
            [(0, 0.0, 0.0, [matrix_with_translation(7.0, 8.0, 9.0)])], [0.0]
        )
        animation = frm.read_frm(data)
        matrix = animation.frames[0].bones[0]
        self.assertEqual((matrix[12], matrix[13], matrix[14]), (7.0, 8.0, 9.0))
        self.assertEqual(matrix[15], 1.0)

    def test_frame_fields(self) -> None:
        data = build_frm_v11([(3, 1.25, -2.5, [identity_matrix_bytes()])], [0.0])
        frame = frm.read_frm(data).frames[0]
        self.assertEqual(frame.option, 3)
        self.assertAlmostEqual(frame.plus_x, 1.25)
        self.assertAlmostEqual(frame.pos_y, -2.5)

    def test_truncated_file_is_rejected(self) -> None:
        data = build_frm_v11([(0, 0.0, 0.0, [identity_matrix_bytes()])], [0.0])
        with self.assertRaises(frm.InvalidFrmError):
            frm.read_frm(data[:-20])

    def test_zero_bones_is_rejected(self) -> None:
        data = HEADER_V11 + struct.pack("<HH", 1, 0)
        with self.assertRaises(frm.InvalidFrmError):
            frm.read_frm(data)


class TestParsingV10(unittest.TestCase):
    def test_counts(self) -> None:
        data = build_frm_v10(
            [
                (0, 1.0, 2.0, [identity_matrix_bytes()]),
                (0, 1.0, 2.0, [identity_matrix_bytes()]),
            ]
        )
        animation = frm.read_frm(data)
        self.assertEqual(animation.version, "1.0")
        self.assertEqual(animation.num_frames, 2)
        self.assertEqual(animation.num_bones, 1)
        self.assertEqual(animation.trailing_bytes, 0)

    def test_pos_z_is_zero(self) -> None:
        data = build_frm_v10([(0, 0.0, 0.0, [identity_matrix_bytes()])])
        self.assertEqual(frm.read_frm(data).frames[0].pos_z, 0.0)


class TestAnimationConversion(unittest.TestCase):
    def test_plus_x_accumulates_y_and_z_are_absolute(self) -> None:
        data = build_frm_v11(
            [
                (0, 1.0, 10.0, [identity_matrix_bytes()]),
                (0, 2.0, 20.0, [identity_matrix_bytes()]),
                (0, 3.0, 30.0, [identity_matrix_bytes()]),
            ],
            [100.0, 200.0, 300.0],
        )
        animation = frm.frm_to_animation(frm.read_frm(data), "andar")
        translations = [f.translation for f in animation.frames]
        self.assertEqual(
            translations,
            [(1.0, 10.0, 100.0), (3.0, 20.0, 200.0), (6.0, 30.0, 300.0)],
            "plus_x deve acumular; pos_y e pos_z sao absolutos",
        )

    def test_name_and_fps(self) -> None:
        data = build_frm_v11([(0, 0.0, 0.0, [identity_matrix_bytes()])], [0.0])
        animation = frm.frm_to_animation(frm.read_frm(data), "pular")
        self.assertEqual(animation.name, "pular")
        self.assertEqual(animation.fps, DEFAULT_FPS)
        self.assertEqual(animation.fps, 55)

    def test_times_are_spaced_by_one_over_fps(self) -> None:
        data = build_frm_v11(
            [(0, 0.0, 0.0, [identity_matrix_bytes()]) for _ in range(3)],
            [0.0, 0.0, 0.0],
        )
        animation = frm.frm_to_animation(frm.read_frm(data), "x")
        times = animation.times()
        self.assertEqual(len(times), 3)
        self.assertAlmostEqual(times[1] - times[0], 1.0 / 55.0)
        self.assertAlmostEqual(animation.duration, 2.0 / 55.0)


if __name__ == "__main__":
    unittest.main()
