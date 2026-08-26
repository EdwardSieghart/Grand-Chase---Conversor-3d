"""Leitura e escrita de dados binarios little-endian.

Os formatos P3M e FRM do Grand Chase sao estruturas C cruas gravadas por um
executavel Windows x86, portanto sao sempre little-endian e sem compressao.

Este modulo nao depende de nada fora da biblioteca padrao.
"""

from __future__ import annotations

import struct

__all__ = ["BinaryReader", "BinaryWriter", "TruncatedDataError"]


class TruncatedDataError(EOFError):
    """Erro levantado quando o arquivo termina antes do esperado."""

    def __init__(self, needed: int, available: int, offset: int, what: str = "") -> None:
        self.needed = needed
        self.available = available
        self.offset = offset
        self.what = what
        alvo = f" ao ler {what}" if what else ""
        super().__init__(
            f"dados truncados{alvo}: precisava de {needed} byte(s) no offset "
            f"{offset} (0x{offset:X}) mas restam apenas {available}"
        )


# Structs pre-compilados: struct.Struct e sensivelmente mais rapido que
# chamar struct.unpack_from com a string de formato a cada vertice.
_U8 = struct.Struct("<B")
_I8 = struct.Struct("<b")
_U16 = struct.Struct("<H")
_I16 = struct.Struct("<h")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_F32 = struct.Struct("<f")


class BinaryReader:
    """Cursor de leitura sequencial sobre um buffer de bytes.

    Trabalha sobre um objeto de bytes ja carregado em memoria. Os arquivos P3M
    e FRM sao pequenos (o maior do conjunto de testes tem menos de 200 KB),
    logo carregar tudo de uma vez e mais simples e mais rapido do que fazer I/O
    incremental.
    """

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    # ---------------------------------------------------------------- estado

    def __len__(self) -> int:
        return len(self.data)

    @property
    def remaining(self) -> int:
        """Quantidade de bytes ainda nao lidos."""
        return len(self.data) - self.pos

    @property
    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def seek(self, pos: int) -> None:
        self.pos = pos

    def skip(self, count: int) -> None:
        self.pos += count

    def tell(self) -> int:
        return self.pos

    def _need(self, count: int, what: str = "") -> None:
        if self.remaining < count:
            raise TruncatedDataError(count, self.remaining, self.pos, what)

    # --------------------------------------------------------------- escalares

    def u8(self) -> int:
        self._need(1, "u8")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def i8(self) -> int:
        self._need(1, "i8")
        (value,) = _I8.unpack_from(self.data, self.pos)
        self.pos += 1
        return value

    def u16(self) -> int:
        self._need(2, "u16")
        (value,) = _U16.unpack_from(self.data, self.pos)
        self.pos += 2
        return value

    def i16(self) -> int:
        self._need(2, "i16")
        (value,) = _I16.unpack_from(self.data, self.pos)
        self.pos += 2
        return value

    def u32(self) -> int:
        self._need(4, "u32")
        (value,) = _U32.unpack_from(self.data, self.pos)
        self.pos += 4
        return value

    def i32(self) -> int:
        self._need(4, "i32")
        (value,) = _I32.unpack_from(self.data, self.pos)
        self.pos += 4
        return value

    def f32(self) -> float:
        self._need(4, "f32")
        (value,) = _F32.unpack_from(self.data, self.pos)
        self.pos += 4
        return value

    # --------------------------------------------------------------- vetores

    def f32s(self, count: int) -> tuple[float, ...]:
        """Le `count` floats de 32 bits consecutivos."""
        size = count * 4
        self._need(size, f"{count} f32")
        values = struct.unpack_from(f"<{count}f", self.data, self.pos)
        self.pos += size
        return values

    def u16s(self, count: int) -> tuple[int, ...]:
        size = count * 2
        self._need(size, f"{count} u16")
        values = struct.unpack_from(f"<{count}H", self.data, self.pos)
        self.pos += size
        return values

    def u32s(self, count: int) -> tuple[int, ...]:
        size = count * 4
        self._need(size, f"{count} u32")
        values = struct.unpack_from(f"<{count}I", self.data, self.pos)
        self.pos += size
        return values

    def vec3(self) -> tuple[float, float, float]:
        return self.f32s(3)  # type: ignore[return-value]

    def vec2(self) -> tuple[float, float]:
        return self.f32s(2)  # type: ignore[return-value]

    # ----------------------------------------------------------------- bytes

    def bytes(self, count: int) -> bytes:
        self._need(count, f"{count} bytes")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def peek(self, count: int) -> bytes:
        """Le bytes sem avancar o cursor. Nao levanta erro se faltar dado."""
        return self.data[self.pos : self.pos + count]

    def cstring(self, size: int, encoding: str = "latin-1") -> str:
        """Le um campo de texto de tamanho fixo terminado (ou preenchido) em NUL.

        Os nomes de textura do P3M usam um buffer `char[260]` do Windows. O
        conteudo apos o primeiro NUL e lixo de memoria e deve ser descartado.
        Usamos latin-1 com `errors="replace"` porque alguns arquivos oficiais
        tem bytes invalidos nesse campo.
        """
        raw = self.bytes(size)
        end = raw.find(b"\0")
        if end >= 0:
            raw = raw[:end]
        return raw.decode(encoding, errors="replace")


class BinaryWriter:
    """Acumulador de bytes little-endian.

    Usado para montar o buffer binario do GLB e, futuramente, para reescrever
    arquivos P3M/FRM.
    """

    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def __len__(self) -> int:
        return len(self.buf)

    def tell(self) -> int:
        return len(self.buf)

    def getvalue(self) -> bytes:
        return bytes(self.buf)

    # --------------------------------------------------------------- escrita

    def u8(self, value: int) -> None:
        self.buf.append(value & 0xFF)

    def u16(self, value: int) -> None:
        self.buf += _U16.pack(value)

    def u32(self, value: int) -> None:
        self.buf += _U32.pack(value)

    def i32(self, value: int) -> None:
        self.buf += _I32.pack(value)

    def f32(self, value: float) -> None:
        self.buf += _F32.pack(value)

    def f32s(self, values) -> None:
        values = tuple(values)
        self.buf += struct.pack(f"<{len(values)}f", *values)

    def u16s(self, values) -> None:
        values = tuple(values)
        self.buf += struct.pack(f"<{len(values)}H", *values)

    def u32s(self, values) -> None:
        values = tuple(values)
        self.buf += struct.pack(f"<{len(values)}I", *values)

    def bytes(self, data: bytes) -> None:
        self.buf += data

    def cstring(self, text: str, size: int, encoding: str = "latin-1") -> None:
        """Escreve texto em campo de tamanho fixo, truncando ou preenchendo com NUL."""
        raw = text.encode(encoding, errors="replace")[:size]
        self.buf += raw + b"\0" * (size - len(raw))

    def align(self, alignment: int, pad: int = 0) -> None:
        """Preenche o buffer ate que seu tamanho seja multiplo de `alignment`."""
        extra = (-len(self.buf)) % alignment
        if extra:
            self.buf += bytes([pad]) * extra
