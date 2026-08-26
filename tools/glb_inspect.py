"""Inspetor e comparador de arquivos GLB.

Ferramenta de desenvolvimento, usada para validar a saida do conversor. Faz duas
coisas:

* `inspect`: mostra a estrutura de um GLB (nos, malhas, acessores, animacoes) e
  checa invariantes do glTF 2.0 que os validadores oficiais cobram.
* `compare`: compara dois GLB atributo por atributo. Foi assim que a saida deste
  conversor foi conferida contra a do conversor antigo (chaseconv), que se sabia
  funcionar corretamente no jogo.

Uso:
    python3 tools/glb_inspect.py inspect arquivo.glb
    python3 tools/glb_inspect.py compare novo.glb referencia.glb
"""

from __future__ import annotations

import json
import struct
import sys

_COMPONENT = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TYPE_COUNT = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class Glb:
    """GLB carregado: JSON + buffer binario, com acesso aos acessores."""

    def __init__(self, path: str) -> None:
        with open(path, "rb") as handle:
            data = handle.read()
        self.path = path
        magic, version, length = struct.unpack_from("<III", data, 0)
        if magic != 0x46546C67:
            raise ValueError(f"{path}: nao e um GLB (magic 0x{magic:08X})")
        if version != 2:
            raise ValueError(f"{path}: versao GLB {version}, esperado 2")
        if length != len(data):
            raise ValueError(
                f"{path}: comprimento declarado {length} != tamanho real {len(data)}"
            )

        self.json: dict = {}
        self.bin = b""
        offset = 12
        while offset + 8 <= len(data):
            chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
            payload = data[offset + 8 : offset + 8 + chunk_length]
            if chunk_type == 0x4E4F534A:
                self.json = json.loads(payload.decode("utf-8"))
            elif chunk_type == 0x004E4942:
                self.bin = payload
            offset += 8 + chunk_length
            offset += (-offset) % 4
        if not self.json:
            raise ValueError(f"{path}: chunk JSON ausente")

    # ------------------------------------------------------------ acessores

    def accessor(self, index: int) -> list:
        """Le um acessor e devolve uma lista de tuplas (ou de escalares)."""
        acc = self.json["accessors"][index]
        fmt, size = _COMPONENT[acc["componentType"]]
        components = _TYPE_COUNT[acc["type"]]
        count = acc["count"]

        view = self.json["bufferViews"][acc["bufferView"]]
        base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or components * size

        values = []
        for i in range(count):
            start = base + i * stride
            chunk = struct.unpack_from(f"<{components}{fmt}", self.bin, start)
            values.append(chunk[0] if components == 1 else chunk)
        return values

    def primitive_attribute(self, mesh: int, name: str, primitive: int = 0):
        prim = self.json["meshes"][mesh]["primitives"][primitive]
        if name == "indices":
            return self.accessor(prim["indices"])
        index = prim["attributes"].get(name)
        return None if index is None else self.accessor(index)


# ------------------------------------------------------------------ inspecao


def _check(problems: list[str], condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def validate(glb: Glb) -> list[str]:
    """Confere invariantes do glTF 2.0 que importam para importadores reais."""
    problems: list[str] = []
    root = glb.json

    _check(problems, root.get("asset", {}).get("version") == "2.0", "asset.version != 2.0")

    buffers = root.get("buffers", [])
    _check(problems, len(buffers) <= 1, "mais de um buffer num GLB")
    if buffers:
        declared = buffers[0].get("byteLength", 0)
        _check(
            problems,
            declared == len(glb.bin),
            f"buffer.byteLength={declared} != chunk BIN={len(glb.bin)}",
        )
        _check(problems, "uri" not in buffers[0], "buffer do GLB nao deve ter uri")

    for i, view in enumerate(root.get("bufferViews", [])):
        end = view.get("byteOffset", 0) + view["byteLength"]
        _check(problems, end <= len(glb.bin), f"bufferView {i} passa do fim do buffer")

    for i, acc in enumerate(root.get("accessors", [])):
        fmt, size = _COMPONENT[acc["componentType"]]
        components = _TYPE_COUNT[acc["type"]]
        view = root["bufferViews"][acc["bufferView"]]
        offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        _check(
            problems,
            offset % size == 0,
            f"accessor {i}: offset {offset} nao alinhado ao componente de {size} byte(s)",
        )
        needed = acc["count"] * components * size
        _check(
            problems,
            needed <= view["byteLength"],
            f"accessor {i}: precisa de {needed} bytes, bufferView tem {view['byteLength']}",
        )

    node_count = len(root.get("nodes", []))
    parents: dict[int, int] = {}
    for i, node in enumerate(root.get("nodes", [])):
        for child in node.get("children", []):
            _check(problems, child < node_count, f"no {i} referencia filho inexistente {child}")
            _check(
                problems,
                child not in parents,
                f"no {child} tem dois pais ({parents.get(child)} e {i}); "
                f"a hierarquia glTF deve ser uma floresta",
            )
            parents[child] = i

    for i, skin in enumerate(root.get("skins", [])):
        joints = skin["joints"]
        if "inverseBindMatrices" in skin:
            ibm = root["accessors"][skin["inverseBindMatrices"]]
            _check(
                problems,
                ibm["count"] == len(joints),
                f"skin {i}: {ibm['count']} inverse bind matrices para {len(joints)} joints",
            )

    for mesh_index, mesh in enumerate(root.get("meshes", [])):
        for prim_index, prim in enumerate(mesh["primitives"]):
            position = root["accessors"][prim["attributes"]["POSITION"]]
            vertex_count = position["count"]
            _check(
                problems,
                "min" in position and "max" in position,
                f"malha {mesh_index}: POSITION precisa de min e max",
            )
            for name, accessor_index in prim["attributes"].items():
                acc = root["accessors"][accessor_index]
                _check(
                    problems,
                    acc["count"] == vertex_count,
                    f"malha {mesh_index}: {name} tem {acc['count']} elementos, "
                    f"POSITION tem {vertex_count}",
                )
            if "indices" in prim:
                indices = glb.accessor(prim["indices"])
                _check(
                    problems,
                    len(indices) % 3 == 0,
                    f"malha {mesh_index} prim {prim_index}: contagem de indices "
                    f"({len(indices)}) nao e multiplo de 3",
                )
                if indices:
                    _check(
                        problems,
                        max(indices) < vertex_count,
                        f"malha {mesh_index}: indice {max(indices)} >= {vertex_count} vertices",
                    )

    for i, animation in enumerate(root.get("animations", [])):
        for j, channel in enumerate(animation["channels"]):
            _check(
                problems,
                channel["sampler"] < len(animation["samplers"]),
                f"animacao {i} canal {j}: sampler inexistente",
            )
            _check(
                problems,
                channel["target"]["node"] < node_count,
                f"animacao {i} canal {j}: no alvo inexistente",
            )
        for j, sampler in enumerate(animation["samplers"]):
            input_acc = root["accessors"][sampler["input"]]
            output_acc = root["accessors"][sampler["output"]]
            _check(
                problems,
                input_acc["count"] == output_acc["count"],
                f"animacao {i} sampler {j}: {input_acc['count']} tempos para "
                f"{output_acc['count']} valores",
            )
            _check(
                problems,
                "min" in input_acc and "max" in input_acc,
                f"animacao {i} sampler {j}: acessor de tempo precisa de min/max",
            )

    return problems


def describe(glb: Glb) -> str:
    root = glb.json
    lines = [f"arquivo: {glb.path}", f"gerador: {root.get('asset',{}).get('generator','?')}"]
    lines.append(f"nos: {len(root.get('nodes', []))}")
    lines.append(f"malhas: {len(root.get('meshes', []))}")
    for i, mesh in enumerate(root.get("meshes", [])):
        for prim in mesh["primitives"]:
            acc = root["accessors"][prim["attributes"]["POSITION"]]
            n_idx = root["accessors"][prim["indices"]]["count"] if "indices" in prim else 0
            lines.append(
                f"  malha {i} '{mesh.get('name','')}': {acc['count']} vertices, "
                f"{n_idx // 3} triangulos, atributos: "
                f"{', '.join(sorted(prim['attributes']))}"
            )
    for i, skin in enumerate(root.get("skins", [])):
        lines.append(f"skin {i}: {len(skin['joints'])} joints, raiz={skin.get('skeleton')}")
    for i, animation in enumerate(root.get("animations", [])):
        frames = root["accessors"][animation["samplers"][0]["input"]]["count"]
        lines.append(
            f"animacao {i} '{animation.get('name','')}': {frames} keyframes, "
            f"{len(animation['channels'])} canais"
        )
    lines.append(f"imagens: {len(root.get('images', []))}, materiais: {len(root.get('materials', []))}")
    lines.append(f"buffer binario: {len(glb.bin)} bytes")
    return "\n".join(lines)


# ----------------------------------------------------------------- comparacao


def compare(a: Glb, b: Glb, tolerance: float = 1e-5) -> list[str]:
    """Compara geometria e esqueleto de dois GLB. Devolve lista de diferencas."""
    diffs: list[str] = []

    mesh_count_a = len(a.json.get("meshes", []))
    mesh_count_b = len(b.json.get("meshes", []))
    if mesh_count_a != mesh_count_b:
        diffs.append(f"numero de malhas: {mesh_count_a} vs {mesh_count_b}")

    for mesh in range(min(mesh_count_a, mesh_count_b)):
        for attribute in ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0", "indices"):
            va = a.primitive_attribute(mesh, attribute)
            vb = b.primitive_attribute(mesh, attribute)
            if va is None and vb is None:
                continue
            if va is None or vb is None:
                diffs.append(f"malha {mesh}: {attribute} presente em apenas um dos dois")
                continue
            if len(va) != len(vb):
                diffs.append(
                    f"malha {mesh}: {attribute} tem {len(va)} vs {len(vb)} elementos"
                )
                continue
            worst = 0.0
            worst_at = -1
            for i, (x, y) in enumerate(zip(va, vb)):
                if isinstance(x, tuple):
                    delta = max(abs(p - q) for p, q in zip(x, y))
                else:
                    delta = abs(x - y)
                if delta > worst:
                    worst = delta
                    worst_at = i
            if worst > tolerance:
                diffs.append(
                    f"malha {mesh}: {attribute} difere, maior delta {worst:.6g} "
                    f"no elemento {worst_at} ({va[worst_at]} vs {vb[worst_at]})"
                )

    skins_a = a.json.get("skins", [])
    skins_b = b.json.get("skins", [])
    if len(skins_a) != len(skins_b):
        diffs.append(f"numero de skins: {len(skins_a)} vs {len(skins_b)}")
    elif skins_a:
        ja, jb = skins_a[0]["joints"], skins_b[0]["joints"]
        if len(ja) != len(jb):
            diffs.append(f"numero de joints: {len(ja)} vs {len(jb)}")
        else:
            ma = a.accessor(skins_a[0]["inverseBindMatrices"])
            mb = b.accessor(skins_b[0]["inverseBindMatrices"])
            worst = max(
                (max(abs(p - q) for p, q in zip(x, y)) for x, y in zip(ma, mb)),
                default=0.0,
            )
            if worst > tolerance:
                diffs.append(f"inverseBindMatrices diferem, maior delta {worst:.6g}")

    # Translacoes dos nos de joint.
    nodes_a = a.json.get("nodes", [])
    nodes_b = b.json.get("nodes", [])
    joint_count = len(skins_a[0]["joints"]) if skins_a else 0
    for i in range(min(joint_count, len(nodes_a), len(nodes_b))):
        ta = tuple(nodes_a[i].get("translation", (0.0, 0.0, 0.0)))
        tb = tuple(nodes_b[i].get("translation", (0.0, 0.0, 0.0)))
        if max(abs(p - q) for p, q in zip(ta, tb)) > tolerance:
            diffs.append(f"no {i}: translacao {ta} vs {tb}")

    return diffs


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    command = argv[1]
    if command == "inspect":
        glb = Glb(argv[2])
        print(describe(glb))
        problems = validate(glb)
        print()
        if problems:
            print(f"{len(problems)} problema(s) encontrado(s):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("validacao: OK, nenhum problema encontrado")
        return 0
    if command == "compare":
        if len(argv) < 4:
            print("compare exige dois arquivos")
            return 2
        a, b = Glb(argv[2]), Glb(argv[3])
        print(f"A: {a.path}")
        print(f"B: {b.path}")
        diffs = compare(a, b)
        if diffs:
            print(f"\n{len(diffs)} diferenca(s):")
            for diff in diffs:
                print(f"  - {diff}")
            return 1
        print("\ngeometria e esqueleto identicos dentro da tolerancia")
        return 0
    print(f"comando desconhecido: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
