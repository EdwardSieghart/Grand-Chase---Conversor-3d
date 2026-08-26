#!/usr/bin/env python3
"""Validacao em massa sobre uma colecao de arquivos do Grand Chase.

Percorre pastas procurando .p3m, .frm e .dds, tenta processar tudo e imprime um
relatorio com contagens e a lista de falhas. E a ferramenta que gerou os numeros
de `docs/VALIDACAO.md`, e serve para revalidar depois de qualquer mudanca.

Uso:
    python3 tools/validate_all.py "/caminho/GRAND CHASE" [mais pastas...]

    # incluindo a checagem cruzada do decodificador de DDS contra o Pillow
    # (so roda se Pillow e numpy estiverem instalados; nao sao necessarios para
    # usar o conversor)
    python3 tools/validate_all.py --cross-check "/caminho/GRAND CHASE"

    # gerando os GLB num diretorio, para depois validar no Blender
    python3 tools/validate_all.py --out-dir /tmp/glb "/caminho/GRAND CHASE"

Codigo de saida 0 se tudo passou, 1 se houve qualquer falha.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (os.path.join(_ROOT, "src"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from glb_inspect import Glb, validate  # noqa: E402

from gc3d import ConvertOptions, convert_model  # noqa: E402
from gc3d.formats import frm as frm_format  # noqa: E402
from gc3d.formats import p3m as p3m_format  # noqa: E402
from gc3d.textures import dds_to_png, read_dds  # noqa: E402


def gather(roots: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"p3m": [], "frm": [], "dds": []}
    for root in roots:
        for directory, _, files in os.walk(root):
            for name in files:
                extension = os.path.splitext(name)[1].lower().lstrip(".")
                if extension in found:
                    found[extension].append(os.path.join(directory, name))
    for key in found:
        found[key].sort()
    return found


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def check_p3m(paths: list[str]) -> tuple[int, list[str], dict]:
    ok = 0
    failures: list[str] = []
    stats = {
        "encodings": collections.Counter(),
        "versions": collections.Counter(),
        "trailing": 0,
        "truncated_mesh": 0,
        "weights_not_one": 0,
        "bones": collections.Counter(),
    }
    for path in paths:
        try:
            model = p3m_format.load_p3m(path)
        except Exception as error:  # noqa: BLE001
            failures.append(f"{os.path.basename(path)}: {type(error).__name__}: {error}")
            continue
        ok += 1
        stats["encodings"][model.bone_index_encoding] += 1
        stats["versions"][model.version] += 1
        stats["bones"][model.num_angle_bones] += 1
        if model.trailing_bytes:
            stats["trailing"] += 1
        if model.mesh_vertices_truncated:
            stats["truncated_mesh"] += 1
        if any(abs(v.weight - 1.0) > 1e-6 for v in model.skin_vertices):
            stats["weights_not_one"] += 1
    return ok, failures, stats


def check_frm(paths: list[str]) -> tuple[int, list[str], dict]:
    ok = 0
    failures: list[str] = []
    stats = {
        "versions": collections.Counter(),
        "bones": collections.Counter(),
        "exact": 0,
        "frames": 0,
    }
    for path in paths:
        try:
            animation = frm_format.load_frm(path)
        except Exception as error:  # noqa: BLE001
            failures.append(f"{os.path.basename(path)}: {type(error).__name__}: {error}")
            continue
        ok += 1
        stats["versions"][animation.version] += 1
        stats["bones"][animation.num_bones] += 1
        stats["frames"] += animation.num_frames
        if animation.trailing_bytes == 0:
            stats["exact"] += 1
    return ok, failures, stats


def check_dds(paths: list[str], cross_check: bool) -> tuple[int, list[str], dict]:
    ok = 0
    failures: list[str] = []
    stats: dict = {"formats": collections.Counter(), "compared": 0, "worst_error": 0}

    reference = None
    if cross_check:
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401

            reference = True
        except ImportError:
            print("  (Pillow/numpy ausentes: comparacao cruzada desativada)")

    for path in paths:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            image = read_dds(data)
            png = dds_to_png(data)
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception as error:  # noqa: BLE001
            failures.append(f"{os.path.basename(path)}: {type(error).__name__}: {error}")
            continue
        ok += 1
        stats["formats"][image.source_format] += 1

        if reference:
            import numpy as np
            from PIL import Image

            try:
                expected = Image.open(path).convert("RGBA")
            except Exception:  # noqa: BLE001
                continue
            if expected.size != (image.width, image.height):
                failures.append(
                    f"{os.path.basename(path)}: tamanho "
                    f"{(image.width, image.height)} != {expected.size} (Pillow)"
                )
                continue
            mine = np.frombuffer(bytes(image.pixels), dtype=np.uint8).astype(np.int16)
            theirs = np.asarray(expected, dtype=np.int16).reshape(-1)
            worst = int(np.abs(mine - theirs).max())
            stats["compared"] += 1
            stats["worst_error"] = max(stats["worst_error"], worst)
    return ok, failures, stats


def check_conversion(paths: list[str], out_dir: str | None) -> tuple[int, list[str], dict]:
    ok = 0
    failures: list[str] = []
    stats = {"invalid_glb": 0, "static": 0, "bytes": 0}

    temporary = None
    if out_dir is None:
        temporary = tempfile.TemporaryDirectory()
        out_dir = temporary.name
    else:
        os.makedirs(out_dir, exist_ok=True)

    try:
        for path in paths:
            stem = os.path.splitext(os.path.basename(path))[0]
            output = os.path.join(out_dir, stem + ".glb")
            result = convert_model(
                path,
                output,
                [],
                ConvertOptions(embed_texture=True, texture_dirs=[os.path.dirname(path)]),
            )
            if not result.ok:
                failures.append(f"{os.path.basename(path)}: {result.error}")
                continue
            ok += 1
            stats["bytes"] += result.bytes_written
            if any("malha estatica" in w for w in result.warnings):
                stats["static"] += 1
            problems = validate(Glb(output))
            if problems:
                stats["invalid_glb"] += 1
                failures.append(f"{os.path.basename(path)}: GLB invalido: {problems[:2]}")
    finally:
        if temporary is not None:
            temporary.cleanup()
    return ok, failures, stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", help="pastas a percorrer")
    parser.add_argument(
        "--cross-check",
        action="store_true",
        help="compara o decodificador de DDS com o Pillow (requer Pillow e numpy)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="grava os GLB nesta pasta em vez de usar um diretorio temporario",
    )
    args = parser.parse_args(argv[1:])

    files = gather(args.roots)
    print("Grand Chase 3D Importer — validacao em massa")
    print(f"pastas: {', '.join(args.roots)}")
    print(
        f"encontrados: {len(files['p3m'])} .p3m, {len(files['frm'])} .frm, "
        f"{len(files['dds'])} .dds"
    )

    all_failures: list[str] = []

    section("1. Leitura de P3M")
    ok, failures, stats = check_p3m(files["p3m"])
    print(f"lidos: {ok}/{len(files['p3m'])}")
    print(f"versoes: {dict(stats['versions'])}")
    print(f"codificacao do indice de osso: {dict(stats['encodings'])}")
    print(f"numero de ossos observado: {sorted(stats['bones'])}")
    print(f"com bytes extras no fim: {stats['trailing']}")
    print(f"com bloco MeshVertex truncado: {stats['truncated_mesh']}")
    print(f"com peso diferente de 1.0: {stats['weights_not_one']}")
    all_failures += failures

    section("2. Leitura de FRM")
    ok, failures, stats = check_frm(files["frm"])
    print(f"lidos: {ok}/{len(files['frm'])}")
    print(f"versoes: {dict(stats['versions'])}")
    print(f"numero de ossos observado: {sorted(stats['bones'])}")
    print(f"consumiram o arquivo exatamente (0 bytes de sobra): {stats['exact']}/{ok}")
    print(f"total de keyframes: {stats['frames']}")
    all_failures += failures

    section("3. Decodificacao de DDS")
    ok, failures, stats = check_dds(files["dds"], args.cross_check)
    print(f"decodificados: {ok}/{len(files['dds'])}")
    print(f"formatos: {dict(stats['formats'])}")
    if stats["compared"]:
        print(f"comparados com Pillow: {stats['compared']}")
        print(f"erro maximo por canal: {stats['worst_error']}")
    all_failures += failures

    section("4. Conversao para GLB e validacao estrutural")
    ok, failures, stats = check_conversion(files["p3m"], args.out_dir)
    print(f"convertidos: {ok}/{len(files['p3m'])}")
    print(f"GLB com problema estrutural: {stats['invalid_glb']}")
    print(f"exportados como malha estatica (sem skinning): {stats['static']}")
    print(f"total gravado: {stats['bytes'] / (1024 * 1024):.1f} MB")
    all_failures += failures

    section("Resultado")
    if all_failures:
        print(f"{len(all_failures)} FALHA(S):")
        for failure in all_failures[:40]:
            print(f"  - {failure}")
        if len(all_failures) > 40:
            print(f"  ... e mais {len(all_failures) - 40}")
        return 1
    print("tudo passou")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
