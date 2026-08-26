"""Matematica 3D minima, sem dependencias externas.

Convencoes adotadas neste projeto
---------------------------------
* Vetores sao tuplas `(x, y, z)` de floats. Sao imutaveis de proposito: evita
  aliasing acidental entre vertices e joints.
* Matrizes 4x4 sao tuplas de 16 floats em ordem **column-major**, exatamente a
  mesma ordem usada pelo FRM e pelo glTF. O elemento da linha `r` e coluna `c`
  fica no indice `c * 4 + r`.

  Indices:
      ( 0  4  8 12 )
      ( 1  5  9 13 )
      ( 2  6 10 14 )
      ( 3  7 11 15 )

  Ou seja, a translacao de uma matriz de transformacao fica nos indices 12,13,14.
* Quaternions sao tuplas `(x, y, z, w)`, a ordem exigida pelo glTF.

Nao usamos numpy: o volume de dados e pequeno (milhares de vertices, nao
milhoes) e manter zero dependencias torna o empacotamento para Windows e Linux
muito mais simples.
"""

from __future__ import annotations

import math

__all__ = [
    "Vec3",
    "Mat4",
    "Quat",
    "vec3_add",
    "vec3_sub",
    "vec3_scale",
    "vec3_length",
    "vec3_normalize",
    "vec3_flip_z",
    "vec3_lerp",
    "MAT4_IDENTITY",
    "mat4_multiply",
    "mat4_translation",
    "mat4_from_translation",
    "mat4_from_trs",
    "mat4_flip_z_conjugate",
    "mat4_to_quaternion",
    "quat_normalize",
    "quat_slerp",
    "FLIP_Z",
]

Vec3 = tuple[float, float, float]
Mat4 = tuple[float, ...]
Quat = tuple[float, float, float, float]


# --------------------------------------------------------------------- vetores


def vec3_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec3_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec3_scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def vec3_length(a: Vec3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def vec3_normalize(a: Vec3) -> Vec3:
    """Normaliza o vetor. Retorna (0,0,0) se o comprimento for degenerado.

    Necessario porque varios P3M oficiais tem normais nao unitarias (medimos
    comprimentos de 0.0 a 3.98 no conjunto de teste) e o glTF exige normais
    unitarias.
    """
    length = vec3_length(a)
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    inv = 1.0 / length
    return (a[0] * inv, a[1] * inv, a[2] * inv)


def vec3_flip_z(a: Vec3) -> Vec3:
    """Converte entre sistemas de coordenadas left-handed e right-handed."""
    return (a[0], a[1], -a[2])


def vec3_lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Interpolacao linear entre dois vetores. Usada ao reamostrar animacoes."""
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


# -------------------------------------------------------------------- matrizes

MAT4_IDENTITY: Mat4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)

#: Matriz de espelhamento no eixo Z, diag(1, 1, -1, 1).
#: Leva o sistema left-handed Y-up do Grand Chase para o right-handed do glTF.
#: E a sua propria inversa (FLIP_Z * FLIP_Z == identidade).
FLIP_Z: Mat4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, -1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def mat4_multiply(a: Mat4, b: Mat4) -> Mat4:
    """Produto matricial `a * b` para matrizes column-major."""
    out = [0.0] * 16
    for c in range(4):
        bc0 = b[c * 4 + 0]
        bc1 = b[c * 4 + 1]
        bc2 = b[c * 4 + 2]
        bc3 = b[c * 4 + 3]
        for r in range(4):
            out[c * 4 + r] = (
                a[0 * 4 + r] * bc0
                + a[1 * 4 + r] * bc1
                + a[2 * 4 + r] * bc2
                + a[3 * 4 + r] * bc3
            )
    return tuple(out)


def mat4_translation(m: Mat4) -> Vec3:
    """Extrai o componente de translacao da matriz."""
    return (m[12], m[13], m[14])


def mat4_from_translation(t: Vec3) -> Mat4:
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        t[0], t[1], t[2], 1.0,
    )


def mat4_from_trs(
    translation: Vec3,
    rotation: Quat,
    scale: Vec3 = (1.0, 1.0, 1.0),
) -> Mat4:
    """Monta uma matriz column-major a partir de translacao, rotacao e escala.

    E a operacao inversa de `mat4_to_quaternion` (mais a translacao), usada ao
    importar glTF: o glTF guarda os nos e os canais de animacao como TRS
    separados, e o FRM quer uma matriz 4x4 por osso.

    A ordem aplicada e a do glTF: primeiro escala, depois rotacao, depois
    translacao (`M = T * R * S`).
    """
    x, y, z, w = rotation
    sx, sy, sz = scale

    # Matriz de rotacao 3x3 a partir do quaternion.
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    r00 = 1.0 - 2.0 * (yy + zz)
    r01 = 2.0 * (xy - wz)
    r02 = 2.0 * (xz + wy)
    r10 = 2.0 * (xy + wz)
    r11 = 1.0 - 2.0 * (xx + zz)
    r12 = 2.0 * (yz - wx)
    r20 = 2.0 * (xz - wy)
    r21 = 2.0 * (yz + wx)
    r22 = 1.0 - 2.0 * (xx + yy)

    # Column-major: cada grupo de 4 e uma coluna. A escala multiplica a coluna
    # correspondente ao seu eixo.
    return (
        r00 * sx, r10 * sx, r20 * sx, 0.0,
        r01 * sy, r11 * sy, r21 * sy, 0.0,
        r02 * sz, r12 * sz, r22 * sz, 0.0,
        translation[0], translation[1], translation[2], 1.0,
    )


def mat4_flip_z_conjugate(m: Mat4) -> Mat4:
    """Reexpressa a transformacao `m` no sistema de coordenadas espelhado em Z.

    Calcula `S * m * S` com `S = diag(1, 1, -1, 1)`. Como `S` e involutiva,
    `S == S^-1`, e a conta equivale a negar todo elemento cujo indice de linha
    OU de coluna seja 2 (mas nao ambos).

    Isso e o que transforma corretamente uma matriz de rotacao left-handed em
    sua equivalente right-handed: apenas negar Z da translacao nao basta,
    porque a parte rotacional tambem precisa ser conjugada.
    """
    out = list(m)
    for c in range(4):
        for r in range(4):
            if (r == 2) != (c == 2):
                out[c * 4 + r] = -out[c * 4 + r]
    return tuple(out)


def mat4_to_quaternion(m: Mat4) -> Quat:
    """Extrai a rotacao de uma matriz 4x4 como quaternion `(x, y, z, w)`.

    A escala eventual embutida na matriz e removida normalizando as colunas da
    submatriz 3x3. Se a matriz for degenerada (o FRM v1.2 tem bones zerados em
    varios arquivos oficiais) devolve a identidade `(0, 0, 0, 1)`, que e o
    comportamento seguro para uma animacao.
    """
    # Colunas da submatriz 3x3, que sao os eixos base transformados.
    cx = (m[0], m[1], m[2])
    cy = (m[4], m[5], m[6])
    cz = (m[8], m[9], m[10])

    lx = vec3_length(cx)
    ly = vec3_length(cy)
    lz = vec3_length(cz)
    if lx < 1e-9 or ly < 1e-9 or lz < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)

    cx = vec3_scale(cx, 1.0 / lx)
    cy = vec3_scale(cy, 1.0 / ly)
    cz = vec3_scale(cz, 1.0 / lz)

    # Uma matriz com determinante negativo contem um espelhamento, que nao pode
    # ser representado por um quaternion. Absorvemos o sinal no eixo X, mesma
    # estrategia da glam (usada pelo conversor antigo).
    det = (
        cx[0] * (cy[1] * cz[2] - cy[2] * cz[1])
        - cy[0] * (cx[1] * cz[2] - cx[2] * cz[1])
        + cz[0] * (cx[1] * cy[2] - cx[2] * cy[1])
    )
    if det < 0.0:
        cx = vec3_scale(cx, -1.0)

    # m[linha][coluna] da rotacao normalizada
    m00, m10, m20 = cx
    m01, m11, m21 = cy
    m02, m12, m22 = cz

    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s

    return quat_normalize((x, y, z, w))


def quat_normalize(q: Quat) -> Quat:
    length = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if length < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    inv = 1.0 / length
    return (q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv)


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Interpolacao esferica entre dois quaternions.

    Necessaria ao reamostrar animacoes importadas de glTF: o Blender exporta
    keyframes nos instantes que o animador criou, e o FRM exige uma pose a cada
    1/55 s. Interpolar quaternion componente a componente encurta o arco e
    produz variacao de velocidade visivel; slerp mantem velocidade angular
    constante.

    Segue a convencao do glTF de negar um dos quaternions quando o produto
    interno e negativo, para percorrer o caminho mais curto.
    """
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]

    if dot < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot

    # Quase paralelos: slerp fica numericamente instavel, e lerp e equivalente.
    if dot > 0.9995:
        return quat_normalize(
            (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
                a[3] + (b[3] - a[3]) * t,
            )
        )

    theta_0 = math.acos(max(-1.0, min(1.0, dot)))
    theta = theta_0 * t
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)

    s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0

    return quat_normalize(
        (
            a[0] * s0 + b[0] * s1,
            a[1] * s0 + b[1] * s1,
            a[2] * s0 + b[2] * s1,
            a[3] * s0 + b[3] * s1,
        )
    )
