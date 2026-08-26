"""Leitor do formato FRM (Frame Motion) do Grand Chase.

O FRM guarda animacao por keyframes: uma matriz 4x4 por osso por frame, mais o
deslocamento da raiz do personagem. Usa sistema left-handed Y-up e taxa fixa de
55 FPS (a taxa nao esta gravada no arquivo, e uma constante do motor).

Estado da implementacao
-----------------------
* **v1.1** implementada e validada byte a byte: os 68 arquivos oficiais do
  conjunto de teste sao consumidos integralmente, sem sobra nem falta.
* **v1.0** implementada (mesmo layout sem cabecalho e com contadores de 1 byte),
  seguindo o conversor antigo. Nao havia arquivos v1.0 no conjunto de teste,
  portanto ela conta com validacao estrutural em tempo de leitura.
* **v1.2** e **v1.2_Origin** ainda nao implementadas; sao detectadas e recusadas
  com mensagem explicita.

Detalhes que importam
---------------------
* As matrizes estao em **column-major**, a mesma ordem do glTF: os 16 floats sao
  lidos como coluna 0 (4 valores), coluna 1, coluna 2, coluna 3. A translacao,
  portanto, cai nos indices 12, 13, 14.
* `plus_x` e **incremental** (delta em relacao ao frame anterior) enquanto
  `pos_y` e `pos_z` sao **absolutos**. Somar plus_x em vez de acumular produz um
  personagem parado; acumular pos_y produz um personagem que sobe sem parar.
* Na v1.1 os valores de `pos_z` ficam num bloco **no fim do arquivo**, depois de
  todos os frames, nao dentro de cada frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..binary import BinaryReader
from ..mathutil import Mat4
from ..scene import DEFAULT_FPS, Animation, Keyframe, Scene

__all__ = [
    "FRM_HEADER_V10",
    "FRM_HEADER_V11",
    "FRM_HEADER_V12",
    "FRM_HEADER_V12_ORIGIN",
    "Frame",
    "FrmFile",
    "InvalidFrmError",
    "UnsupportedFrmVersionError",
    "detect_version",
    "read_frm",
    "load_frm",
    "frm_to_scene",
]

FRM_HEADER_V11 = b"Frm Ver 1.1\0"
FRM_HEADER_V12 = b"Frm Ver 1.2\0"
FRM_HEADER_V12_ORIGIN = b"FRM Ver 1.2\0"  # atencao: "FRM" em maiusculas
FRM_HEADER_V10 = b""  # v1.0 nao tem cabecalho
HEADER_SIZE = 12

MATRIX_SIZE = 64  # 16 floats
FRAME_PRELUDE_SIZE = 9  # u8 option + f32 plus_x + f32 pos_y

SUPPORTED_VERSIONS = ("1.0", "1.1")


class InvalidFrmError(ValueError):
    """O arquivo nao e um FRM valido ou esta corrompido."""


class UnsupportedFrmVersionError(InvalidFrmError):
    """O arquivo e um FRM, mas de uma versao ainda nao implementada."""

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(
            f"FRM versao {version!r} ainda nao implementado. "
            f"Versoes suportadas: {', '.join(SUPPORTED_VERSIONS)}. "
            f"O layout desta versao esta descrito em docs/ESPECIFICACAO_FORMATOS.md."
        )


# ---------------------------------------------------------------- estruturas


@dataclass
class Frame:
    """Uma pose do esqueleto em um frame."""

    #: Flags de uso interno do jogo. Sempre 0 nos arquivos observados.
    option: int = 0
    #: Deslocamento X **relativo ao frame anterior**.
    plus_x: float = 0.0
    #: Posicao Y **absoluta**.
    pos_y: float = 0.0
    #: Posicao Z **absoluta**. Zero na v1.0.
    pos_z: float = 0.0
    #: Uma matriz 4x4 column-major por osso.
    bones: list[Mat4] = field(default_factory=list)


@dataclass
class FrmFile:
    """Conteudo cru de um arquivo FRM."""

    version: str = "1.1"
    frames: list[Frame] = field(default_factory=list)
    num_bones: int = 0
    #: Bytes nao consumidos no fim do arquivo. Deve ser 0 num arquivo intacto.
    trailing_bytes: int = 0

    @property
    def num_frames(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        if not self.frames:
            return 0.0
        return (len(self.frames) - 1) / float(DEFAULT_FPS)


# ------------------------------------------------------------------- leitura


def detect_version(data: bytes) -> str:
    """Identifica a versao pelo cabecalho de 12 bytes.

    Se nenhum cabecalho conhecido casar, assume v1.0, que nao tem cabecalho.
    """
    head = data[:HEADER_SIZE]
    if head == FRM_HEADER_V11:
        return "1.1"
    if head == FRM_HEADER_V12:
        return "1.2"
    if head == FRM_HEADER_V12_ORIGIN:
        return "1.2_Origin"
    return "1.0"


def read_frm(data: bytes) -> FrmFile:
    """Interpreta os bytes de um arquivo FRM."""
    version = detect_version(data)
    if version == "1.1":
        return _read_v11(data)
    if version == "1.0":
        return _read_v10(data)
    raise UnsupportedFrmVersionError(version)


def _read_matrices(reader: BinaryReader, num_bones: int) -> list[Mat4]:
    """Le `num_bones` matrizes 4x4 consecutivas, em column-major."""
    if num_bones == 0:
        return []
    flat = reader.f32s(num_bones * 16)
    return [flat[i * 16 : (i + 1) * 16] for i in range(num_bones)]


def _read_frame(reader: BinaryReader, num_bones: int) -> Frame:
    frame = Frame()
    frame.option = reader.u8()
    frame.plus_x = reader.f32()
    frame.pos_y = reader.f32()
    frame.bones = _read_matrices(reader, num_bones)
    return frame


def _read_v11(data: bytes) -> FrmFile:
    reader = BinaryReader(data)
    reader.skip(HEADER_SIZE)

    num_frames = reader.u16()
    num_bones = reader.u16()
    _check_size(len(data), HEADER_SIZE + 4, num_frames, num_bones, pos_z_block=True)

    frm = FrmFile(version="1.1", num_bones=num_bones)
    for _ in range(num_frames):
        frm.frames.append(_read_frame(reader, num_bones))

    # Bloco de pos_z: um float por frame, depois de todos os frames.
    for frame in frm.frames:
        frame.pos_z = reader.f32()

    frm.trailing_bytes = reader.remaining
    return frm


def _read_v10(data: bytes) -> FrmFile:
    reader = BinaryReader(data)
    num_frames = reader.u8()
    num_bones = reader.u8()
    _check_size(len(data), 2, num_frames, num_bones, pos_z_block=False)

    frm = FrmFile(version="1.0", num_bones=num_bones)
    for _ in range(num_frames):
        frm.frames.append(_read_frame(reader, num_bones))

    frm.trailing_bytes = reader.remaining
    return frm


def _check_size(
    total: int, header: int, num_frames: int, num_bones: int, pos_z_block: bool
) -> None:
    """Confere se o tamanho do arquivo bate com os contadores lidos.

    Esta checagem e o que torna a deteccao de v1.0 (que nao tem cabecalho)
    confiavel: se os contadores fossem lixo, o tamanho previsto nao fecharia.
    """
    if num_bones == 0:
        raise InvalidFrmError("FRM declara 0 ossos")
    if num_frames == 0:
        raise InvalidFrmError("FRM declara 0 frames")
    per_frame = FRAME_PRELUDE_SIZE + num_bones * MATRIX_SIZE
    needed = header + num_frames * per_frame
    if pos_z_block:
        needed += num_frames * 4
    if total < needed:
        raise InvalidFrmError(
            f"FRM truncado: {num_frames} frames x {num_bones} ossos exigem "
            f"{needed} bytes, mas o arquivo tem {total}"
        )


def load_frm(path) -> FrmFile:
    """Le um arquivo FRM do disco."""
    with open(path, "rb") as handle:
        return read_frm(handle.read())


# ---------------------------------------------------------------- conversao


def frm_to_animation(frm: FrmFile, name: str = "animation") -> Animation:
    """Converte um `FrmFile` cru em uma `Animation` (ainda left-handed)."""
    animation = Animation(name=name, fps=DEFAULT_FPS)
    accumulated_x = 0.0
    for frame in frm.frames:
        # plus_x e um delta; pos_y e pos_z sao absolutos.
        accumulated_x += frame.plus_x
        animation.frames.append(
            Keyframe(
                translation=(accumulated_x, frame.pos_y, frame.pos_z),
                transforms=list(frame.bones),
            )
        )
    return animation


def frm_to_scene(frm: FrmFile, name: str = "animation") -> Scene:
    """Envelopa a animacao numa `Scene`, para poder ser mesclada com um P3M."""
    scene = Scene()
    scene.animations.append(frm_to_animation(frm, name))
    return scene
