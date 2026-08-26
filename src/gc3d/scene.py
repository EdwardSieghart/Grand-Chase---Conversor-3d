"""Representacao intermediaria de cena 3D.

Todo conversor deste projeto passa por aqui:

    P3M ---importa---> Scene ---exporta---> GLB
    FRM ---importa---> Scene

Manter um formato neutro no meio significa que adicionar um novo formato de
entrada ou de saida custa um modulo, nao N x M conversores.

Sistema de coordenadas
----------------------
Uma `Scene` recem importada de P3M/FRM esta em **left-handed Y-up**, o sistema
nativo do Grand Chase (DirectX). O glTF exige **right-handed Y-up**. A conversao
e feita por `Scene.to_right_handed()`, que deve ser chamada uma unica vez, na
exportacao. Ela e explicita e nao acontece no import para que a cena continue
fiel ao arquivo original enquanto estiver em memoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mathutil import (
    Mat4,
    Vec3,
    mat4_flip_z_conjugate,
    vec3_add,
    vec3_flip_z,
    vec3_normalize,
)

__all__ = [
    "Joint",
    "Vertex",
    "Mesh",
    "Keyframe",
    "Animation",
    "Scene",
    "DEFAULT_FPS",
    "NO_JOINT",
]

#: Taxa de amostragem das animacoes do Grand Chase. Nao esta gravada no arquivo
#: FRM; e uma constante do motor do jogo.
DEFAULT_FPS = 55

#: Sentinela para "vertice sem joint associado".
NO_JOINT = -1


@dataclass
class Joint:
    """Um osso do esqueleto. Suporta apenas translacao no bind pose.

    O Grand Chase guarda o esqueleto em duas listas (PositionBones e
    AngleBones). Um `Joint` aqui e o resultado do achatamento das duas: cada
    joint corresponde a um AngleBone, e sua `translation` vem do PositionBone
    que o tem como filho. Ver `formats/p3m.py`.
    """

    name: str = ""
    #: Translacao relativa ao joint pai.
    translation: Vec3 = (0.0, 0.0, 0.0)
    #: Indice do pai no `Scene.skeleton`, ou None se for raiz.
    parent: int | None = None
    #: Indices dos filhos no `Scene.skeleton`.
    children: list[int] = field(default_factory=list)


@dataclass
class Vertex:
    """Vertice com dados de skinning."""

    position: Vec3 = (0.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 0.0)
    uv: tuple[float, float] = (0.0, 0.0)
    #: Indice do joint influente em `Scene.skeleton`, ou `NO_JOINT`.
    joint: int = NO_JOINT
    #: Peso da influencia. O P3M usa skinning rigido (peso 1.0) na maioria dos
    #: casos, mas alguns arquivos oficiais trazem 0.5.
    weight: float = 1.0


@dataclass
class Mesh:
    """Geometria de um objeto, com um unico material/textura."""

    name: str = ""
    vertices: list[Vertex] = field(default_factory=list)
    #: Buffer de indices; cada trio consecutivo forma um triangulo.
    indices: list[int] = field(default_factory=list)
    #: Nome do arquivo de textura declarado no P3M (frequentemente vazio).
    texture_name: str = ""

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


@dataclass
class Keyframe:
    """Pose completa do esqueleto em um instante."""

    #: Translacao aplicada ao esqueleto inteiro (movimento da raiz).
    translation: Vec3 = (0.0, 0.0, 0.0)
    #: Uma matriz por joint, na mesma ordem de `Scene.skeleton`.
    transforms: list[Mat4] = field(default_factory=list)


@dataclass
class Animation:
    """Sequencia de keyframes amostrada em intervalos regulares."""

    name: str = ""
    frames: list[Keyframe] = field(default_factory=list)
    fps: int = DEFAULT_FPS

    @property
    def duration(self) -> float:
        """Duracao em segundos."""
        if not self.frames:
            return 0.0
        return (len(self.frames) - 1) / float(self.fps)

    def times(self) -> list[float]:
        """Instante de cada keyframe, em segundos."""
        step = 1.0 / float(self.fps)
        return [i * step for i in range(len(self.frames))]

    def joint_transforms(self, joint_index: int) -> list[Mat4]:
        """Todas as matrizes de um joint ao longo do tempo."""
        return [
            frame.transforms[joint_index]
            for frame in self.frames
            if joint_index < len(frame.transforms)
        ]


@dataclass
class Scene:
    """Malhas, esqueleto e animacoes que serao exportados juntos."""

    meshes: list[Mesh] = field(default_factory=list)
    skeleton: list[Joint] = field(default_factory=list)
    animations: list[Animation] = field(default_factory=list)
    #: Sistema de coordenadas atual. Serve para impedir dupla conversao.
    right_handed: bool = False
    #: Quantos vertices vieram sem osso associado. Informativo, para relatorio.
    unskinned_vertices: int = 0

    # ------------------------------------------------------------- consultas

    def joint_world_translation(self, index: int) -> Vec3:
        """Translacao acumulada do joint em relacao a origem da cena.

        Como os joints so tem translacao no bind pose, basta somar as
        translacoes locais subindo pela cadeia de pais.
        """
        total = (0.0, 0.0, 0.0)
        current: int | None = index
        guard = 0
        limit = len(self.skeleton) + 1
        while current is not None:
            joint = self.skeleton[current]
            total = vec3_add(total, joint.translation)
            current = joint.parent
            guard += 1
            if guard > limit:  # protecao contra hierarquia ciclica corrompida
                break
        return total

    def world_translations(self) -> list[Vec3]:
        """Translacao mundial de todos os joints, calculada de uma vez."""
        return [self.joint_world_translation(i) for i in range(len(self.skeleton))]

    def root_joints(self) -> list[int]:
        return [i for i, j in enumerate(self.skeleton) if j.parent is None]

    @property
    def vertex_count(self) -> int:
        return sum(len(m.vertices) for m in self.meshes)

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes)

    # ----------------------------------------------------------- composicao

    def merge(self, other: Scene) -> Scene:
        """Incorpora outra cena nesta. Usado para juntar um P3M com varios FRM.

        O esqueleto da primeira cena que tiver um prevalece: as animacoes FRM
        referenciam bones por indice, e e o P3M que define a hierarquia real.
        """
        if not self.skeleton:
            self.skeleton = other.skeleton
        self.meshes.extend(other.meshes)
        self.animations.extend(other.animations)
        return self

    # -------------------------------------------------------- normalizacao

    def normalize_normals(self) -> int:
        """Torna unitarias todas as normais. Devolve quantas foram corrigidas.

        O glTF exige normais unitarias e varios P3M oficiais nao cumprem isso.
        """
        fixed = 0
        for mesh in self.meshes:
            for vertex in mesh.vertices:
                original = vertex.normal
                unit = vec3_normalize(original)
                if unit != original:
                    vertex.normal = unit
                    fixed += 1
        return fixed

    def _flip_z(self) -> None:
        """Espelha o eixo Z de toda a cena, trocando a mao do sistema.

        Sao quatro operacoes, e todas as quatro sao necessarias:

        1. Negar Z de posicoes, normais e translacoes de joint.
        2. Inverter a ordem de enrolamento (winding) dos triangulos, porque
           espelhar um eixo inverte a orientacao das faces e elas ficariam com a
           normal geometrica para dentro.
        3. Negar Z da translacao de raiz de cada keyframe.
        4. Conjugar cada matriz de animacao com `S = diag(1,1,-1)`, isto e
           `M' = S * M * S`. Negar apenas a translacao seria insuficiente: a
           parte rotacional tambem muda de mao.

        A operacao e a sua propria inversa, e por isso serve tanto para
        left-handed -> right-handed quanto para o contrario.
        """
        for mesh in self.meshes:
            for vertex in mesh.vertices:
                vertex.position = vec3_flip_z(vertex.position)
                vertex.normal = vec3_flip_z(vertex.normal)
            indices = mesh.indices
            for i in range(0, len(indices) - 2, 3):
                indices[i + 1], indices[i + 2] = indices[i + 2], indices[i + 1]

        for joint in self.skeleton:
            joint.translation = vec3_flip_z(joint.translation)

        for animation in self.animations:
            for frame in animation.frames:
                frame.translation = vec3_flip_z(frame.translation)
                frame.transforms = [
                    mat4_flip_z_conjugate(m) for m in frame.transforms
                ]

    def to_right_handed(self) -> Scene:
        """Converte de left-handed (Grand Chase) para right-handed (glTF).

        Idempotente: chamar duas vezes nao corrompe a cena.
        """
        if self.right_handed:
            return self
        self._flip_z()
        self.right_handed = True
        return self

    def to_left_handed(self) -> Scene:
        """Converte de right-handed (glTF) para left-handed (Grand Chase).

        E o caminho usado na conversao inversa, ao gravar P3M e FRM a partir de
        um glTF. Idempotente.
        """
        if not self.right_handed:
            return self
        self._flip_z()
        self.right_handed = False
        return self

    # -------------------------------------------------------------- relatorio

    def summary(self) -> str:
        parts = [
            f"{len(self.meshes)} malha(s)",
            f"{self.vertex_count} vertices",
            f"{self.triangle_count} triangulos",
            f"{len(self.skeleton)} joints",
            f"{len(self.animations)} animacao(oes)",
        ]
        total_frames = sum(len(a.frames) for a in self.animations)
        if total_frames:
            parts.append(f"{total_frames} keyframes")
        return ", ".join(parts)
