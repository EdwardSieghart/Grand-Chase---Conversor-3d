# Contexto do projeto

Arquivo de contexto para quem for continuar este trabalho — pessoa ou assistente
de IA. Reúne o estado atual, as decisões já tomadas (com o motivo), o que foi
verificado e onde estão as fontes, para não ser necessário refazer a
investigação.

Última atualização: 2026-08-26.

---

## O que é

Conversor de `.p3m` (modelos) e `.frm` (animações) do Grand Chase Classic para
glTF 2.0 binário (`.glb`). Python 3, **zero dependências externas**, roda em
Linux e Windows, com interface gráfica (tkinter) e linha de comando.

Substitui o `chaseconv` (Rust, só Windows), acrescentando textura embutida,
casamento automático de animações e conversão em lote.

---

## Estado atual

| Item | Situação |
|------|----------|
| P3M v0.5 | implementado, validado contra 131 arquivos |
| P3M v0.5.2 (índice u32) | implementado via autodetecção |
| P3M v0.6, 0.7, 0.8, 1.0 | **não implementados**; documentados; recusados com erro claro |
| FRM v1.1 | implementado, validado contra 68 arquivos |
| FRM v1.0 | implementado, **sem arquivo real para testar** |
| FRM v1.2, v1.2_Origin | **não implementados**; documentados; recusados |
| DDS DXT1/DXT3/DXT5, 16/24/32 bits | implementado, idêntico ao Pillow em 406 arquivos |
| Exportação GLB com skin e animação | implementado e validado no Blender |
| CLI | `info`, `convert`, `batch` |
| GUI | tkinter, com thread de trabalho e cancelamento |
| Testes | 100, só com a biblioteca padrão |
| Build | PyInstaller, `build_linux.sh` e `build_windows.bat` |
| Escrita de P3M/FRM | **não implementada** (só leitura) |

---

## Onde estão as fontes de informação

### Dentro do projeto

- `docs/ESPECIFICACAO_FORMATOS.md` — layout byte a byte de todas as versões de
  P3M, FRM e BON. **É a referência primária.** Contém uma correção anotada: o
  `SkinVertex` v0.5 tem 40 bytes, não 36.
- `docs/ARQUITETURA.md` — organização do código e o motivo de cada decisão.
- `docs/VALIDACAO.md` — o que foi verificado, como, e os números.
- `docs/GUIA_USO.md` — manual e solução de problemas.

### Fora do projeto (na máquina onde foi desenvolvido)

```
/run/media/eduardo/Arquivos/GC Engine - EDU NEW CHAR STUDIO/
├── conversor antigo/Chaseconv-master/src/     conversor antigo, em Rust
│   ├── format/p3m/internal.rs                 layout P3M v0.5 (limpo e correto)
│   ├── format/frm/internal.rs                 layout FRM v1.0 e v1.1
│   ├── format/gltf/mod.rs                     conversão left→right handed
│   ├── format/gltf/exporter.rs                exportação glTF
│   └── conversion/scene.rs                    representação intermediária
└── GC Engine - EDU NEW CHAR STUDIO/CharacterStudio/
    └── FORMATOS_P3M_FRM_CHARACTERSTUDIO.md    spec de partida (1240 linhas)

/run/media/eduardo/Arquivos/GRAND CHASE/       dados de teste
├── Models/     83 .p3m + .dds
├── Face/       .p3m de rostos
├── ANIMAÇÔES/  68 .frm
└── MODELO AULA/
```

O `internal.rs` do conversor antigo é a fonte mais confiável para a v0.5: é curto,
comentado e comprovadamente funcionava no jogo.

---

## Conhecimento do formato, condensado

### P3M v0.5

Cabeçalho de 27 bytes: `"Perfact 3D Model (Ver 0.5)\0"` (o erro de grafia é do
formato original). Depois:

```
u8   numPositionBones
u8   numAngleBones
PositionBone[numPositionBones]    24 bytes cada
AngleBone[numAngleBones]          28 bytes cada
u16  numVertices
u16  numFaces
char textureName[260]
Face[numFaces]                    3 × u16
SkinVertex[numVertices]           40 bytes cada
MeshVertex[numVertices]           32 bytes cada (pode estar truncado/ausente)
(pode haver bytes extras — ignorar)
```

- `PositionBone` = 3×f32 posição + 10×u8 filhos (`0xFF` = vazio) + 2 bytes de padding.
- `AngleBone` = 3×f32 posição + f32 escala + 10×u8 filhos + 2 bytes de padding.
- `SkinVertex` = 3×f32 posição + f32 peso + **4 bytes de índice de osso** +
  3×f32 normal + 2×f32 UV.
- `MeshVertex` = 3×f32 posição + 3×f32 normal + 2×f32 UV. **Não é usado.**

O índice de osso do vértice é **absoluto**: vale
`indice_do_angle_bone + numPositionBones`.

### FRM v1.1

Cabeçalho de 12 bytes: `"Frm Ver 1.1\0"`. Depois:

```
u16  numFrames
u16  numBones
por frame:
    u8   option
    f32  plusX
    f32  posY
    f32  matriz[16] × numBones      column-major
depois de TODOS os frames:
    f32  posZ × numFrames
```

- **`plusX` é incremental** (delta em relação ao frame anterior); `posY` e `posZ`
  são absolutos.
- As matrizes são **column-major**, a mesma ordem do glTF.
- **55 FPS**, constante do motor; não está no arquivo.
- v1.0 é igual, mas sem cabeçalho, com contadores de 1 byte e sem o bloco de
  `posZ`.

### Conversão left-handed → right-handed

O Grand Chase usa left-handed Y-up (DirectX); o glTF usa right-handed Y-up. São
**quatro** operações, todas necessárias:

1. negar Z de posições, normais e translações de joint;
2. inverter o winding dos triângulos (trocar os índices 1 e 2 de cada trio);
3. negar Z da translação de raiz dos keyframes;
4. conjugar as matrizes de animação: `M' = S · M · S`, com `S = diag(1,1,-1)`.

**O item 4 é o que se esquece.** Negar só a translação deixa as rotações na mão
errada e o personagem anima ao contrário.

### Mapeamento para glTF

- joints = AngleBones, um para um.
- a translação de um joint vem do PositionBone que o lista como filho.
- posição final do vértice = `posição no SkinVertex + translação mundial do joint`.
- inverse bind matrix = translação pelo **negativo** da posição mundial do joint
  (funciona porque o bind pose é puramente translacional).
- hierarquia de nós: joints `0..J-1`, depois um nó `"root"` (índice `J`) que é pai
  de todos os joints sem pai, depois os nós de malha.
- animação: o nó `"root"` recebe um canal de `translation`; cada joint recebe um
  canal de `rotation` (matriz → quaternion).

---

## Decisões tomadas, e por quê

| Decisão | Motivo |
|---------|--------|
| Python em vez de Rust | roda nos dois sistemas sem toolchain nem recompilação |
| Zero dependências | sem `pip install` para usar; executável de 8 MB em vez de 60 MB |
| DDS e PNG escritos à mão | evita depender de Pillow; verificado como idêntico a ele |
| tkinter | acompanha o Python; Qt traria dezenas de MB para uma janela simples |
| GLB como saída | arquivo único, autocontido, importado nativamente em todo lugar |
| Matrizes column-major internamente | é a ordem do FRM **e** do glTF; elimina transposições |
| Vetores como tuplas imutáveis | evita aliasing acidental entre vértices |
| `to_right_handed()` explícita, na exportação | mantém a cena fiel ao arquivo em memória, o que permite depurar contra o hex dump |
| `export_glb` **recusa** cena left-handed | modelo espelhado é bug difícil de notar |
| `P3mFile` separada de `Scene` | permite distinguir erro de leitura de erro de interpretação |
| Autodetectar u8 vs u32 pelos dados | nada no cabeçalho indica qual é; testar as hipóteses é confiável com milhares de vértices |
| Malha sem skinning → sem esqueleto | skin com pesos zero tem comportamento indefinido no glTF |
| Tolerar bytes extras, bloco truncado, normais ruins | são comuns nos arquivos reais; falhar por isso inutilizaria o conversor |
| **Não** tolerar índice de face fora do intervalo | é o sintoma de layout desalinhado; continuar geraria geometria corrompida em silêncio |
| Interpolação linear nas animações | o jogo usa Bézier com tangentes desconhecidas; a 55 Hz a diferença é desprezível |
| Sem `MERGE()` no PyInstaller | `MERGE` quebra build de arquivo único: o segundo binário fica sem libpython |
| Thread de trabalho comunica por `queue` | tkinter não é thread-safe; atualizar widget de outra thread trava de forma intermitente |

---

## Armadilhas encontradas, para não repetir

1. **`SkinVertex` de 40 bytes, não 36.** A spec de partida dizia 36 no título mas
   a tabela de offsets somava 40. Sempre confira contra o tamanho real do
   arquivo.
2. **Índice de osso em duas codificações.** `mon_void_dragon3.p3m` (248+248
   ossos) usa `u32`. Índice absoluto acima de 255 não cabe em um byte.
3. **Três arquivos sem skinning nenhum** (`AR 15 GC.p3m`, `ARMA.p3m`,
   `mesh_abta180169.p3m`): todos os vértices com `0xFF`.
4. **`pos_z` do FRM fica no fim do arquivo**, não dentro de cada frame.
5. **`plus_x` acumula, `pos_y`/`pos_z` não.** Trocar isso deixa o personagem
   parado ou subindo sem parar.
6. **`MERGE()` do PyInstaller quebra onefile.** Sintoma: "Failed to load Python
   shared library".
7. **Blender via Flatpak não vê o `/tmp` do host.** Coloque o script numa pasta
   do projeto.
8. **Caminhos com espaço quebram os argumentos do Blender.** Por isso
   `blender_check.py` aceita `--list arquivo.txt`.
9. **Blender exige caminho absoluto** no importador; caminho relativo dá "Please
   select a file".
10. **O `abta180169.glb` do conversor antigo não é par do
    `mesh_abta180169.p3m`.** Nome interno da malha indica origem diferente. Não
    serve como referência de comparação.

---

## Ambiente onde foi desenvolvido

- Fedora Linux, Python 3.14.7, tkinter presente, git presente.
- **Sem** `cargo` (então o conversor antigo não pôde ser compilado para comparar).
- **Sem** `gh` CLI (o push para o GitHub precisa de credencial do usuário).
- **Sem** node/npm (o `gltf-validator` oficial não pôde ser usado; daí o
  `tools/glb_inspect.py` escrito à mão a partir da especificação).
- Pillow 12.3 e numpy 2.4 disponíveis — usados **só** para validação cruzada.
- Blender 5.2 via Flatpak (`flatpak run org.blender.Blender`).
- PyInstaller 6.22.2 instalado com `pip install --user`.

---

## Próximos passos sugeridos, em ordem de valor

1. **P3M v0.6 e v1.0.** Layout já documentado. v1.0 tem multi-bone skinning
   (mais de um osso por vértice), que o `Vertex` atual não suporta — precisaria
   virar lista de `(joint, weight)`, e o exportador GLB já escreve `JOINTS_0`/
   `WEIGHTS_0` como `VEC4`, então cabem 4 influências sem mudar o formato de
   saída.
2. **P3M v0.7 e v0.8.** Mais trabalhosas: exigem o algoritmo de face permutation
   (120 combinações) e autodetecção de layout de vértice. Ambos documentados.
3. **FRM v1.2.** Tem duas listas de matrizes (`Bones` = rotação, `Bones2` =
   translação) e bones degenerados em cerca de 37% dos arquivos.
4. **Escrever P3M/FRM de volta.** Habilitaria modding: editar no Blender e
   devolver para o jogo. Exige importador de glTF e escritores; o `BinaryWriter`
   já existe.
5. **Visualização prévia na interface.** Um viewport 3D em tkinter é limitado;
   uma alternativa razoável é renderizar uma miniatura estática do primeiro
   frame.
6. **Conversão paralela no lote.** `convert_batch` é sequencial. Com
   `concurrent.futures.ProcessPoolExecutor` o ganho é linear no número de
   núcleos, já que cada arquivo é independente.

---

## Como verificar que nada quebrou

```bash
# 1. testes (rápido, sem dependências)
python3 -m unittest discover -s tests -t .

# 2. validação em massa contra a coleção de arquivos do jogo
python3 tools/validate_all.py --cross-check --out-dir out/glb "/caminho/GRAND CHASE"

# 3. importação real no Blender
ls -d "$PWD"/out/glb/*.glb > out/lista.txt
flatpak run org.blender.Blender --background --factory-startup \
    --python "$PWD/tools/blender_check.py" -- --list "$PWD/out/lista.txt"
```

Os três precisam passar. O resultado esperado está em `docs/VALIDACAO.md`; a
linha mais importante da saída do Blender é `unweighted_verts: 0`, porque vértice
sem peso é um defeito que a validação estrutural do glTF não detecta.
