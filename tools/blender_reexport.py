"""Reexporta arquivos GLB pelo Blender, para testar interoperabilidade.

O ciclo `nosso GLB -> Blender -> GLB do Blender -> nosso P3M` e o teste que
importa de verdade para a conversao inversa: prova que o importador aguenta um
glTF produzido por outra ferramenta, com suas proprias convencoes de nome de no,
ordem de joints, instantes de keyframe e layout de acessor.

Executar:
    blender --background --factory-startup --python tools/blender_reexport.py \
        -- --list entrada.txt --out-dir /pasta/de/saida

Para cada arquivo da lista imprime uma linha `REEXPORT_JSON {...}`.
"""

import json
import os
import sys

import bpy


def reexport(path: str, out_dir: str) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for block in list(bpy.data.objects):
        bpy.data.objects.remove(block, do_unlink=True)
    for block in list(bpy.data.actions):
        bpy.data.actions.remove(block, do_unlink=True)

    name = os.path.splitext(os.path.basename(path))[0]
    target = os.path.join(out_dir, name + ".glb")

    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "file": os.path.basename(path), "stage": "import", "error": str(error)}

    # Reune todas as actions em faixas NLA para que o exportador do Blender
    # grave todas as animacoes, e nao apenas a que esta ativa.
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    actions = list(bpy.data.actions)
    if armatures and actions:
        armature = armatures[0]
        if armature.animation_data is None:
            armature.animation_data_create()
        armature.animation_data.action = None
        for action in actions:
            track = armature.animation_data.nla_tracks.new()
            track.name = action.name
            track.strips.new(action.name, int(action.frame_range[0]), action)

    try:
        bpy.ops.export_scene.gltf(
            filepath=target,
            export_format="GLB",
            export_animations=True,
            export_animation_mode="ACTIONS",
            export_skins=True,
            export_yup=True,
        )
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "file": os.path.basename(path), "stage": "export", "error": str(error)}

    return {
        "ok": True,
        "file": os.path.basename(path),
        "output": target,
        "actions": len(actions),
        "size": os.path.getsize(target) if os.path.isfile(target) else 0,
    }


def main() -> int:
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    args = sys.argv[sys.argv.index("--") + 1 :]

    paths: list[str] = []
    out_dir = "."
    i = 0
    while i < len(args):
        if args[i] == "--list":
            with open(args[i + 1], encoding="utf-8") as handle:
                paths = [line.strip() for line in handle if line.strip()]
            i += 2
        elif args[i] == "--out-dir":
            out_dir = args[i + 1]
            i += 2
        else:
            paths.append(args[i])
            i += 1

    os.makedirs(out_dir, exist_ok=True)
    failed = 0
    for path in paths:
        result = reexport(os.path.abspath(path), os.path.abspath(out_dir))
        if not result.get("ok"):
            failed += 1
        print("REEXPORT_JSON", json.dumps(result, ensure_ascii=False))

    print("REEXPORT_SUMMARY", json.dumps({"total": len(paths), "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
