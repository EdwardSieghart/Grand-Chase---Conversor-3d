"""Validacao end-to-end: importa arquivos GLB no Blender e relata o que chegou.

Serve como prova de que a saida do conversor e consumivel por um importador
glTF real, nao apenas estruturalmente valida. Verifica o que de fato importa
para quem vai usar o modelo: malha, esqueleto, pesos de vertice, UVs, textura e
animacoes.

Executar:
    blender --background --factory-startup --python tools/blender_check.py -- a.glb b.glb ...

Ou, com Blender instalado por Flatpak:
    flatpak run org.blender.Blender --background --factory-startup \
        --python tools/blender_check.py -- a.glb

Para cada arquivo imprime uma linha `RESULT_JSON {...}` com o resumo, e no fim
uma linha `SUMMARY_JSON {...}` com o agregado. Sai com codigo 1 se algum arquivo
falhar.
"""

import json
import os
import sys

import bpy


def snapshot() -> set[str]:
    return {o.name for o in bpy.data.objects}


def check(path: str) -> dict:
    """Importa um GLB numa cena vazia e devolve um resumo do conteudo."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for block in list(bpy.data.objects):
        bpy.data.objects.remove(block, do_unlink=True)
    for block in list(bpy.data.actions):
        bpy.data.actions.remove(block, do_unlink=True)
    for block in list(bpy.data.images):
        bpy.data.images.remove(block, do_unlink=True)

    before = snapshot()
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "file": os.path.basename(path), "error": str(error)}

    imported = [o for o in bpy.data.objects if o.name not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    armatures = [o for o in imported if o.type == "ARMATURE"]

    total_verts = sum(len(o.data.vertices) for o in meshes)
    # Um vertice sem peso numa malha com armature ficaria parado durante a
    # animacao. Em malha estatica (sem armature) a ausencia de peso e o normal,
    # por isso a contagem so considera malhas de fato skinadas.
    unweighted = 0
    skinned_meshes = [
        o for o in meshes if any(m.type == "ARMATURE" for m in o.modifiers)
    ]
    for obj in skinned_meshes:
        for vertex in obj.data.vertices:
            if not vertex.groups or all(g.weight == 0.0 for g in vertex.groups):
                unweighted += 1

    return {
        "ok": True,
        "file": os.path.basename(path),
        "meshes": len(meshes),
        "skinned_meshes": len(skinned_meshes),
        "armatures": len(armatures),
        "verts": total_verts,
        "tris": sum(len(o.data.polygons) for o in meshes),
        "bones": sum(len(a.data.bones) for a in armatures),
        "actions": len(bpy.data.actions),
        "images": [list(i.size) for i in bpy.data.images if i.size[0]],
        "uv_layers": min((len(o.data.uv_layers) for o in meshes), default=0),
        "vgroups": sum(len(o.vertex_groups) for o in meshes),
        "unweighted_verts": unweighted,
    }


def main() -> int:
    if "--" not in sys.argv:
        print("uso: blender ... --python tools/blender_check.py -- arquivo.glb [...]")
        print("     blender ... --python tools/blender_check.py -- --list lista.txt")
        return 2
    args = sys.argv[sys.argv.index("--") + 1 :]

    # Caminhos do projeto contem espacos, e passar muitos argumentos pelo shell
    # e fragil. `--list` le um caminho por linha, sem ambiguidade de quoting.
    if args and args[0] == "--list":
        with open(args[1], encoding="utf-8") as handle:
            paths = [line.strip() for line in handle if line.strip()]
    else:
        paths = args

    results = []
    for path in paths:
        result = check(os.path.abspath(path))
        results.append(result)
        print("RESULT_JSON", json.dumps(result, ensure_ascii=False))

    failed = [r for r in results if not r.get("ok")]
    summary = {
        "total": len(results),
        "ok": len(results) - len(failed),
        "failed": len(failed),
        "failures": [(r["file"], r.get("error", "")[:120]) for r in failed],
        "total_verts": sum(r.get("verts", 0) for r in results),
        "total_actions": sum(r.get("actions", 0) for r in results),
        "unweighted_verts": sum(r.get("unweighted_verts", 0) for r in results),
        "files_with_unweighted": [
            (r["file"], r["unweighted_verts"])
            for r in results
            if r.get("unweighted_verts")
        ][:10],
        "without_uv": [
            r["file"] for r in results if r.get("ok") and not r.get("uv_layers")
        ][:10],
        "without_armature": [
            r["file"] for r in results if r.get("ok") and not r.get("armatures")
        ][:10],
    }
    print("SUMMARY_JSON", json.dumps(summary, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
