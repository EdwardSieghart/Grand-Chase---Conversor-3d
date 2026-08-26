#!/usr/bin/env python3
"""Interface de linha de comando do Grand Chase 3D Importer.

Exemplos
--------
Converter um modelo:
    python3 gc3d_cli.py convert abta003.p3m -o saida/

Converter um modelo com todas as animacoes compativeis de uma pasta:
    python3 gc3d_cli.py convert abta003.p3m --anim-dir animacoes/ -o saida/

Converter um modelo com animacoes especificas:
    python3 gc3d_cli.py convert modelo.p3m -a andar.frm -a correr.frm -o saida/

Converter uma pasta inteira, casando animacoes pelo numero de ossos:
    python3 gc3d_cli.py batch "GRAND CHASE/Models" --anim-dir "GRAND CHASE/ANIM" -o saida/

Inspecionar arquivos sem converter:
    python3 gc3d_cli.py info abta003.p3m 4528.frm
"""

from __future__ import annotations

import argparse
import os
import sys

# Permite rodar direto do repositorio, sem instalar o pacote.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from gc3d import (  # noqa: E402
    ConvertOptions,
    ConvertResult,
    __version__,
    collect_inputs,
    convert_batch,
    convert_model,
    find_animations_for_model,
)
from gc3d.formats import frm as frm_format  # noqa: E402
from gc3d.formats import p3m as p3m_format  # noqa: E402


# --------------------------------------------------------------- apresentacao


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _print_result(result: ConvertResult, verbose: bool, quiet: bool) -> None:
    name = os.path.basename(result.source)
    if result.ok:
        if not quiet:
            print(f"[ok]    {name} -> {os.path.basename(result.output_path or '')}")
            print(f"        {result.summary}, {_human_size(result.bytes_written)}")
            if result.texture_used:
                print(f"        textura: {os.path.basename(result.texture_used)}")
            elif verbose:
                print("        textura: nenhuma encontrada")
        for warning in result.warnings if verbose else []:
            print(f"        aviso: {warning}")
    else:
        print(f"[ERRO]  {name}: {result.error}", file=sys.stderr)
        if verbose and result.traceback:
            print(result.traceback, file=sys.stderr)


def _options_from_args(args: argparse.Namespace) -> ConvertOptions:
    return ConvertOptions(
        embed_texture=not args.no_texture,
        texture_path=getattr(args, "texture", None),
        texture_dirs=list(getattr(args, "texture_dir", None) or []),
        double_sided=not args.single_sided,
        alpha_mode=args.alpha_mode,
        normalize_normals=not args.keep_normals,
        pretty_json=args.pretty_json,
    )


# ------------------------------------------------------------------- comandos


def cmd_convert(args: argparse.Namespace) -> int:
    models, animations = collect_inputs(args.inputs, recursive=False)
    animations = list(animations) + list(args.anim or [])

    if not models and not animations:
        print("nada a converter: informe pelo menos um .p3m ou .frm", file=sys.stderr)
        return 2
    if len(models) > 1:
        print(
            f"{len(models)} modelos informados; use o comando 'batch' para "
            f"converter varios de uma vez",
            file=sys.stderr,
        )
        return 2

    model = models[0] if models else None

    if args.anim_dir and model:
        found = find_animations_for_model(model, args.anim_dir)
        if not args.quiet:
            print(f"{len(found)} animacao(oes) compativel(is) em {args.anim_dir}")
        animations.extend(a for a in found if a not in animations)

    stem = os.path.splitext(os.path.basename(model or animations[0]))[0]
    if args.output and args.output.lower().endswith(".glb"):
        output_path = args.output
    else:
        output_path = os.path.join(args.output or ".", stem + ".glb")

    result = convert_model(model, output_path, animations, _options_from_args(args))
    _print_result(result, args.verbose, args.quiet)
    return 0 if result.ok else 1


def cmd_batch(args: argparse.Namespace) -> int:
    models, _ = collect_inputs(args.inputs, recursive=not args.no_recursive)
    if not models:
        print("nenhum arquivo .p3m encontrado nas entradas", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"{len(models)} modelo(s) para converter -> {args.output}")

    def progress(index: int, total: int, path: str) -> None:
        if args.quiet or not path:
            return
        print(f"[{index + 1}/{total}] {os.path.basename(path)}", flush=True)

    results = convert_batch(
        models,
        args.output,
        _options_from_args(args),
        animation_dir=args.anim_dir,
        progress=progress,
    )

    failures = [r for r in results if not r.ok]
    if not args.quiet:
        for result in results:
            if not result.ok:
                _print_result(result, args.verbose, args.quiet)
        total_bytes = sum(r.bytes_written for r in results)
        print()
        print(
            f"concluido: {len(results) - len(failures)}/{len(results)} convertido(s), "
            f"{_human_size(total_bytes)} gravado(s) em {args.output}"
        )
        if failures:
            print(f"{len(failures)} falha(s):", file=sys.stderr)
            for result in failures:
                print(
                    f"  {os.path.basename(result.source)}: {result.error}",
                    file=sys.stderr,
                )
    return 1 if failures else 0


def cmd_info(args: argparse.Namespace) -> int:
    exit_code = 0
    for path in args.inputs:
        name = os.path.basename(path)
        lower = path.lower()
        try:
            if lower.endswith(".p3m"):
                model = p3m_format.load_p3m(path)
                print(f"{name}")
                print(f"  formato            P3M v{model.version}")
                print(f"  position bones     {model.num_position_bones}")
                print(f"  angle bones        {model.num_angle_bones}  (= joints)")
                print(f"  vertices           {len(model.skin_vertices)}")
                print(f"  triangulos         {len(model.faces)}")
                print(f"  indice de osso     {model.bone_index_encoding}")
                print(f"  nome de textura    {model.texture_name or '(vazio)'}")
                if model.mesh_vertices_truncated:
                    print("  observacao         bloco MeshVertex truncado/ausente")
                if model.trailing_bytes:
                    print(f"  bytes extras       {model.trailing_bytes} (ignorados)")
            elif lower.endswith(".frm"):
                animation = frm_format.load_frm(path)
                print(f"{name}")
                print(f"  formato            FRM v{animation.version}")
                print(f"  frames             {animation.num_frames}")
                print(f"  ossos              {animation.num_bones}")
                print(
                    f"  duracao            {animation.duration:.2f}s "
                    f"a {frm_format.DEFAULT_FPS if hasattr(frm_format,'DEFAULT_FPS') else 55} FPS"
                )
                if animation.trailing_bytes:
                    print(f"  bytes extras       {animation.trailing_bytes}")
            else:
                print(f"{name}: extensao nao reconhecida (esperado .p3m ou .frm)")
                exit_code = 1
                continue
        except Exception as error:  # noqa: BLE001
            print(f"{name}: ERRO {type(error).__name__}: {error}", file=sys.stderr)
            exit_code = 1
        print()
    return exit_code


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gc3d",
        description=(
            "Converte modelos (.p3m) e animacoes (.frm) do Grand Chase para "
            "glTF binario (.glb), que abre no Blender, Unity, Godot e navegadores."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"gc3d {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--no-texture",
            action="store_true",
            help="nao procurar nem embutir textura",
        )
        sub.add_argument(
            "--texture-dir",
            action="append",
            metavar="PASTA",
            help="pasta extra onde procurar texturas (pode repetir)",
        )
        sub.add_argument(
            "--single-sided",
            action="store_true",
            help="material com faces de um lado so (padrao: dois lados)",
        )
        sub.add_argument(
            "--alpha-mode",
            choices=("OPAQUE", "MASK", "BLEND"),
            default=None,
            help="modo de transparencia do material (padrao: automatico)",
        )
        sub.add_argument(
            "--keep-normals",
            action="store_true",
            help="nao normalizar normais nao unitarias",
        )
        sub.add_argument(
            "--pretty-json",
            action="store_true",
            help="grava o JSON do GLB indentado (para depuracao)",
        )
        sub.add_argument("-v", "--verbose", action="store_true", help="mais detalhes")
        sub.add_argument("-q", "--quiet", action="store_true", help="menos saida")

    convert = subparsers.add_parser(
        "convert", help="converte um modelo (e animacoes opcionais) em um .glb"
    )
    convert.add_argument("inputs", nargs="+", help="arquivos .p3m e/ou .frm")
    convert.add_argument(
        "-o",
        "--output",
        default=".",
        metavar="DESTINO",
        help="arquivo .glb de saida ou pasta de destino (padrao: pasta atual)",
    )
    convert.add_argument(
        "-a",
        "--anim",
        action="append",
        metavar="ARQUIVO.frm",
        help="animacao a incluir (pode repetir)",
    )
    convert.add_argument(
        "--anim-dir",
        metavar="PASTA",
        help="inclui todas as animacoes da pasta que tiverem o mesmo numero de ossos",
    )
    convert.add_argument(
        "--texture", metavar="ARQUIVO", help="usa esta textura (.dds ou .png)"
    )
    add_common(convert)
    convert.set_defaults(func=cmd_convert)

    batch = subparsers.add_parser(
        "batch", help="converte todos os .p3m de arquivos/pastas informados"
    )
    batch.add_argument("inputs", nargs="+", help="arquivos .p3m e/ou pastas")
    batch.add_argument(
        "-o", "--output", required=True, metavar="PASTA", help="pasta de destino"
    )
    batch.add_argument(
        "--anim-dir",
        metavar="PASTA",
        help="para cada modelo, inclui as animacoes da pasta com o mesmo numero de ossos",
    )
    batch.add_argument(
        "--no-recursive",
        action="store_true",
        help="nao entrar em subpastas",
    )
    add_common(batch)
    batch.set_defaults(func=cmd_batch)

    info = subparsers.add_parser("info", help="mostra informacoes de arquivos .p3m/.frm")
    info.add_argument("inputs", nargs="+", help="arquivos .p3m e/ou .frm")
    info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
