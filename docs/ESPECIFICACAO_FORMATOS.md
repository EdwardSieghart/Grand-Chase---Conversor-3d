# Especificação Completa dos Formatos Binários P3M e FRM — Grand Chase Classic

**Referência técnica para implementação de parsers.**  
Baseado na análise do código-fonte do CharacterStudio (C#) e do documento `FORMATOS_P3M_FRM_CHARACTERSTUDIO.md`.

---

## Convenções Gerais

| Aspecto | Valor |
|---------|-------|
| Byte order | **Little-endian** em TODOS os campos |
| Encoding de strings | Latin-1 (ISO 8859-1), preenchidas com `\0` até tamanho fixo |
| Tipos primitivos | `u8`=1 byte, `u16`=2 bytes LE, `u32`=4 bytes LE, `f32`=IEEE 754 float 32-bit LE |
| Matrizes 4×4 | Armazenadas em **column-major order** (estilo OpenGL): col0[4], col1[4], col2[4], col3[4] |
| Índices de face | 0-based (exceto raros arquivos v0.7/v0.8 antigos que usam 1-based) |
| FPS de animação | **55 FPS** (framerate nativo do Grand Chase Classic) |

---

# PARTE 1 — FORMATO P3M (Perfect 3D Model)

## 1.1 Detecção de Versão

**Fonte:** `P3mParser.cs` → `FromBytes()`

Ler os primeiros **27 bytes** do arquivo como string Latin-1:

| Bytes do Header (27 bytes, incluindo `\0` final) | Versão |
|---------------------------------------------------|--------|
| `"Perfect 3D Model (Ver 1.0)\0"` | v1.0 |
| `"Perfect 3D Model (Ver 0.8)\0"` | v0.8 |
| `"Perfect 3D Model (Ver 0.7)\0"` | v0.7 |
| `"Perfect 3D Model (Ver 0.6)\0"` | v0.6 |
| `"Perfact 3D Model (Ver 0.5)\0"` | v0.5 / v0.5.2 (typo intencional: "Perfact") |

**Algoritmo:**
1. Ler 27 bytes
2. Se contém `"Ver 1.0"` → v1.0
3. Se contém `"Ver 0.8"` → v0.8
4. Se contém `"Ver 0.7"` → v0.7
5. Se contém `"Ver 0.6"` → v0.6
6. Caso contrário (inclui "Perfact") → v0.5 (sub-variante detectada depois)

> **NOTA:** v0.5 usa "**Perfact**" (typo). Todas as outras usam "**Perfect**".

### Detecção de Sub-Variante v0.5 vs v0.5.2

**Fonte:** `P3mParser.cs` → `ParseV05()` (bloco de detecção após leitura das faces)

Após ler header, bones, contadores, textureName e faces, calcular bytes restantes:

```
remaining = fileSize - offsetAtual
boneNamesSize = (numPositionBones + numAngleBones) × 21
```

| Condição | Variante |
|----------|----------|
| `remaining == numVertices × 72` | v0.5 standard (40B skin + 32B mesh) |
| `remaining == numVertices × 40` | v0.5.2 "soup" (40B skin only) |
| `remaining == numVertices × 72` | v0.5.2 "shared" (40B skin + 32B mesh) |
| `remaining == numVertices × 72 + boneNamesSize` | v0.5.2 "shared+bonenames" |

### Constantes Sentinela para ChildIndex Inválido

**Fonte:** `Models.cs` → `P3mConstants`

| Versão | Tipo | Valor Sentinela |
|--------|------|-----------------|
| v0.5, v0.7, BON | u8 | **255** (0xFF) |
| v0.6 | u16 | **300** |
| v0.8, v1.0 | u16 | **500** |

---

## 1.2 Hierarquia Dual de Bones (PositionBones + AngleBones)

**Fonte:** `P3mConverters.cs` → `ConvertP3mJoints()`

O P3M usa dois tipos de bones:

- **PositionBones** (índices 0 a numPosition-1): Bones raiz/estruturais. Contêm posição 3D e lista de filhos que apontam para **AngleBones**.
- **AngleBones** (índices 0 a numAngle-1): Bones articulares. Contêm posição relativa, scale, e lista de filhos que apontam para **outros AngleBones** (via intermediários PositionBone).

### Conversão para Esqueleto Simples (flat Joint list)

A lista unificada de Joints contém **apenas AngleBones** (PositionBones são absorvidos como translação):

```
Joint[0..numAngle-1] = AngleBones

Para cada PositionBone:
  Para cada child em PositionBone.Children:
    Joint[child].Translation = PositionBone.Position

Para cada AngleBone[i]:
  Para cada child em AngleBone[i].Children:
    Se child < numPositionBones:
      Para cada grandchild em PositionBone[child].Children:
        Joint[i].Children.append(grandchild)

Parents são derivados da lista de Children.
```

### Relação bone_index nos vértices

Os `SkinVertex.BoneIndex` nos arquivos P3M são **índices absolutos**:
```
índice_absoluto = numPositionBones + índice_do_AngleBone
```

Para converter para índice no skeleton simples:
```
skeleton_index = BoneIndex - numPositionBones
```

**EXCEÇÃO v1.0 SecondaryData:** Os `BoneIdx[]` no bloco secundário já são **índices de AngleBone** (0-based), usar diretamente sem subtrair.

---

## 1.3 P3M v0.5 (Standard)

**Fonte:** `P3mParser.cs` → `ParseV05()`

### Layout Sequencial do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x0000 | Header | char[27] | 27 | `"Perfact 3D Model (Ver 0.5)\0"` |
| 0x001B | NumPositionBones | u8 | 1 |
| 0x001C | NumAngleBones | u8 | 1 |
| 0x001D | PositionBone[NumPos] | — | NumPos × 24 |
| variável | AngleBone[NumAng] | — | NumAng × 28 |
| variável | NumVertices | u16 | 2 |
| variável | NumFaces | u16 | 2 |
| variável | TextureName | char[260] | 260 (Latin-1, null-padded) |
| variável | Face[NumFaces] | — | NumFaces × 6 |
| variável | SkinVertex[NumVerts] | — | NumVerts × 36 |
| variável | MeshVertex[NumVerts] | — | NumVerts × 32 |

### PositionBone v0.5 — 24 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | Posição local (x, y, z) |
| 0x0C | u8×10 | 10 | ChildIndices | Índices de AngleBones filhos; 0xFF = vazio |
| 0x16 | u16 | 2 | Padding | Sempre 0xFFFF, ler e descartar |

### AngleBone v0.5 — 28 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | Offset local relativo ao parent |
| 0x0C | f32 | 4 | Scale | Fator de escala (geralmente 1.0) |
| 0x10 | u8×10 | 10 | ChildIndices | Índices de outros AngleBones; 0xFF = vazio |
| 0x1A | u16 | 2 | Padding | Sempre 0xFFFF, ler e descartar |

### Face v0.5 — 6 bytes

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | u16 | 2 | Index[0] |
| 0x02 | u16 | 2 | Index[1] |
| 0x04 | u16 | 2 | Index[2] |

### SkinVertex v0.5 Standard — 40 bytes

> **CORRIGIDO POR VERIFICACAO EMPIRICA.** Uma versao anterior deste documento
> anunciava 36 bytes, mas a propria tabela de offsets abaixo soma 40
> (0x20 + 8 = 0x28). A medicao contra 131 arquivos P3M reais confirma **40
> bytes**: com 36, o tamanho previsto do arquivo nao fecha e os indices de
> face saem do intervalo valido. O campo de indice de osso ocupa 4 bytes, nao
> 1. Ver `docs/VALIDACAO.md`.

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | World-space |
| 0x0C | f32 | 4 | Weight | Geralmente 1.0 |
| 0x10 | u8 | 1 | BoneIndex | Índice absoluto (numPos + angleIdx) |
| 0x11 | u8 | 1 | BoneIndexCopy | Cópia redundante |
| 0x12 | u8 | 1 | Unused0 | Sempre 0xFF |
| 0x13 | u8 | 1 | Unused1 | Sempre 0xFF |
| 0x14 | f32×3 | 12 | Normal | Normal unitária |
| 0x20 | f32×2 | 8 | UV | Coordenadas de textura (u, v) |

### MeshVertex v0.5 — 32 bytes

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | f32×3 | 12 | Position |
| 0x0C | f32×3 | 12 | Normal |
| 0x18 | f32×2 | 8 | UV |

---

## 1.4 P3M v0.5.2 (Sub-Variantes)

**Fonte:** `P3mParser.cs` → `ParseV05()` (bloco `isV052Soup || isV052Shared`)

Mesmo header que v0.5. Mesma estrutura de bones, contadores, textureName e faces. Diferença está nos vértices.

### SkinVertex v0.5.2 (Layout B) — 40 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | World-space |
| 0x0C | f32 | 4 | Weight | Geralmente 1.0 |
| 0x10 | u32 | 4 | BoneIndex | Se totalBones ≤ 255: usar `value & 0xFF`; se > 255: usar valor completo |
| 0x14 | f32×3 | 12 | Normal | Normal unitária |
| 0x20 | f32×2 | 8 | UV | Coordenadas de textura |

### Variante "soup" — apenas SkinVertex

- `numVertices × 40` bytes de SkinVertex (Layout B)
- Sem MeshVertex, sem bone names

### Variante "shared" — SkinVertex + MeshVertex

- `numVertices × 40` bytes de SkinVertex (Layout B)
- `numVertices × 32` bytes de MeshVertex (mesmo formato da seção 1.3)

### Variante "shared+bonenames" — SkinVertex + MeshVertex + BoneNames

- SkinVertex[numVerts] (40B) + MeshVertex[numVerts] (32B)
- Seguido de tabela de nomes: para cada bone (numPos + numAng):

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | u8 | 1 | BoneIndex |
| 0x01 | char[20] | 20 | BoneName (Latin-1, null-padded) |

Total extra: `(numPosition + numAngle) × 21` bytes.

---

## 1.5 P3M v0.6

**Fonte:** `P3mParser.cs` → `ParseV06()`

### Layout Sequencial do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x0000 | Header | char[27] | 27 | `"Perfect 3D Model (Ver 0.6)\0"` |
| 0x001B | NumPositionBones | u16 | 2 |
| 0x001D | NumAngleBones | u16 | 2 |
| 0x001F | PositionBone[NumPos] | — | NumPos × 32 |
| variável | AngleBone[NumAng] | — | NumAng × 36 |
| variável | NumVertices | u32 | 4 |
| variável | NumFaces | u32 | 4 |
| variável | TextureName | char[260] | 260 |
| variável | Face[NumFaces] | — | NumFaces × 12 |
| variável | SkinVertex[NumVerts] | — | NumVerts × 40 (Layout B) |

### PositionBone v0.6 — 32 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | u16×10 | 20 | ChildIndices | 300 = slot vazio |

### AngleBone v0.6 — 36 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | f32 | 4 | Scale | |
| 0x10 | u16×10 | 20 | ChildIndices | 300 = slot vazio |

### Face v0.6 — 12 bytes

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | u32 | 4 | Index[0] |
| 0x04 | u32 | 4 | Index[1] |
| 0x08 | u32 | 4 | Index[2] |

### SkinVertex v0.6 — 40 bytes (Layout B)

Idêntico ao SkinVertex v0.5.2 Layout B (seção 1.4). Parser também gera MeshVertex clonando pos/normal/UV.

---

## 1.6 P3M v0.7

**Fonte:** `P3mParser.cs` → `ParseV07()`

### Layout Sequencial do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x0000 | Header | char[27] | 27 | `"Perfect 3D Model (Ver 0.7)\0"` |
| 0x001B | NumPositionBones | u16 | 2 |
| 0x001D | NumAngleBones | u16 | 2 |
| 0x001F | PositionBone[NumPos] | — | NumPos × 44 |
| variável | AngleBone[NumAng] | — | NumAng × 48 |
| variável | NumVertices | u32 | 4 |
| variável | NumFaces | u32 | 4 |
| variável | TextureName | char[260] | 260 |
| variável | FaceRecord[NumFaces] | — | NumFaces × 12 (6× u16 packed) |
| variável | Vertex[NumVerts] | — | NumVerts × 40 (Layout A ou B, auto-detect) |

### PositionBone v0.7 — 44 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | u8×30 | 30 | ChildIndices | 0xFF = slot vazio |
| 0x2A | u16 | 2 | ExtraField | Ler e descartar |

### AngleBone v0.7 — 48 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | 4 bytes | 4 | ScaleOrPacked | Ler como raw 4 bytes. Interpretar como f32 (Scale) E como u32 (RawU32) para round-trip |
| 0x10 | u8×30 | 30 | ChildIndices | 0xFF = slot vazio |
| 0x2E | u16 | 2 | ExtraU16 | Preservar para round-trip |

### Face Record v0.7 — 12 bytes (6× u16 packed)

Cada face record contém 6 slots u16. Apenas 3 contêm índices reais:

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | u16 | 2 | Slot[0] |
| 0x02 | u16 | 2 | Slot[1] |
| 0x04 | u16 | 2 | Slot[2] |
| 0x06 | u16 | 2 | Slot[3] |
| 0x08 | u16 | 2 | Slot[4] |
| 0x0A | u16 | 2 | Slot[5] |

Ver seção 1.9 para o algoritmo de extração (Face Permutation).

---

## 1.7 P3M v0.8

**Fonte:** `P3mParser.cs` → `ParseV08()`

### Layout Sequencial do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x0000 | Header | char[27] | 27 | `"Perfect 3D Model (Ver 0.8)\0"` |
| 0x001B | NumPositionBones | u16 | 2 |
| 0x001D | NumAngleBones | u16 | 2 |
| 0x001F | PositionBone[NumPos] | — | NumPos × 72 |
| variável | AngleBone[NumAng] | — | NumAng × 76 |
| variável | NumVertices | u32 | 4 |
| variável | NumFaces | u32 | 4 |
| variável | TextureName | char[260] | 260 |
| variável | Faces | — | NumFaces × 12 (formato depende de numVertices) |
| variável | Vertex[NumVerts] | — | NumVerts × 40 (Layout A ou B, auto-detect) |

### PositionBone v0.8 — 72 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | u16×30 | 60 | ChildIndices | 500 = slot vazio |

### AngleBone v0.8 — 76 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | f32 | 4 | Scale | |
| 0x10 | u16×30 | 60 | ChildIndices | 500 = slot vazio |

### Faces v0.8 — Duas Modalidades

**Fonte:** `P3mParser.cs` → `ParseV08()` (bloco `useU32Faces`)

```
Se numVertices > 65535:
    Faces são 3× u32 (12 bytes cada) — formato limpo, sem packed slots
    Detectar 1-based: se nenhum índice é 0 e mínimo é 1 → subtrair 1
    Clamp para [0, numVertices-1]
Senão:
    Faces são 6× u16 packed (12 bytes cada) — mesmo formato v0.7
    Aplicar FindBestFacePermutation + WindingRefinement
```

---

## 1.8 P3M v1.0

**Fonte:** `P3mParser.cs` → `ParseV10()`

### Layout Sequencial do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x0000 | Header | char[27] | 27 | `"Perfect 3D Model (Ver 1.0)\0"` |
| 0x001B | ExtendedHeader | u32×3 | 12 | Sempre {2, 2000, 2001}. Ler e descartar |
| 0x0027 | NumPositionBones | u16 | 2 |
| 0x0029 | NumAngleBones | u16 | 2 |
| 0x002B | PositionBone[NumPos] | — | NumPos × 72 (mesmo formato v0.8) |
| variável | AngleBone[NumAng] | — | NumAng × 76 |
| variável | NumVertices | u32 | 4 |
| variável | NumFaces | u32 | 4 |
| variável | TextureName | char[260] | 260 |
| variável | Face[NumFaces] | — | NumFaces × 12 (3× u32) |
| variável | PrimaryVertex[NumVerts] | — | NumVerts × 40 (Layout B fixo) |
| variável | SecondaryData[NumVerts] | — | NumVerts × 36 (multi-bone skinning) |
| variável | Footer | u32 | 4 | Sempre 0, ler e descartar |

### AngleBone v1.0 — 76 bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | |
| 0x0C | 4 bytes | 4 | ScaleOrRaw | Preservar como raw u32 para round-trip |
| 0x10 | u16×30 | 60 | ChildIndices | 500 = slot vazio |

### Face v1.0 — 12 bytes — WINDING INVERTIDO!

**CRÍTICO:** v1.0 inverte winding durante a leitura.

```
i0 = read_u32()
i1 = read_u32()
i2 = read_u32()
face = { i0, i2, i1 }   ← swap de i1 e i2!
```

### Primary Vertex v1.0 — 40 bytes (Layout B fixo)

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | f32×3 | 12 | Position | World-space |
| 0x0C | f32 | 4 | Weight | |
| 0x10 | u32 | 4 | BoneIndex | Índice ABSOLUTO (numPos + angleIdx) |
| 0x14 | f32×3 | 12 | Normal | |
| 0x20 | f32×2 | 8 | UV | |

> v1.0 **sempre** usa Layout B. Não é necessário auto-detecção.

### Secondary Data v1.0 — 36 bytes (Multi-Bone Skinning)

**Fonte:** `P3mParser.cs` → `ParseV10()` (bloco de secondary data)

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | u32 | 4 | DedupIndex | Geralmente == vertex_index. **Ignorar** |
| 0x04 | u32 | 4 | BoneIdx[0] | Índice de AngleBone (0-based, NÃO absoluto!) |
| 0x08 | u32 | 4 | BoneIdx[1] | 0xFFFFFFFF = slot vazio |
| 0x0C | u32 | 4 | BoneIdx[2] | 0xFFFFFFFF = slot vazio |
| 0x10 | u32 | 4 | BoneIdx[3] | 0xFFFFFFFF = slot vazio |
| 0x14 | f32 | 4 | Weight[0] | Peso do bone 0 |
| 0x18 | f32 | 4 | Weight[1] | < 0 = inválido |
| 0x1C | f32 | 4 | Weight[2] | < 0 = inválido |
| 0x20 | f32 | 4 | Weight[3] | < 0 = inválido |

**Regras de importação:**
- Filtrar slots onde `BoneIdx == 0xFFFFFFFF` ou `Weight < 0`
- `BoneIdx[]` são índices de **AngleBone** (usar DIRETAMENTE como skeleton_index)
- NÃO subtrair numPositionBones destes índices!
- Tipicamente 1-4 bones por vértice, weights somam ~1.0

---

## 1.9 Algoritmo de Face Permutation (v0.7 e v0.8)

**Fonte:** `P3mParser.cs` → `FindBestFacePermutation()`

### Conceito

Nos formatos v0.7/v0.8, cada face é armazenada como 6 slots u16. Apenas 3 dos 6 contêm os verdadeiros índices de vértice. O algoritmo testa todas as **120 combinações** de 3 posições distintas entre os 6 slots.

### Máscara de Vértice (vmask)

```
vmask = (1 << max(1, bit_length(numVertices - 1))) - 1
```

Onde `bit_length(n)` = número de bits necessários para representar `n`.

### Algoritmo FindBestFacePermutation

Para cada triplet `(a, b, c)` onde `a, b, c ∈ {0..5}` e todos distintos (120 combinações):

1. Amostrar `min(numFaces, 500)` faces
2. Para cada face `fi`:
   - `i0 = faceRaw[fi*6 + a] & vmask`
   - `i1 = faceRaw[fi*6 + b] & vmask`
   - `i2 = faceRaw[fi*6 + c] & vmask`
   - `inRange++` se todos < numVertices
   - `distinct++` se todos diferentes entre si
   - `tripOk++` se `i0 + i1 + i2 == 3*fi + 3` e `min(i0,i1,i2) == fi*3`

3. Escolher triplet com maior score `(tripOk, inRange, distinct)` em ordem lexicográfica
4. Resultado típico: **(2, 0, 4)**

### Detecção de Índices 1-Based

**Fonte:** `P3mParser.cs` → `DetectOneBased()`

Amostrar `min(numFaces, 2000)` faces usando a permutação escolhida:
- Se NENHUM índice é 0 E o valor mínimo é 1 → todos os índices são 1-based, subtrair 1

### Winding Refinement

**Fonte:** `P3mParser.cs` → `RefineWindingV07V08()`

Após encontrar o melhor triplet `(a, b, c)`, testar as **6 permutações** desse triplet:

1. Para cada permutação de `(a, b, c)`:
   - Amostrar `min(numFaces, 500)` faces
   - Calcular cross product dos edges → face normal
   - Calcular média das vertex normals dos 3 vértices
   - `posCount++` se dot(faceNormal, avgVertexNormal) ≥ 0
   - `negCount++` se dot < 0
2. Usar a permutação com maior `(posCount - negCount)`

### Winding para u32 (v0.8 com numVertices > 65535)

**Fonte:** `P3mParser.cs` → `RefineWindingU32()`

Amostrar 500 faces, contar normals que concordam vs discordam. Se maioria discorda → flip (swap i1 ↔ i2).

---

## 1.10 Auto-Detecção de Layout de Vértice (v0.7 e v0.8)

**Fonte:** `P3mParser.cs` → `DetectVertexLayout()`

Os 40 bytes por vértice podem estar em dois layouts:

### Layout A — 40 bytes (Z no final)

| Offset | Tipo | Campo |
|--------|------|-------|
| 0x00 | f32 | Position.x |
| 0x04 | f32 | Position.y |
| 0x08 | f32 | **Weight** ← offset 8 |
| 0x0C | u32 | **BoneIndex** ← offset 12 |
| 0x10 | f32 | Normal.x |
| 0x14 | f32 | Normal.y |
| 0x18 | f32 | Normal.z |
| 0x1C | f32 | UV.u |
| 0x20 | f32 | UV.v |
| 0x24 | f32 | **Position.z** ← Z no final! |

### Layout B — 40 bytes (ordem normal)

| Offset | Tipo | Campo |
|--------|------|-------|
| 0x00 | f32 | Position.x |
| 0x04 | f32 | Position.y |
| 0x08 | f32 | Position.z |
| 0x0C | f32 | **Weight** ← offset 12 |
| 0x10 | u32 | **BoneIndex** ← offset 16 |
| 0x14 | f32 | Normal.x |
| 0x18 | f32 | Normal.y |
| 0x1C | f32 | Normal.z |
| 0x20 | f32 | UV.u |
| 0x24 | f32 | UV.v |

### Algoritmo de Detecção

Amostrar `min(numVertices, 5000)` vértices:

```
Para cada vértice i (offset = i × 40):
  wA = float no offset 8  (weight candidato para Layout A)
  wB = float no offset 12 (weight candidato para Layout B)
  uA = u32 no offset 12   (bone candidato para Layout A)
  uB = u32 no offset 16   (bone candidato para Layout B)

  wa++ se |wA - 1.0| < 0.0001
  wb++ se |wB - 1.0| < 0.0001
  ba++ se uA != 0xFFFFFFFF e uA <= 2000
  bb++ se uB != 0xFFFFFFFF e uB <= 2000

scoreA = wa/n + ba/n
scoreB = wb/n + bb/n
Escolher Layout B se scoreB > scoreA, senão Layout A
```

**Override por variável de ambiente:** `P3M_VERTEX_RECORD_LAYOUT=a` ou `=b` força o layout.

---

## 1.11 Tabela Resumo de Tamanhos por Versão

### Bones

| Versão | PositionBone | AngleBone |
|--------|-------------|-----------|
| v0.5 / BON | 24 bytes | 28 bytes |
| v0.6 | 32 bytes | 36 bytes |
| v0.7 | 44 bytes | 48 bytes |
| v0.8 / v1.0 | 72 bytes | 76 bytes |

### Vértices

| Formato | Tamanho |
|---------|---------|
| SkinVertex v0.5 standard | 40 bytes (verificado em 131 arquivos) |
| SkinVertex Layout B (v0.5.2/v0.6/v0.7/v0.8/v1.0) | 40 bytes |
| SkinVertex Layout A (v0.7/v0.8 raro) | 40 bytes |
| MeshVertex | 32 bytes |
| Secondary Data v1.0 | 36 bytes |

---

# PARTE 2 — FORMATO FRM (Frame Motion)

## 2.1 Detecção de Versão

**Fonte:** `FrmParser.cs` → `FromBytes()`

Ler os primeiros **12 bytes**:

| Header (12 bytes incluindo `\0`) | Versão | Notas |
|----------------------------------|--------|-------|
| `"FRM Ver 1.2\0"` | v1.2_Origin | Uppercase "FRM"! |
| `"Frm Ver 1.2\0"` | v1.2 | Mixed-case "Frm" |
| `"Frm Ver 1.1\0"` | v1.1 | Com auto-detect 1x/2x |
| Nenhum match | v1.0 | Rewind para offset 0 |

> **ATENÇÃO:** v1.2_Origin usa `"FRM"` (uppercase). v1.1/v1.2 usam `"Frm"` (mixed-case). Os primeiros 3 bytes diferenciam.

---

## 2.2 FRM v1.0

**Fonte:** `FrmParser.cs` → bloco v1.0 + `ReadFrame()`

### Layout do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x00 | NumFrames | u8 | 1 |
| 0x01 | NumBones | u8 | 1 |
| 0x02 | Frame[NumFrames] | — | NumFrames × (9 + NumBones×64) |

> v1.0 **não tem header**. Se os primeiros 12 bytes não casam com nenhum header conhecido, tratar como v1.0.

### Frame v1.0 — (9 + NumBones × 64) bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | u8 | 1 | Option | Flags (uso do jogo) |
| 0x01 | f32 | 4 | PlusX | Deslocamento X **incremental** (delta) |
| 0x05 | f32 | 4 | PosY | Posição Y **absoluta** |
| 0x09 | f32[16]×N | N×64 | BoneMatrices | Matrizes 4×4, column-major |

### Matriz 4×4 Column-Major — 64 bytes

**Fonte:** `FrmParser.cs` → `ReadFrame()` — loop `for (int col = 0; col < 4; col++) for (int row = 0; row < 4; row++)`

Cada matrix é lida como 16 floats em **column-major order**:

```
Ordem de leitura: col0[0], col0[1], col0[2], col0[3], col1[0], col1[1], col1[2], col1[3], ...

Representação matricial:
    ┌                                    ┐
    │ col0[0]  col1[0]  col2[0]  col3[0] │
    │ col0[1]  col1[1]  col2[1]  col3[1] │
    │ col0[2]  col1[2]  col2[2]  col3[2] │
    │ col0[3]  col1[3]  col2[3]  col3[3] │
    └                                    ┘

Onde:
  - col0..col2: Rotação 3×3 (+ row3 geralmente 0)
  - col3: Translação (col3[0]=tx, col3[1]=ty, col3[2]=tz, col3[3] geralmente 1.0)
```

**Justificativa com o código:** Em `FrmParser.cs` → `ReadFrame()`:
```csharp
for (int col = 0; col < 4; col++)
{
    mat[col] = new float[4];
    for (int row = 0; row < 4; row++)
        mat[col][row] = allVals[off++];
}
```
O loop externo itera por **colunas** e o interno por **linhas dentro da coluna**, confirmando armazenamento column-major.

### Semântica de PlusX, PosY, PosZ

**Fonte:** `P3mConverters.cs` → `FrmConverters.ConvertFrmFrames()`

```
PlusX → INCREMENTAL (delta-X a cada frame, acumular somando)
PosY  → ABSOLUTO (posição Y naquele frame)
PosZ  → ABSOLUTO (quando presente via PosZ Trailer, senão 0)
```

Cálculo da posição acumulada:
```
float accX = 0
Para cada frame i:
    accX += frame[i].PlusX
    posição do personagem = (accX, frame[i].PosY, frame[i].PosZ)
```

---

## 2.3 FRM v1.1

**Fonte:** `FrmParser.cs` → bloco v1.1

### Layout do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x00 | Header | char[12] | 12 | `"Frm Ver 1.1\0"` |
| 0x0C | NumFrames | u16 | 2 |
| 0x0E | NumBones | u16 | 2 |
| 0x10 | Frame[NumFrames] | — | Tamanho variável |
| (opcional) | PosZ_Trailer | f32×NumFrames | NumFrames×4 |

### Auto-Detecção 1× vs 2× Matrizes

**Fonte:** `FrmParser.cs` → bloco de detecção de payload

```
payload = fileSize - 16    (header 12 + counts 4)
perFrame_1x = 1 + 4 + 4 + numBones × 64     = 9 + N×64
perFrame_2x = 1 + 4 + 4 + numBones × 64 × 2 = 9 + N×128

expected_1x      = numFrames × perFrame_1x
expected_1x_posz = expected_1x + numFrames × 4
expected_2x      = numFrames × perFrame_2x
expected_2x_posz = expected_2x + numFrames × 4

Se payload == expected_2x ou expected_2x_posz:
    Usar parser de double-matrix (ReadFrameV12)
    Se payload == expected_2x_posz → ler PosZ trailer
Senão:
    Usar parser single-matrix (ReadFrame)
    Se payload == expected_1x_posz → ler PosZ trailer
```

### PosZ Trailer

Após TODOS os frames, ler `NumFrames × f32`:
```
Para cada frame i:
    frame[i].PosZ = read_f32()
```

---

## 2.4 FRM v1.2

**Fonte:** `FrmParser.cs` → bloco v1.2 + `ReadFrameV12()`

### Layout do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x00 | Header | char[12] | 12 | `"Frm Ver 1.2\0"` |
| 0x0C | NumFrames | u16 | 2 |
| 0x0E | NumBones | u16 | 2 |
| 0x10 | Frame[NumFrames] | — | NumFrames × (9 + NumBones×128) |

### Frame v1.2 — (9 + NumBones × 128) bytes

| Offset | Tipo | Tamanho | Campo |
|--------|------|---------|-------|
| 0x00 | u8 | 1 | Option |
| 0x01 | f32 | 4 | PlusX |
| 0x05 | f32 | 4 | PosY |
| 0x09 | f32[16]×N | N×64 | Bones (matrizes primárias — rotação) |
| 0x09+N×64 | f32[16]×N | N×64 | Bones2 (matrizes secundárias — translação) |

### Semântica de Bones vs Bones2

**Fonte:** `P3mConverters.cs` → `FrmConverters.ConvertFrmFrames()` + análise de 1.609 arquivos reais

**Bones (primárias):**
- Colunas 0-2: Rotação 3×3 do bone naquele frame
- Coluna 3: **SEMPRE zero** — nunca contém translação

**Bones2 (secundárias):**
- Colunas 0-2: **SEMPRE identidade/zero** — nunca contém rotação
- Coluna 3: **Translação do bone** (col3[0]=tx, col3[1]=ty, col3[2]=tz)

### Bones Degenerados (det < 0.01)

**Fonte:** `FrmConverters.ConvertFrmFrames()` — bloco `if (d < 0.01f)`

```
Para cada bone bi:
    Calcular determinante da sub-matriz 3×3 de Bones[bi]:
    det = |col0[0]*(col1[1]*col2[2] - col1[2]*col2[1])
         - col1[0]*(col0[1]*col2[2] - col0[2]*col2[1])
         + col2[0]*(col0[1]*col1[2] - col0[2]*col1[1])|

    tx = Bones2[bi].col3[0]
    ty = Bones2[bi].col3[1]
    tz = Bones2[bi].col3[2]

    Se |det| < 0.01:
        Bone degenerado → usar identidade como rotação
        Transform final = identidade + translação de Bones2.col3
    Senão:
        Transform final = rotação de Bones + translação de Bones2.col3
```

**Estatísticas:**
- 60% dos arquivos: todos os bones têm rotação válida
- 37% dos arquivos: mistos (alguns degenerados) — sistema multi-FRM do jogo
- 3%: todos degenerados — animação translation-only

---

## 2.5 FRM v1.2_Origin

**Fonte:** `FrmParser.cs` → bloco v1.2_Origin + `ReadFrameV12Origin()`

### Layout do Arquivo

| Offset | Campo | Tipo | Tamanho | Notas |
|--------|-------|------|---------|-------|
| 0x00 | Header | char[12] | 12 | `"FRM Ver 1.2\0"` (uppercase!) |
| 0x0C | NumBones | **u32** | 4 | **Bones PRIMEIRO!** |
| 0x10 | NumFrames | **u32** | 4 | Frames depois |
| 0x14 | Frame[NumFrames] | — | variável |

> **CRÍTICO:** Ordem invertida em relação a v1.1/v1.2!
> - v1.1/v1.2: NumFrames (u16) primeiro, NumBones (u16) depois
> - v1.2_Origin: **NumBones (u32) primeiro**, NumFrames (u32) depois

### Frame v1.2_Origin — (4 + NumBones×64 + 9) bytes

| Offset | Tipo | Tamanho | Campo | Notas |
|--------|------|---------|-------|-------|
| 0x00 | u8[4] | 4 | Prefix | 4 bytes de propósito desconhecido |
| 0x04 | f32[16]×N | N×64 | BoneMatrices | Single matrix set |
| variável | f32 | 4 | PosY | Posição Y |
| variável | f32 | 4 | PlusX | Deslocamento X incremental |
| variável | u8 | 1 | Option | Flags |

> **Ordem dos campos dentro do frame é diferente:**
> - v1.0/v1.1/v1.2: Option, PlusX, PosY, BoneMatrices
> - v1.2_Origin: **Prefix, BoneMatrices, PosY, PlusX, Option**

---

# PARTE 3 — FORMATO BON (Skeleton-Only)

**Fonte:** `BonParser.cs` → `FromBytes()`

### Layout do Arquivo

| Offset | Campo | Tipo | Tamanho |
|--------|-------|------|---------|
| 0x00 | NumPositionBones | u8 | 1 |
| 0x01 | NumAngleBones | u8 | 1 |
| 0x02 | PositionBone[NumPos] | — | NumPos × 24 (formato v0.5) |
| variável | AngleBone[NumAng] | — | NumAng × 28 (formato v0.5) |

> Sem header de versão. O arquivo começa diretamente com contadores. Formatos de bone idênticos à seção 1.3.

---

# PARTE 4 — SISTEMA DE COORDENADAS E CONVERSÃO PARA glTF

## 4.1 Sistema Nativo do Grand Chase

P3M e FRM usam um sistema de coordenadas **left-handed, Y-up**.

## 4.2 Conversão para glTF (Right-Handed Y-up)

**Fonte:** `GltfIO.cs` → `GltfTransformScene()`

A conversão LH→RH é feita por **negação do eixo Z**:

### Vértices (posição e normal)
```
position.z *= -1
normal.z *= -1
```

### Faces (inversão de winding)
```
Para cada triângulo (i0, i1, i2):
    Trocar i1 ↔ i2 → (i0, i2, i1)
```

### Skeleton (translação dos joints)
```
joint.translation.z *= -1
```

### Matrizes de Animação (Mat4FlipZ)

**Fonte:** `MathHelpers.cs` → `Mat4FlipZ()`

A transformação de matrizes é equivalente à conjugação `M' = S × M × S⁻¹` onde `S = diag(1, 1, -1, 1)`:

```
Para cada elemento mat[col][row]:
    Se (row == 2) XOR (col == 2):
        mat[col][row] *= -1
```

Isto nega os elementos onde exatamente uma das coordenadas (linha ou coluna) é Z:
- Linha 2, colunas 0,1,3 → negados
- Coluna 2, linhas 0,1,3 → negados
- Linha 2, coluna 2 → NÃO negado (XOR = false)

### BindWorldPositions
```
bindWorldPos.z *= -1
```

### InverseBindMatrix
```
Aplicar mesma Mat4FlipZ
```

---

# PARTE 5 — CASOS ESPECIAIS E ARMADILHAS

## 5.1 Valores Sentinela

| Contexto | Valor | Significado |
|----------|-------|-------------|
| ChildIndex u8 (v0.5, v0.7) | 0xFF (255) | Slot vazio |
| ChildIndex u16 (v0.6) | 300 | Slot vazio |
| ChildIndex u16 (v0.8, v1.0) | 500 | Slot vazio |
| BoneIndex (v0.5 standard) | 0xFF (255) | Bone inválido (EXCETO se totalBones > 255) |
| BoneIndex u32 (Secondary v1.0) | 0xFFFFFFFF | Slot vazio |
| Weight (Secondary v1.0) | < 0.0 | Slot inválido |
| Padding (v0.5 bones) | 0xFFFF | Ler e descartar |

## 5.2 BoneIndex em v0.5.2 com totalBones > 255

**Fonte:** `P3mParser.cs` → `ParseV05()` — variável `useFullU32Bone`

Quando `numPositionBones + numAngleBones > 255`, o valor 255 NÃO é sentinela — é um índice válido. Nesse caso usar o u32 completo. Caso contrário, mascarar com `value & 0xFF` (bytes superiores podem conter lixo como 0xFFFF00xx).

## 5.3 Face Winding v1.0 Invertido

Todas as faces v1.0 devem ter i1 e i2 trocados: armazenar como `(i0, i2, i1)`.

## 5.4 Dualidade de Índices em v1.0

| Fonte | Tipo de Índice | Conversão para skeleton index |
|-------|---------------|-------------------------------|
| PrimaryVertex.BoneIndex | Absoluto (numPos + angleBoneIdx) | `skeleton_idx = BoneIndex - numPositionBones` |
| SecondaryData.BoneIdx[] | AngleBone-relativo (0-based) | `skeleton_idx = BoneIdx` (usar direto!) |

## 5.5 Hard Skinning vs Smooth Skinning

- v0.5 a v0.8: **hard skinning** (1 bone por vértice, weight = 1.0). NÃO aplicar blending.
- v1.0 com SecondaryData: **smooth skinning** (até 4 bones, weights explícitos).

## 5.6 Posição do Vértice é World-Space

As posições nos SkinVertex estão em **world-space relativo à bind pose**. Para obter a posição local (relativa ao bone):
```
bindWorldPos = soma das translações na cadeia parent→root do bone
localPos = vertex.position - bindWorldPos
```

Para v1.0 multi-bone, usar a **média ponderada** das translações de todos os bones:
```
offset = Σ(worldTranslation[boneIdx[i]] × weight[i])
```

## 5.7 FRM v1.0 com PosZ Trailer

Alguns arquivos v1.0 possuem dados PosZ após os frames. A detecção é feita na v1.1 pelo cálculo de payload, mas para v1.0 puro (u8 counts) não há mecanismo documentado de detecção no parser C# atual. O documento de especificação original indica que 53,9% dos arquivos v1.0 têm PosZ.

**NÃO CONFIRMADO:** O mecanismo exato de detecção de PosZ em v1.0 puro. O parser C# (`FrmParser.cs`) não implementa detecção de PosZ para v1.0 — apenas para v1.1. Os dados estatísticos (8.904 de 16.527 com PosZ) vêm do documento de especificação mas o código não mostra como distinguir.

## 5.8 ScaleOrPacked em v0.7 AngleBone

O campo de 4 bytes no offset 0x0C do AngleBone v0.7 pode conter tanto um float válido (Scale) quanto dados packed de propósito desconhecido. O parser lê como raw bytes e preserva ambas interpretações (f32 e u32) para garantir round-trip fiel.

## 5.9 v1.2_Origin — Prefix de 4 bytes

Os 4 bytes de prefix em cada frame v1.2_Origin têm propósito desconhecido. Ler e preservar para round-trip.

---

# PARTE 6 — DISTRIBUIÇÃO REAL (88.493 arquivos analisados)

## P3M (71.966 arquivos)

| Variante | Quantidade | % |
|----------|-----------|---|
| v0.5.2 shared+bonenames | 39.439 | 54,8% |
| v0.8 | 9.702 | 13,5% |
| v0.5.2 soup | 9.356 | 13,0% |
| v0.5.2 shared (sem bone names) | 5.050 | 7,0% |
| v0.7 | 3.959 | 5,5% |
| v0.6 | 2.936 | 4,1% |
| v1.0 | 1.524 | 2,1% |

## FRM (16.527 arquivos)

| Variante | Quantidade | % |
|----------|-----------|---|
| v1.0 com PosZ | 8.904 | 53,9% |
| v1.0 standard | 2.739 | 16,6% |
| v1.1 1x matrizes | 1.918 | 11,6% |
| v1.2 2x standard | 1.609 | 9,7% |
| v1.1 1x + PosZ | 1.351 | 8,2% |
| v1.2_Origin e outros | 6 | <0,1% |

---

# PARTE 7 — REFERÊNCIA DE ARQUIVOS-FONTE

| Arquivo C# | Função/Classe | Conteúdo |
|------------|---------------|----------|
| `Parsers/P3mParser.cs` | `FromBytes()` | Detecção de versão P3M |
| `Parsers/P3mParser.cs` | `ParseV05()` | Parser v0.5 e v0.5.2 |
| `Parsers/P3mParser.cs` | `ParseV06()` | Parser v0.6 |
| `Parsers/P3mParser.cs` | `ParseV07()` | Parser v0.7 |
| `Parsers/P3mParser.cs` | `ParseV08()` | Parser v0.8 |
| `Parsers/P3mParser.cs` | `ParseV10()` | Parser v1.0 |
| `Parsers/P3mParser.cs` | `FindBestFacePermutation()` | Algoritmo face permutation |
| `Parsers/P3mParser.cs` | `DetectVertexLayout()` | Auto-detecção Layout A/B |
| `Parsers/P3mParser.cs` | `RefineWindingV07V08()` | Winding refinement |
| `Parsers/FrmParser.cs` | `FromBytes()` | Detecção de versão FRM |
| `Parsers/FrmParser.cs` | `ReadFrame()` | Leitura de frame single-matrix |
| `Parsers/FrmParser.cs` | `ReadFrameV12()` | Leitura de frame double-matrix |
| `Parsers/FrmParser.cs` | `ReadFrameV12Origin()` | Leitura de frame v1.2_Origin |
| `Parsers/BonParser.cs` | `FromBytes()` | Parser de .bon |
| `Converters/P3mConverters.cs` | `ConvertP3mJoints()` | Conversão hierarquia → flat joints |
| `Converters/P3mConverters.cs` | `ConvertP3mVertices()` | Conversão vértices com bind-pose |
| `Converters/P3mConverters.cs` | `FrmConverters.ConvertFrmFrames()` | Conversão FRM → Keyframes |
| `Gltf/GltfIO.cs` | `GltfTransformScene()` | Conversão LH→RH (flip Z) |
| `Math/MathHelpers.cs` | `Mat4FlipZ()` | Conjugação de matrizes S*M*S⁻¹ |
| `Models/Models.cs` | `P3mConstants`, `FrmConstants` | Constantes e sentinelas |

---

*Documento gerado em 2026-08-26 a partir do código-fonte do CharacterStudio e da especificação FORMATOS_P3M_FRM_CHARACTERSTUDIO.md.*
