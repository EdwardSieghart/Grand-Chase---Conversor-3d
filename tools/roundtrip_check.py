#!/usr/bin/env python3
"""Validacao de ida e volta: P3M/FRM -> GLB -> P3M/FRM.

Converte cada modelo para GLB, converte de volta para os formatos do jogo e
compara o resultado com o original. E a prova de que as duas direcoes sao
consistentes entre si.

O que e comparado, e a tolerancia esperada:

* numero de ossos, vertices e triangulos — igualdade exata
* indices de face — igualdade exata
* joint de cada vertice — igualdade exata
* posicao de vertice, UV, translacao de joint — erro de arredondamento f32
* rotacao por osso e frame — comparada como quaternion, porque e essa a forma
  que atravessa o glTF; `q` e `-q` sao a mesma rotacao e sao tratados como iguais

O que **nao** volta identico, por decisao de projeto:

* `numPositionBones` — a escrita usa um PositionBone por AngleBone (1:1),
  enquanto os arquivos originais as vezes compartilham um PositionBone entre dois
  AngleBones raiz. O indice de osso absoluto muda junto, mas o *joint* resolvido
  e o mesmo, e e ele que o jogo usa.
* matrizes de osso zeradas (0.08% dos casos) voltam como identidade.

Uso:
    python3 tools/roundtrip_check.py "/caminho/GRAND CHASE" [mais pastas...]
    python3 tools/roundtrip_check.py --anim-dir "/caminho/ANIM" "/caminho/Models"
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (os.path.join(_ROOT, "src"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from gc3d import ConvertOptions, convert_model, convert_to_gc  # noqa: E402
from gc3d.formats import frm as frm_format  # noqa: E402
from gc3d.formats import p3m as p3m_format  # noqa: E402
from gc3d.mathutil import mat4_to_quaternion  # noqa: E402

#: Tolerancia para valores que passaram por f32 mais aritmetica de conversao.
TOLERANCE = 1e-4


def quaternion_delta(a, b) -> float:
    """Distancia entre duas rotacoes, tratando `q` e `-q` como iguais."""
    same = max(abs(x - y) for x, y in zip(a, b))
    negated = max(abs(x + y) for x, y in zip(a, b))
    return min(same, negated)


def compare_models(original_path: str, rebuilt_path: str) -> list[str]:
    """Compara dois P3M. Devolve a lista de diferencas relevantes."""
    diffs: list[str] = []
    a = p3m_format.load_p3m(original_path)
    b = p3m_format.load_p3m(rebuilt_path)

    if a.num_angle_bones != b.num_angle_bones:
        diffs.append(
            f"ossos (angle): {a.num_angle_bones} vs {b.num_angle_bones}"
        )
    if len(a.skin_vertices) != len(b.skin_vertices):
        diffs.append(
            f"vertices: {len(a.skin_vertices)} vs {len(b.skin_vertices)}"
        )
        return diffs
    if len(a.faces) != len(b.faces):
        diffs.append(f"faces: {len(a.faces)} vs {len(b.faces)}")
        return diffs
    if a.faces != b.faces:
        diffs.append("indices de face diferem")

    # O joint resolvido precisa ser identico; o indice absoluto muda de proposito.
    joints_a = [v.bone_index - a.num_position_bones for v in a.skin_vertices]
    joints_b = [v.bone_index - b.num_position_bones for v in b.skin_vertices]
    if joints_a != joints_b:
        divergent = sum(1 for x, y in zip(joints_a, joints_b) if x != y)
        diffs.append(f"joint de {divergent} vertice(s) mudou")

    worst_position = 0.0
    worst_uv = 0.0
    for va, vb in zip(a.skin_vertices, b.skin_vertices):
        worst_position = max(
            worst_position, max(abs(x - y) for x, y in zip(va.position, vb.position))
        )
        worst_uv = max(worst_uv, max(abs(x - y) for x, y in zip(va.uv, vb.uv)))
    if worst_position > TOLERANCE:
        diffs.append(f"posicao de vertice difere em ate {worst_position:.6g}")
    if worst_uv > TOLERANCE:
        diffs.append(f"UV difere em ate {worst_uv:.6g}")

    skeleton_a = p3m_format.build_joints(a.position_bones, a.angle_bones)
    skeleton_b = p3m_format.build_joints(b.position_bones, b.angle_bones)
    if [j.parent for j in skeleton_a] != [j.parent for j in skeleton_b]:
        diffs.append("hierarquia de pais mudou")
    if [j.children for j in skeleton_a] != [j.children for j in skeleton_b]:
        diffs.append("hierarquia de filhos mudou")
    worst_translation = max(
        (
            max(abs(x - y) for x, y in zip(ja.translation, jb.translation))
            for ja, jb in zip(skeleton_a, skeleton_b)
        ),
        default=0.0,
    )
    if worst_translation > TOLERANCE:
        diffs.append(
            f"translacao de joint difere em ate {worst_translation:.6g}"
        )

    return diffs


def compare_animations(original_path: str, rebuilt_path: str) -> list[str]:
    """Compara dois FRM. Devolve a lista de diferencas relevantes."""
    diffs: list[str] = []
    a = frm_format.load_frm(original_path)
    b = frm_format.load_frm(rebuilt_path)

    if a.num_frames != b.num_frames:
        diffs.append(f"frames: {a.num_frames} vs {b.num_frames}")
        return diffs
    if a.num_bones != b.num_bones:
        diffs.append(f"ossos: {a.num_bones} vs {b.num_bones}")
        return diffs

    animation_a = frm_format.frm_to_animation(a, "a")
    animation_b = frm_format.frm_to_animation(b, "b")

    worst_translation = 0.0
    for fa, fb in zip(animation_a.frames, animation_b.frames):
        worst_translation = max(
            worst_translation,
            max(abs(x - y) for x, y in zip(fa.translation, fb.translation)),
        )
    if worst_translation > TOLERANCE:
        diffs.append(
            f"translacao de raiz difere em ate {worst_translation:.6g}"
        )

    worst_rotation = 0.0
    degenerate = 0
    for fa, fb in zip(animation_a.frames, animation_b.frames):
        for ma, mb in zip(fa.transforms, fb.transforms):
            # Matriz zerada no original volta como identidade; e esperado.
            column_lengths = [
                math.sqrt(ma[i * 4] ** 2 + ma[i * 4 + 1] ** 2 + ma[i * 4 + 2] ** 2)
                for i in range(3)
            ]
            if max(column_lengths) < 1e-9:
                degenerate += 1
                continue
            worst_rotation = max(
                worst_rotation,
                quaternion_delta(mat4_to_quaternion(ma), mat4_to_quaternion(mb)),
            )
    if worst_rotation > TOLERANCE:
        diffs.append(f"rotacao difere em ate {worst_rotation:.6g}")

    return diffs


def gather(roots: list[str], extension: str) -> list[str]:
    found = []
    for root in roots:
        for directory, _, files in os.walk(root):
            for name in files:
                if name.lower().endswith(extension):
                    found.append(os.path.join(directory, name))
    return sorted(found)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", help="pastas com arquivos .p3m")
    parser.add_argument(
        "--anim-dir",
        default=None,
        help="pasta com .frm; para cada modelo usa a primeira animacao compativel",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="testa apenas os N primeiros modelos"
    )
    args = parser.parse_args(argv[1:])

    models = gather(args.roots, ".p3m")
    if args.limit:
        models = models[: args.limit]

    animations_by_bones: dict[int, str] = {}
    if args.anim_dir:
        for path in gather([args.anim_dir], ".frm"):
            try:
                count = frm_format.load_frm(path).num_bones
            except Exception:  # noqa: BLE001
                continue
            animations_by_bones.setdefault(count, path)

    print("Grand Chase 3D Importer — validacao de ida e volta")
    print(f"modelos: {len(models)}")
    if animations_by_bones:
        print(
            f"animacoes de referencia: {len(animations_by_bones)} "
            f"(uma por contagem de ossos: {sorted(animations_by_bones)})"
        )
    print()

    ok = 0
    failures: list[str] = []
    animation_tested = 0
    animation_ok = 0

    with tempfile.TemporaryDirectory() as tmp:
        for index, model_path in enumerate(models):
            name = os.path.basename(model_path)
            stem = os.path.splitext(name)[0]

            try:
                bones = p3m_format.load_p3m(model_path).num_angle_bones
            except Exception as error:  # noqa: BLE001
                failures.append(f"{name}: leitura falhou: {error}")
                continue

            animation_path = animations_by_bones.get(bones)
            animations = [animation_path] if animation_path else []

            glb_path = os.path.join(tmp, f"{index}.glb")
            forward = convert_model(
                model_path,
                glb_path,
                animations,
                ConvertOptions(embed_texture=False),
            )
            if not forward.ok:
                failures.append(f"{name}: ida falhou: {forward.error}")
                continue

            back_dir = os.path.join(tmp, f"back{index}")
            backward = convert_to_gc(glb_path, back_dir)
            if not backward.ok:
                failures.append(f"{name}: volta falhou: {backward.error}")
                continue

            rebuilt_model = os.path.join(back_dir, f"{index}.p3m")
            if not os.path.isfile(rebuilt_model):
                failures.append(f"{name}: P3M de volta nao foi gravado")
                continue

            diffs = compare_models(model_path, rebuilt_model)
            if diffs:
                failures.append(f"{name}: {'; '.join(diffs)}")
            else:
                ok += 1

            if animation_path:
                animation_stem = os.path.splitext(os.path.basename(animation_path))[0]
                rebuilt_animation = os.path.join(
                    back_dir, f"{index}_{animation_stem}.frm"
                )
                if os.path.isfile(rebuilt_animation):
                    animation_tested += 1
                    animation_diffs = compare_animations(
                        animation_path, rebuilt_animation
                    )
                    if animation_diffs:
                        failures.append(
                            f"{animation_stem}.frm (via {name}): "
                            f"{'; '.join(animation_diffs)}"
                        )
                    else:
                        animation_ok += 1

    print(f"modelos identicos apos ida e volta: {ok}/{len(models)}")
    if animation_tested:
        print(f"animacoes identicas apos ida e volta: {animation_ok}/{animation_tested}")
    print()

    if failures:
        print(f"{len(failures)} DIVERGENCIA(S):")
        for failure in failures[:40]:
            print(f"  - {failure}")
        if len(failures) > 40:
            print(f"  ... e mais {len(failures) - 40}")
        return 1
    print("tudo passou")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
