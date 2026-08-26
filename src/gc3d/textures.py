"""Conversao de texturas DDS para PNG, em Python puro.

As texturas do Grand Chase sao DDS (DirectDraw Surface), formato que o glTF nao
aceita. O glTF aceita PNG e JPEG. Como nao queremos depender de Pillow (para o
projeto continuar sendo um unico arquivo executavel sem instalacao), este modulo
implementa:

* decodificacao dos formatos DDS que aparecem no jogo: DXT1/BC1, DXT3/BC2,
  DXT5/BC3 e superficies nao comprimidas de 16, 24 e 32 bits;
* codificacao de PNG RGBA usando apenas `zlib` e `binascii.crc32`.

Somente o mip level 0 (a imagem em resolucao cheia) e convertido; o glTF gera
mipmaps na hora de renderizar.
"""

from __future__ import annotations

import binascii
import os
import struct
import zlib

__all__ = [
    "DdsError",
    "DdsImage",
    "read_dds",
    "dds_to_png",
    "encode_png",
    "find_texture_file",
    "load_texture_as_png",
]

_DDS_MAGIC = b"DDS "
_DDPF_ALPHAPIXELS = 0x1
_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40
_DDPF_LUMINANCE = 0x20000

#: Extensoes de imagem que sabemos aproveitar, em ordem de preferencia.
TEXTURE_EXTENSIONS = (".png", ".dds", ".tga", ".bmp", ".jpg", ".jpeg")


class DdsError(ValueError):
    """Arquivo DDS invalido ou em formato nao suportado."""


class DdsImage:
    """Imagem RGBA decodificada."""

    __slots__ = ("width", "height", "pixels", "source_format", "has_alpha")

    def __init__(
        self,
        width: int,
        height: int,
        pixels: bytearray,
        source_format: str,
        has_alpha: bool,
    ) -> None:
        self.width = width
        self.height = height
        #: RGBA de 8 bits por canal, `width * height * 4` bytes.
        self.pixels = pixels
        self.source_format = source_format
        self.has_alpha = has_alpha


# ----------------------------------------------------------------- leitura DDS


def read_dds(data: bytes) -> DdsImage:
    """Decodifica o mip level 0 de um DDS para RGBA."""
    if len(data) < 128 or data[:4] != _DDS_MAGIC:
        raise DdsError("nao e um arquivo DDS (assinatura 'DDS ' ausente)")

    header_size = struct.unpack_from("<I", data, 4)[0]
    if header_size != 124:
        raise DdsError(f"tamanho de cabecalho DDS inesperado: {header_size}")

    height, width = struct.unpack_from("<II", data, 12)
    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
        raise DdsError(f"dimensoes DDS improvaveis: {width}x{height}")

    # Pixel format fica no offset 76: size, flags, fourCC, bitCount, 4 mascaras.
    pf_flags, pf_fourcc = struct.unpack_from("<I4s", data, 80)
    bit_count, r_mask, g_mask, b_mask, a_mask = struct.unpack_from("<5I", data, 88)

    offset = 4 + header_size
    if pf_flags & _DDPF_FOURCC and pf_fourcc == b"DX10":
        offset += 20  # DDS_HEADER_DXT10
        dxgi_format = struct.unpack_from("<I", data, 128)[0]
        fourcc = _DXGI_TO_FOURCC.get(dxgi_format)
        if fourcc is None:
            raise DdsError(f"DXGI_FORMAT {dxgi_format} nao suportado")
    elif pf_flags & _DDPF_FOURCC:
        fourcc = pf_fourcc
    else:
        fourcc = None

    body = data[offset:]

    if fourcc in (b"DXT1", b"DXT2", b"DXT3", b"DXT4", b"DXT5"):
        pixels = _decode_bc(body, width, height, fourcc)
        name = fourcc.decode("ascii")
        has_alpha = fourcc != b"DXT1" or _any_transparent(pixels)
    elif pf_flags & (_DDPF_RGB | _DDPF_LUMINANCE):
        pixels = _decode_uncompressed(
            body, width, height, bit_count, r_mask, g_mask, b_mask,
            a_mask if pf_flags & _DDPF_ALPHAPIXELS else 0,
        )
        name = f"RGB{bit_count}"
        has_alpha = bool(pf_flags & _DDPF_ALPHAPIXELS) and _any_transparent(pixels)
    else:
        raise DdsError(
            f"formato DDS nao suportado (flags=0x{pf_flags:X}, fourCC={pf_fourcc!r})"
        )

    return DdsImage(width, height, pixels, name, has_alpha)


_DXGI_TO_FOURCC = {
    70: b"DXT1", 71: b"DXT1", 72: b"DXT1",  # BC1
    73: b"DXT3", 74: b"DXT3", 75: b"DXT3",  # BC2
    76: b"DXT5", 77: b"DXT5", 78: b"DXT5",  # BC3
}


def _any_transparent(pixels: bytearray) -> bool:
    return any(pixels[i] != 255 for i in range(3, len(pixels), 4))


# ---------------------------------------------------- blocos comprimidos BCn


def _rgb565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    # Replicacao dos bits altos: mais fiel que multiplicar e dividir.
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _decode_bc(body: bytes, width: int, height: int, fourcc: bytes) -> bytearray:
    """Decodifica DXT1/DXT3/DXT5 para RGBA."""
    block_bytes = 8 if fourcc == b"DXT1" else 16
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    needed = blocks_x * blocks_y * block_bytes
    if len(body) < needed:
        raise DdsError(
            f"dados DDS truncados: {fourcc.decode()} {width}x{height} precisa de "
            f"{needed} bytes, ha {len(body)}"
        )

    out = bytearray(width * height * 4)
    stride = width * 4

    for by in range(blocks_y):
        for bx in range(blocks_x):
            block_offset = (by * blocks_x + bx) * block_bytes

            if fourcc == b"DXT1":
                alphas = None
                color_offset = block_offset
            elif fourcc in (b"DXT2", b"DXT3"):
                alphas = _decode_bc2_alpha(body, block_offset)
                color_offset = block_offset + 8
            else:  # DXT4 / DXT5
                alphas = _decode_bc3_alpha(body, block_offset)
                color_offset = block_offset + 8

            c0, c1, bits = struct.unpack_from("<HHI", body, color_offset)
            r0, g0, b0 = _rgb565(c0)
            r1, g1, b1 = _rgb565(c1)

            if fourcc == b"DXT1" and c0 <= c1:
                # Modo de 3 cores + transparente.
                palette = (
                    (r0, g0, b0, 255),
                    (r1, g1, b1, 255),
                    ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
                    (0, 0, 0, 0),
                )
            else:
                palette = (
                    (r0, g0, b0, 255),
                    (r1, g1, b1, 255),
                    ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255),
                    ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255),
                )

            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    break
                row = y * stride
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        break
                    code = (bits >> (2 * (py * 4 + px))) & 0x3
                    r, g, b, a = palette[code]
                    if alphas is not None:
                        a = alphas[py * 4 + px]
                    i = row + x * 4
                    out[i] = r
                    out[i + 1] = g
                    out[i + 2] = b
                    out[i + 3] = a
    return out


def _decode_bc2_alpha(body: bytes, offset: int) -> list[int]:
    """DXT3: 4 bits de alfa explicito por pixel."""
    alphas = []
    for i in range(8):
        byte = body[offset + i]
        low = byte & 0x0F
        high = (byte >> 4) & 0x0F
        alphas.append(low * 17)  # 0..15 -> 0..255
        alphas.append(high * 17)
    return alphas


def _decode_bc3_alpha(body: bytes, offset: int) -> list[int]:
    """DXT5: dois alfas de referencia e indices de 3 bits interpolados."""
    a0 = body[offset]
    a1 = body[offset + 1]
    if a0 > a1:
        table = [
            a0,
            a1,
            (6 * a0 + 1 * a1) // 7,
            (5 * a0 + 2 * a1) // 7,
            (4 * a0 + 3 * a1) // 7,
            (3 * a0 + 4 * a1) // 7,
            (2 * a0 + 5 * a1) // 7,
            (1 * a0 + 6 * a1) // 7,
        ]
    else:
        table = [
            a0,
            a1,
            (4 * a0 + 1 * a1) // 5,
            (3 * a0 + 2 * a1) // 5,
            (2 * a0 + 3 * a1) // 5,
            (1 * a0 + 4 * a1) // 5,
            0,
            255,
        ]
    # 16 indices de 3 bits empacotados em 6 bytes, lidos como inteiro de 48 bits.
    packed = int.from_bytes(body[offset + 2 : offset + 8], "little")
    return [table[(packed >> (3 * i)) & 0x7] for i in range(16)]


# ------------------------------------------------------ superficies nao comprimidas


def _mask_shift_scale(mask: int) -> tuple[int, float]:
    if mask == 0:
        return 0, 0.0
    shift = (mask & -mask).bit_length() - 1
    bits = bin(mask >> shift).count("1")
    maximum = (1 << bits) - 1
    return shift, 255.0 / maximum if maximum else 0.0


def _decode_uncompressed(
    body: bytes,
    width: int,
    height: int,
    bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
) -> bytearray:
    if bit_count not in (8, 16, 24, 32):
        raise DdsError(f"profundidade de cor nao suportada: {bit_count} bits")
    bytes_per_pixel = bit_count // 8
    needed = width * height * bytes_per_pixel
    if len(body) < needed:
        raise DdsError(
            f"dados DDS truncados: {width}x{height}x{bit_count}bpp precisa de "
            f"{needed} bytes, ha {len(body)}"
        )

    r_shift, r_scale = _mask_shift_scale(r_mask)
    g_shift, g_scale = _mask_shift_scale(g_mask)
    b_shift, b_scale = _mask_shift_scale(b_mask)
    a_shift, a_scale = _mask_shift_scale(a_mask)

    out = bytearray(width * height * 4)
    for i in range(width * height):
        raw = int.from_bytes(
            body[i * bytes_per_pixel : (i + 1) * bytes_per_pixel], "little"
        )
        o = i * 4
        out[o] = int(((raw & r_mask) >> r_shift) * r_scale) if r_mask else 0
        out[o + 1] = int(((raw & g_mask) >> g_shift) * g_scale) if g_mask else 0
        out[o + 2] = int(((raw & b_mask) >> b_shift) * b_scale) if b_mask else 0
        out[o + 3] = int(((raw & a_mask) >> a_shift) * a_scale) if a_mask else 255
    return out


# -------------------------------------------------------------- escrita de PNG


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgba: bytes, compress_level: int = 6) -> bytes:
    """Codifica pixels RGBA de 8 bits em um PNG sem perdas."""
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(
            f"esperava {expected} bytes de RGBA para {width}x{height}, "
            f"recebeu {len(rgba)}"
        )

    stride = width * 4
    # Cada linha e prefixada pelo tipo de filtro; 0 = None, que e o mais rapido
    # e ja comprime bem para texturas de jogo.
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride : (y + 1) * stride]

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), compress_level))
        + _png_chunk(b"IEND", b"")
    )


def dds_to_png(data: bytes) -> bytes:
    """Converte os bytes de um DDS nos bytes de um PNG equivalente."""
    image = read_dds(data)
    return encode_png(image.width, image.height, bytes(image.pixels))


# ------------------------------------------------------------ busca de textura


def find_texture_file(
    model_path: str,
    texture_name: str = "",
    search_dirs: list[str] | None = None,
) -> str | None:
    """Procura o arquivo de textura de um modelo.

    O campo `textureName` do P3M vem vazio na maioria dos arquivos oficiais, e
    quando vem preenchido pode conter lixo binario. Por isso a busca tem duas
    estrategias, nesta ordem:

    1. o nome declarado no P3M, se parecer utilizavel;
    2. o nome do proprio modelo (`abta003.p3m` -> `abta003.dds`), que e a
       convencao usada pelos arquivos do jogo.

    Cada candidato e procurado na pasta do modelo e nas pastas extras
    informadas, testando as extensoes conhecidas.
    """
    model_dir = os.path.dirname(os.path.abspath(model_path))
    stem = os.path.splitext(os.path.basename(model_path))[0]

    dirs = [model_dir]
    for extra in search_dirs or []:
        if extra and extra not in dirs:
            dirs.append(extra)

    candidates: list[str] = []
    cleaned = _clean_texture_name(texture_name)
    if cleaned:
        candidates.append(cleaned)
        candidates.append(os.path.splitext(cleaned)[0])
    candidates.append(stem)
    # Modelos do jogo costumam ter prefixos: "mesh_abta1.p3m" usa "abta1.dds".
    for prefix in ("mesh_", "bigface_", "face_", "live"):
        if stem.startswith(prefix):
            candidates.append(stem[len(prefix) :])

    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        # Indexa a pasta uma vez, em minusculas: resolve diferenca de caixa
        # entre o Windows (case-insensitive) e o Linux (case-sensitive).
        try:
            listing = {name.lower(): name for name in os.listdir(directory)}
        except OSError:
            continue
        for candidate in candidates:
            base = os.path.basename(candidate).lower()
            if not base:
                continue
            if base in listing:
                path = os.path.join(directory, listing[base])
                if os.path.isfile(path):
                    return path
            for extension in TEXTURE_EXTENSIONS:
                key = base + extension
                if key in listing:
                    path = os.path.join(directory, listing[key])
                    if os.path.isfile(path):
                        return path
    return None


def _clean_texture_name(texture_name: str) -> str:
    """Descarta nomes de textura que sao claramente lixo de memoria."""
    if not texture_name:
        return ""
    name = texture_name.strip().replace("\\", "/")
    name = name.split("/")[-1]
    # Bytes de controle ou substituicao indicam campo corrompido.
    if any(ord(ch) < 32 or ch == "\ufffd" for ch in name):
        # Ainda pode haver uma parte util depois do lixo, ex. "\x88\xc1p\x15arma01".
        cleaned = "".join(
            ch for ch in name if ord(ch) >= 32 and ch != "\ufffd"
        ).strip()
        return cleaned if len(cleaned) >= 3 else ""
    return name


def load_texture_as_png(path: str) -> bytes:
    """Carrega uma imagem do disco e devolve bytes de PNG.

    PNG e devolvido como esta; DDS e convertido. Outros formatos levantam erro,
    porque o glTF nao os aceita embutidos.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    if data[:4] == _DDS_MAGIC:
        return dds_to_png(data)
    raise DdsError(
        f"{os.path.basename(path)}: formato de imagem nao suportado para "
        f"embutir em glTF (use PNG ou DDS)"
    )
