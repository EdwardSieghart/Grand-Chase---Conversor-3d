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
from dataclasses import dataclass, field

__all__ = [
    "DdsError",
    "PngError",
    "DdsImage",
    "TextureMatch",
    "read_dds",
    "read_png",
    "dds_to_png",
    "png_to_dds",
    "image_to_dds",
    "encode_png",
    "write_dds",
    "resolve_texture",
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
    elif pf_flags & (_DDPF_RGB | _DDPF_LUMINANCE):
        pixels = _decode_uncompressed(
            body, width, height, bit_count, r_mask, g_mask, b_mask,
            a_mask if pf_flags & _DDPF_ALPHAPIXELS else 0,
        )
        name = f"RGB{bit_count}"
    else:
        raise DdsError(
            f"formato DDS nao suportado (flags=0x{pf_flags:X}, fourCC={pf_fourcc!r})"
        )

    # `has_alpha` reflete transparencia **real**, nao a presenca do canal. Um DXT5
    # ou um A8R8G8B8 totalmente opaco nao precisa de canal alfa na saida, e usar o
    # formato do arquivo como critério faria toda textura opaca virar 32 bits.
    return DdsImage(width, height, pixels, name, _any_transparent(pixels))


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


# ------------------------------------------------------------ leitura de PNG


class PngError(ValueError):
    """Arquivo PNG invalido ou em formato nao suportado."""


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png(data: bytes) -> DdsImage:
    """Decodifica um PNG para RGBA de 8 bits por canal.

    Existe para o caminho inverso: o glTF embute a textura como PNG, e para
    gravar um `.dds` ao lado do `.p3m` e preciso decodifica-la primeiro.

    Cobre os cinco tipos de cor do PNG (cinza, RGB, paleta, cinza+alfa, RGBA),
    profundidades de 1, 2, 4, 8 e 16 bits, e transparencia por `tRNS`. PNG
    entrelacado (Adam7) e recusado com mensagem clara: nenhum exportador de glTF
    gera entrelacado, e implementar isso seria complexidade sem uso.
    """
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        raise PngError("nao e um arquivo PNG (assinatura ausente)")

    width = height = 0
    bit_depth = color_type = interlace = 0
    palette: bytes = b""
    transparency: bytes = b""
    idat = bytearray()

    offset = 8
    while offset + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        tag = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length  # tamanho + tag + dados + CRC

        if tag == b"IHDR":
            if length < 13:
                raise PngError("IHDR truncado")
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack_from(
                ">IIBBBBB", payload, 0
            )
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"tRNS":
            transparency = payload
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise PngError("PNG sem IHDR valido")
    if interlace:
        raise PngError(
            "PNG entrelacado (Adam7) nao suportado; salve sem entrelacamento"
        )
    if not idat:
        raise PngError("PNG sem dados de imagem (IDAT)")
    if bit_depth not in (1, 2, 4, 8, 16):
        raise PngError(f"profundidade de bits nao suportada: {bit_depth}")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError(f"colorType {color_type} desconhecido")

    raw = zlib.decompress(bytes(idat))
    bits_per_pixel = channels * bit_depth
    stride = (width * bits_per_pixel + 7) // 8
    # Distancia em bytes entre um pixel e o anterior, minimo 1: os filtros Sub,
    # Average e Paeth referenciam o pixel a esquerda.
    filter_unit = max(1, bits_per_pixel // 8)

    expected = (stride + 1) * height
    if len(raw) < expected:
        raise PngError(
            f"dados PNG truncados: esperava {expected} bytes apos descomprimir, "
            f"veio {len(raw)}"
        )

    scanlines = _unfilter_png(raw, height, stride, filter_unit)
    pixels = _png_to_rgba(
        scanlines, width, height, stride, bit_depth, color_type, palette, transparency
    )
    # `has_alpha` reflete transparencia **real**, nao a presenca do canal: quase
    # todo PNG que passa por este projeto e RGBA, e usar o tipo de cor faria toda
    # textura opaca virar DDS de 32 bits sem necessidade.
    has_alpha = _any_transparent(pixels)
    return DdsImage(
        width, height, pixels, f"PNG{bit_depth}/{color_type}", has_alpha
    )


def _unfilter_png(
    raw: bytes, height: int, stride: int, filter_unit: int
) -> bytearray:
    """Desfaz os filtros por linha do PNG, devolvendo os bytes crus."""
    out = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride

        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(filter_unit, stride):
                line[i] = (line[i] + line[i - filter_unit]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - filter_unit] if i >= filter_unit else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - filter_unit] if i >= filter_unit else 0
                up = previous[i]
                upper_left = previous[i - filter_unit] if i >= filter_unit else 0
                estimate = left + up - upper_left
                da = abs(estimate - left)
                db = abs(estimate - up)
                dc = abs(estimate - upper_left)
                if da <= db and da <= dc:
                    predictor = left
                elif db <= dc:
                    predictor = up
                else:
                    predictor = upper_left
                line[i] = (line[i] + predictor) & 0xFF
        else:
            raise PngError(f"tipo de filtro PNG invalido: {filter_type}")

        out[row * stride : (row + 1) * stride] = line
        previous = line
    return out


def _png_to_rgba(
    scanlines: bytearray,
    width: int,
    height: int,
    stride: int,
    bit_depth: int,
    color_type: int,
    palette: bytes,
    transparency: bytes,
) -> bytearray:
    """Expande as linhas ja desfiltradas para RGBA de 8 bits."""
    out = bytearray(width * height * 4)

    def samples_of_row(row: int) -> list[int]:
        """Amostras da linha, ja normalizadas para 0..255 (ou indice de paleta)."""
        start = row * stride
        line = scanlines[start : start + stride]
        if bit_depth == 8:
            return list(line)
        if bit_depth == 16:
            # Descarta o byte baixo: o destino tem 8 bits por canal.
            return list(line[0::2])
        # 1, 2 ou 4 bits: desempacota do bit mais significativo para o menos.
        values: list[int] = []
        per_byte = 8 // bit_depth
        mask = (1 << bit_depth) - 1
        for byte in line:
            for slot in range(per_byte):
                shift = 8 - bit_depth * (slot + 1)
                values.append((byte >> shift) & mask)
        return values

    # Para cinza e paleta em baixa profundidade, os valores precisam ser escalados
    # para 0..255 (cinza) ou usados como indice (paleta).
    maximum = (1 << bit_depth) - 1
    scale = 255.0 / maximum if maximum else 0.0

    for row in range(height):
        values = samples_of_row(row)
        base = row * width * 4

        if color_type == 0:  # cinza
            single = transparency and len(transparency) >= 2
            key = struct.unpack_from(">H", transparency, 0)[0] if single else -1
            if bit_depth == 16:
                key >>= 8
            for x in range(width):
                raw_value = values[x] if x < len(values) else 0
                level = int(raw_value * scale) if bit_depth != 8 else raw_value
                o = base + x * 4
                out[o] = out[o + 1] = out[o + 2] = level
                out[o + 3] = 0 if single and raw_value == key else 255
        elif color_type == 2:  # RGB
            for x in range(width):
                i = x * 3
                o = base + x * 4
                out[o] = values[i] if i < len(values) else 0
                out[o + 1] = values[i + 1] if i + 1 < len(values) else 0
                out[o + 2] = values[i + 2] if i + 2 < len(values) else 0
                out[o + 3] = 255
        elif color_type == 3:  # paleta
            for x in range(width):
                index = values[x] if x < len(values) else 0
                p = index * 3
                o = base + x * 4
                out[o] = palette[p] if p < len(palette) else 0
                out[o + 1] = palette[p + 1] if p + 1 < len(palette) else 0
                out[o + 2] = palette[p + 2] if p + 2 < len(palette) else 0
                out[o + 3] = (
                    transparency[index] if index < len(transparency) else 255
                )
        elif color_type == 4:  # cinza + alfa
            for x in range(width):
                i = x * 2
                level = values[i] if i < len(values) else 0
                o = base + x * 4
                out[o] = out[o + 1] = out[o + 2] = level
                out[o + 3] = values[i + 1] if i + 1 < len(values) else 255
        else:  # 6 = RGBA
            for x in range(width):
                i = x * 4
                o = base + x * 4
                out[o] = values[i] if i < len(values) else 0
                out[o + 1] = values[i + 1] if i + 1 < len(values) else 0
                out[o + 2] = values[i + 2] if i + 2 < len(values) else 0
                out[o + 3] = values[i + 3] if i + 3 < len(values) else 255
    return out


# ------------------------------------------------------------ escrita de DDS


def write_dds(width: int, height: int, rgba: bytes, force_alpha: bool | None = None) -> bytes:
    """Codifica pixels RGBA num arquivo DDS **sem compressao**.

    O formato escolhido copia exatamente o que o proprio jogo usa nos seus
    arquivos. Medindo as 406 texturas do conjunto de teste:

        190 + 60 + 1  -> 24 bits, R=0xFF0000 G=0xFF00 B=0xFF        (BGR)
         17 + 13      -> 32 bits, mais A=0xFF000000                 (BGRA)
        108 + 1 + ...  -> DXT1
         10 + 2 + 1   -> DXT5

    Ou seja, **a maioria das texturas do jogo ja e sem compressao**, o que torna
    escrever sem compressao a escolha segura: e sem perda e comprovadamente lido
    pelo jogo. Compressao DXT nao e implementada porque exigiria um compressor com
    perda para ganhar apenas espaco em disco.

    Usa 32 bits quando ha transparencia e 24 bits quando nao ha, igual ao jogo.
    Nao grava mipmaps — 326 das 406 texturas originais tambem nao tem.
    """
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(
            f"esperava {expected} bytes de RGBA para {width}x{height}, "
            f"recebeu {len(rgba)}"
        )

    if force_alpha is None:
        force_alpha = any(rgba[i] != 255 for i in range(3, len(rgba), 4))

    bytes_per_pixel = 4 if force_alpha else 3
    body = bytearray(width * height * bytes_per_pixel)
    if force_alpha:
        # A8R8G8B8: em memoria little-endian a ordem dos bytes e B, G, R, A.
        for i in range(width * height):
            src = i * 4
            dst = i * 4
            body[dst] = rgba[src + 2]
            body[dst + 1] = rgba[src + 1]
            body[dst + 2] = rgba[src]
            body[dst + 3] = rgba[src + 3]
    else:
        # R8G8B8: bytes B, G, R.
        for i in range(width * height):
            src = i * 4
            dst = i * 3
            body[dst] = rgba[src + 2]
            body[dst + 1] = rgba[src + 1]
            body[dst + 2] = rgba[src]

    header = bytearray(128)
    header[0:4] = _DDS_MAGIC
    struct.pack_into("<I", header, 4, 124)  # dwSize
    # DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT
    struct.pack_into("<I", header, 8, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000)
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 20, width * bytes_per_pixel)  # pitch
    struct.pack_into("<I", header, 24, 0)  # depth
    struct.pack_into("<I", header, 28, 0)  # mipMapCount

    # Pixel format, em 0x4C (76).
    struct.pack_into("<I", header, 76, 32)  # dwSize
    struct.pack_into(
        "<I", header, 80, (_DDPF_RGB | _DDPF_ALPHAPIXELS) if force_alpha else _DDPF_RGB
    )
    struct.pack_into("<I", header, 84, 0)  # fourCC
    struct.pack_into("<I", header, 88, bytes_per_pixel * 8)  # bit count
    struct.pack_into("<I", header, 92, 0x00FF0000)  # R
    struct.pack_into("<I", header, 96, 0x0000FF00)  # G
    struct.pack_into("<I", header, 100, 0x000000FF)  # B
    struct.pack_into("<I", header, 104, 0xFF000000 if force_alpha else 0)  # A

    struct.pack_into("<I", header, 108, 0x1000)  # caps: DDSCAPS_TEXTURE

    return bytes(header) + bytes(body)


def png_to_dds(png: bytes) -> bytes:
    """Converte os bytes de um PNG nos bytes de um DDS sem compressao.

    O numero de bits e decidido pelos pixels: 32 se houver transparencia de fato,
    24 se nao houver. Passar `None` deixa essa decisao com `write_dds`.
    """
    image = read_png(png)
    return write_dds(image.width, image.height, bytes(image.pixels), None)


def image_to_dds(data: bytes) -> bytes:
    """Converte PNG ou DDS para DDS sem compressao.

    Um DDS de entrada e decodificado e regravado sem compressao, para que a saida
    seja sempre um formato que o jogo aceita.
    """
    if data[:8] == _PNG_SIGNATURE:
        return png_to_dds(data)
    if data[:4] == _DDS_MAGIC:
        image = read_dds(data)
        return write_dds(image.width, image.height, bytes(image.pixels), None)
    raise DdsError("formato de imagem nao reconhecido (esperado PNG ou DDS)")


# ------------------------------------------------------------ busca de textura


@dataclass
class TextureMatch:
    """Resultado da busca de textura de um modelo."""

    path: str
    #: Como o arquivo foi encontrado, para poder avisar quando foi um chute.
    #: "declarado" | "nome" | "sufixo" | "prefixo"
    how: str = "nome"
    #: Outros candidatos com o mesmo prefixo, quando `how == "prefixo"`.
    alternatives: list[str] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return self.how in ("declarado", "nome", "sufixo")


def resolve_texture(
    model_path: str,
    texture_name: str = "",
    search_dirs: list[str] | None = None,
) -> TextureMatch | None:
    """Procura o arquivo de textura de um modelo.

    O campo `textureName` do P3M vem vazio na maioria dos arquivos oficiais, e
    quando vem preenchido pode conter lixo binario. A busca entao usa varias
    estrategias, da mais confiavel para a menos, e informa qual funcionou para que
    o chamador possa avisar quando o resultado foi um chute.

    As regras vieram de medir os 127 modelos e 406 texturas do conjunto de teste:

    1. **declarado** — o nome gravado no proprio P3M, se parecer utilizavel.
    2. **nome** — o nome do modelo (`abta003.p3m` -> `abta003.dds`). Resolve 119
       dos 127 modelos.
    3. **sufixo** — o nome sem o ultimo segmento `_x`, progressivamente
       (`abta93827_m` -> `abta93827`). Existe porque variantes de um modelo
       compartilham a textura do original.
    4. **prefixo** — qualquer imagem que comece com o nome do modelo sem o ultimo
       segmento (`face_04_00` -> `face_04_hited_01.dds`). E um chute, mas util:
       os rostos do jogo tem uma textura por expressao e nem sempre existe a
       `_00`; todas servem a mesma malha e mesmo UV. Devolve as alternativas para
       que o usuario saiba que ha outras.
    """
    model_dir = os.path.dirname(os.path.abspath(model_path))
    stem = os.path.splitext(os.path.basename(model_path))[0]

    dirs = [model_dir]
    for extra in search_dirs or []:
        if extra and extra not in dirs:
            dirs.append(extra)

    # Indexa cada pasta uma vez, em minusculas: resolve diferenca de caixa entre
    # o Windows (case-insensitive) e o Linux (case-sensitive).
    listings: list[tuple[str, dict[str, str]]] = []
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        try:
            listings.append(
                (directory, {name.lower(): name for name in os.listdir(directory)})
            )
        except OSError:
            continue
    if not listings:
        return None

    def lookup(base: str) -> str | None:
        """Procura `base` com e sem extensao conhecida, em todas as pastas."""
        key = os.path.basename(base).lower()
        if not key:
            return None
        for directory, listing in listings:
            if key in listing:
                path = os.path.join(directory, listing[key])
                if os.path.isfile(path):
                    return path
            for extension in TEXTURE_EXTENSIONS:
                if key + extension in listing:
                    path = os.path.join(directory, listing[key + extension])
                    if os.path.isfile(path):
                        return path
        return None

    # 1. nome declarado no P3M
    cleaned = _clean_texture_name(texture_name)
    if cleaned:
        for candidate in (cleaned, os.path.splitext(cleaned)[0]):
            found = lookup(candidate)
            if found:
                return TextureMatch(found, "declarado")

    # 2. nome do modelo, incluindo prefixos que o jogo usa
    bases = [stem]
    for prefix in ("mesh_", "live"):
        if stem.startswith(prefix):
            bases.append(stem[len(prefix) :])
    for base in bases:
        found = lookup(base)
        if found:
            return TextureMatch(found, "nome")

    # 3. remove segmentos do fim, um por um
    for base in bases:
        parts = base.split("_")
        while len(parts) > 1:
            parts.pop()
            found = lookup("_".join(parts))
            if found:
                return TextureMatch(found, "sufixo")

    # 4. qualquer imagem com o mesmo prefixo
    for base in bases:
        parts = base.split("_")
        prefix = "_".join(parts[:-1]) if len(parts) > 1 else base
        if len(prefix) < 3:
            continue
        matches: list[str] = []
        for directory, listing in listings:
            for lower, real in sorted(listing.items()):
                if not lower.startswith(prefix.lower()):
                    continue
                if os.path.splitext(lower)[1] not in TEXTURE_EXTENSIONS:
                    continue
                matches.append(os.path.join(directory, real))
        if matches:
            matches.sort()
            return TextureMatch(matches[0], "prefixo", matches[1:])

    return None


def find_texture_file(
    model_path: str,
    texture_name: str = "",
    search_dirs: list[str] | None = None,
) -> str | None:
    """Versao simples de `resolve_texture`, devolvendo apenas o caminho."""
    match = resolve_texture(model_path, texture_name, search_dirs)
    return match.path if match else None


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
