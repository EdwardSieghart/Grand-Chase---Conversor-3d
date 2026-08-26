#!/usr/bin/env python3
"""Interface de linha de comando do Grand Chase 3D Importer.

Converte nos dois sentidos, e o sentido e deduzido das extensoes:

    .p3m / .frm  ->  .glb          (extrair do jogo)
    .glb / .gltf ->  .p3m + .frm   (devolver para o jogo)

Exemplos
--------
Extrair um modelo do jogo, com todas as animacoes compativeis de uma pasta:
    python3 gc3d_cli.py convert abta003.p3m --anim-dir animacoes/ -o saida/

Trazer de volta um modelo editado no Blender:
    python3 gc3d_cli.py convert personagem.glb -o saida/

Uma pasta inteira, em qualquer um dos sentidos:
    python3 gc3d_cli.py batch "GRAND CHASE/Models" --anim-dir animacoes/ -o saida/
    python3 gc3d_cli.py batch modelos_editados/ -o saida/

Inspecionar arquivos sem converter:
    python3 gc3d_cli.py info abta003.p3m 4528.frm personagem.glb
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
    Direction,
    __version__,
    collect_inputs,
    convert_model,
    convert_to_gc,
    find_animations_for_model,
)
from gc3d.formats import frm as frm_format  # noqa: E402
from gc3d.formats import gltf_in  # noqa: E402
from gc3d.formats import p3m as p3m_format  # noqa: E402
from gc3d.scene import DEFAULT_FPS  # noqa: E402


# --------------------------------------------------------------- apresentacao


def _human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _print_result(result: ConvertResult, verbose: bool, quiet: bool) -> None:
    name = os.path.basename(result.source)
    if result.ok:
        if not quiet:
            produced = ", ".join(os.path.basename(p) for p in result.outputs[:4])
            if len(result.outputs) > 4:
                produced += f" (+{len(result.outputs) - 4})"
            print(f"[ok]    {name} -> {produced}")
            print(f"        {result.summary}, {_human_size(result.bytes_written)}")
            if result.texture_used:
                print(f"        textura: {os.path.basename(result.texture_used)}")
            elif verbose:
                print("        textura: nenhuma")
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
        export_animations=not args.no_animations,
        extract_texture=not args.no_texture,
    )


# ------------------------------------------------------------------- comandos


def cmd_convert(args: argparse.Namespace) -> int:
    models, animations, gltfs = collect_inputs(args.inputs, recursive=False)
    animations = list(animations) + list(args.anim or [])

    if gltfs:
        # Sentido inverso: glTF -> P3M/FRM.
        if len(gltfs) > 1:
            print(
                f"{len(gltfs)} arquivos glTF informados; use o comando 'batch' "
                f"para converter varios de uma vez",
                file=sys.stderr,
            )
            return 2
        if models or animations:
            print(
                "aviso: arquivos .p3m/.frm foram ignorados porque a entrada "
                "principal e um glTF",
                file=sys.stderr,
            )
        output_dir = args.output or "."
        if output_dir.lower().endswith((".glb", ".gltf", ".p3m", ".frm")):
            output_dir = os.path.dirname(output_dir) or "."
        if not args.quiet:
            print(f"{Direction.LABELS[Direction.TO_GC]}: {os.path.basename(gltfs[0])}")
        result = convert_to_gc(gltfs[0], output_dir, _options_from_args(args))
        _print_result(result, args.verbose, args.quiet)
        return 0 if result.ok else 1

    if not models and not animations:
        print(
            "nada a converter: informe um .p3m, um .frm ou um .glb",
            file=sys.stderr,
        )
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
    models, _, gltfs = collect_inputs(args.inputs, recursive=not args.no_recursive)

    if not models and not gltfs:
        print(
            "nenhum arquivo .p3m nem .glb encontrado nas entradas", file=sys.stderr
        )
        return 2
    if models and gltfs:
        print(
            f"aviso: {len(gltfs)} glTF e {len(models)} P3M encontrados juntos; "
            f"convertendo apenas os glTF (para o outro sentido, rode em pastas "
            f"separadas)",
            file=sys.stderr,
        )
        models = []

    options = _options_from_args(args)
    inputs = gltfs or models
    direction = Direction.TO_GC if gltfs else Direction.TO_GLTF

    if not args.quiet:
        print(
            f"{Direction.LABELS[direction]}: {len(inputs)} arquivo(s) -> {args.output}"
        )

    results: list[ConvertResult] = []
    for index, path in enumerate(inputs):
        if not args.quiet:
            print(f"[{index + 1}/{len(inputs)}] {os.path.basename(path)}", flush=True)
        if direction == Direction.TO_GC:
            results.append(convert_to_gc(path, args.output, options))
        else:
            stem = os.path.splitext(os.path.basename(path))[0]
            animations = (
                find_animations_for_model(path, args.anim_dir)
                if args.anim_dir
                else []
            )
            results.append(
                convert_model(
                    path,
                    os.path.join(args.output, stem + ".glb"),
                    animations,
                    options,
                )
            )

    failures = [r for r in results if not r.ok]
    if not args.quiet:
        for result in failures:
            _print_result(result, args.verbose, args.quiet)
        total_bytes = sum(r.bytes_written for r in results)
        total_files = sum(len(r.outputs) for r in results)
        print()
        print(
            f"concluido: {len(results) - len(failures)}/{len(results)} "
            f"convertido(s), {total_files} arquivo(s) e "
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
                    f"  duracao            {animation.duration:.2f}s a "
                    f"{DEFAULT_FPS} FPS"
                )
                if animation.trailing_bytes:
                    print(f"  bytes extras       {animation.trailing_bytes}")
            elif lower.endswith((".glb", ".gltf")):
                document = gltf_in.load_gltf(path)
                root = document.json
                print(f"{name}")
                print(
                    f"  formato            glTF 2.0 "
                    f"{'binario (GLB)' if lower.endswith('.glb') else 'texto'}"
                )
                print(
                    f"  gerador            "
                    f"{root.get('asset', {}).get('generator', '(nao informado)')}"
                )
                print(f"  nos                {len(document.nodes)}")
                print(f"  malhas             {len(document.meshes)}")
                vertices = 0
                triangles = 0
                for mesh in document.meshes:
                    for primitive in mesh.get("primitives") or []:
                        attributes = primitive.get("attributes") or {}
                        if "POSITION" in attributes:
                            vertices += document.accessors[
                                attributes["POSITION"]
                            ].get("count", 0)
                        if "indices" in primitive:
                            triangles += (
                                document.accessors[primitive["indices"]].get(
                                    "count", 0
                                )
                                // 3
                            )
                print(f"  vertices           {vertices}")
                print(f"  triangulos         {triangles}")
                if document.skins:
                    print(
                        f"  ossos              "
                        f"{len(document.skins[0].get('joints') or [])}"
                    )
                else:
                    print("  ossos              0 (sem skin: malha estatica)")
                print(f"  animacoes          {len(document.animations)}")
                for animation in document.animations[:10]:
                    samplers = animation.get("samplers") or []
                    frames = 0
                    if samplers:
                        frames = document.accessors[samplers[0]["input"]].get(
                            "count", 0
                        )
                    print(
                        f"    - {animation.get('name', '(sem nome)')}: "
                        f"{frames} keyframes"
                    )
                if len(document.animations) > 10:
                    print(f"    ... e mais {len(document.animations) - 10}")
            else:
                print(
                    f"{name}: extensao nao reconhecida "
                    f"(esperado .p3m, .frm, .glb ou .gltf)"
                )
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
            "Converte modelos e animacoes do Grand Chase nos dois sentidos: "
            ".p3m/.frm para glTF binario (.glb), e .glb/.gltf de volta para "
            ".p3m/.frm. O sentido e deduzido das extensoes."
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
            help="nao procurar, embutir nem extrair textura",
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
        sub.add_argument(
            "--no-animations",
            action="store_true",
            help="ao converter glTF de volta, nao gravar os arquivos .frm",
        )
        sub.add_argument("-v", "--verbose", action="store_true", help="mais detalhes")
        sub.add_argument("-q", "--quiet", action="store_true", help="menos saida")

    convert = subparsers.add_parser(
        "convert",
        help="converte um arquivo (o sentido vem da extensao)",
    )
    convert.add_argument(
        "inputs", nargs="+", help="arquivos .p3m, .frm, .glb ou .gltf"
    )
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
        "batch",
        help="converte todos os arquivos convertiveis de arquivos/pastas informados",
    )
    batch.add_argument("inputs", nargs="+", help="arquivos e/ou pastas")
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

    info = subparsers.add_parser(
        "info", help="mostra informacoes de arquivos .p3m, .frm, .glb ou .gltf"
    )
    info.add_argument("inputs", nargs="+", help="arquivos a inspecionar")
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
