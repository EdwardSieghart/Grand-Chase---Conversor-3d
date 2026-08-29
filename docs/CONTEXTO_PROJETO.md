# Contexto do projeto

Arquivo de contexto para quem for continuar este trabalho — pessoa ou assistente
de IA. Reúne o estado atual, as decisões já tomadas (com o motivo), o que foi
verificado e onde estão as fontes, para não ser necessário refazer a investigação.

Versão 1.4.0. **Atenção: o disco foi remontado de `/run/media/eduardo/Arquivos` para `/mnt/Arquivos`.** Última atualização: 2026-08-26.

---

## O que é

Conversor **bidirecional** entre os formatos do Grand Chase Classic e glTF 2.0:

```
P3M + FRM  ──▶  GLB
GLB / glTF ──▶  P3M + FRM
```

Python 3, **zero dependências externas**, roda em Linux e Windows, com interface
gráfica (tkinter, tema escuro) e linha de comando. O sentido da conversão é
deduzido das extensões.

Substitui o `chaseconv` (Rust, só Windows), cujo importador de glTF vinha com o
aviso *"GLTF importing does not work properly yet"* no próprio código.

---

## Estado atual

| Item | Situação |
|------|----------|
| P3M v0.5 — leitura | validada contra 131 arquivos |
| P3M v0.5 — escrita | validada por ida e volta, 131/131 |
| P3M v0.5.2 (índice u32) | autodetectado na leitura, escolhido na escrita |
| P3M v0.6, 0.7, 0.8, 1.0 | **não implementados**; documentados; recusados com erro claro |
| FRM v1.1 — leitura e escrita | validadas, 70/70 na ida e volta |
| FRM v1.0 — leitura | implementada, **sem arquivo real para testar** |
| FRM v1.2, v1.2_Origin | **não implementados**; documentados; recusados |
| glTF 2.0 — escrita (`glb.py`) | validada no Blender, 131/131 |
| glTF 2.0 — leitura (`gltf_in.py`) | validada com arquivos próprios e do Blender |
| DDS DXT1/3/5 + 16/24/32 bits | leitura idêntica ao Pillow em 406 arquivos |
| Escrita de DDS | implementada, sem compressão (24/32 bits); é o padrão na volta |
| Leitura de PNG | implementada; idêntica ao Pillow nas 406 texturas |
| Skinning suave (multi-osso) | **não suportado**; fica o osso de maior peso |
| CLI | `info`, `convert`, `batch`, nos dois sentidos |
| GUI | tela única, tema escuro, direção automática, limpa a lista ao fim |
| Arrastar e soltar | via `tkinterdnd2`, **opcional** em runtime e embutido nos executáveis |
| Muitas animações num só GLB | suportado; testado com 68 |
| Vários modelos num só GLB | suportado, com uma `skin` por esqueleto; `--merge` na CLI, padrão na GUI |
| Textura por malha | suportado; um material por malha no GLB |
| Detecção de textura | 127/127 modelos; 4 estratégias, com aviso quando é aproximação |
| Testes | 239, só com a biblioteca padrão; rodam no CI em Linux e Windows |
| Preferências | `gc3d.ini` na pasta do executável, com reserva na config do sistema |
| Distribuição | um arquivo por sistema: `.exe` e `.AppImage`, gerados pelo CI na tag |
| Zip de exemplos | `build/exemplos.py` → `release/GrandChase3D-<versão>-exemplos.zip` |
| Build Linux | `build/linux/build.sh` → `dist/linux/gc3d` — **funciona** (para testar) |
| AppImage | `build/linux/appimage.sh`, em container Ubuntu 22.04 — **funciona** |
| Build Windows nativo | `build/windows/build.bat` — roda no CI a cada tag |
| Publicação | `.github/workflows/release.yml`, automática na tag `v*` |
| Publicação no GitHub | **feita**: github.com/EdwardSieghart/Grand-Chase---Conversor-3d |

---

## Pendências conhecidas

1. **O `.exe` nunca foi executado por um humano.** Ele é compilado e submetido a um
   teste de fumaça pelo CI num Windows de verdade — versão, `config`, conversão de
   ida e volta, redirecionamento de saída e código de erro —, mas ninguém abriu a
   interface e clicou nos botões. O ponto de maior risco é o
   `gc3d_app.attach_console()`, que só existe por causa do Windows e é o único
   trecho sem cobertura em máquina Linux.
   - A tentativa anterior de gerar o `.exe` por Wine foi **aposentada**. Ela
     produzia o executável de linha de comando, mas nunca a interface: a
     `tcl86t.dll` não carrega no Wine.
2. **O AppImage cobre glibc 2.35 ou mais nova.** Medido com `objdump`, vindo de
   `libpython3.10.so`, `libtcl8.6`, `libtk8.6` e `libBLT`. Cobre Ubuntu 22.04+,
   Debian 12+, Fedora 36+ e RHEL 9+. Sistemas mais antigos precisam rodar pelo
   código-fonte. Para descer esse número, seria preciso construir numa base mais
   antiga ainda, como `manylinux`.
3. **Só x86-64.** O `appimage_interno.sh` já usa `uname -m` e funcionaria em
   `aarch64`, mas nenhum build ARM foi feito nem o CI tem um job para isso.
4. **Nada foi testado dentro do jogo.** A evidência é de consistência de formato e
   de ida e volta, não de execução no Grand Chase.

---

## Onde estão as fontes de informação

### Dentro do projeto

- `docs/ESPECIFICACAO_FORMATOS.md` — layout byte a byte de todas as versões de
  P3M, FRM e BON. **Referência primária.** Contém uma correção anotada: o
  `SkinVertex` v0.5 tem 40 bytes, não 36.
- `docs/ARQUITETURA.md` — organização do código e o motivo de cada decisão,
  incluindo uma seção inteira sobre a direção inversa.
- `docs/VALIDACAO.md` — o que foi verificado, como, os números, e os três bugs que
  a validação encontrou.
- `docs/GUIA_USO.md` — manual e solução de problemas.

### Fora do projeto (na máquina onde foi desenvolvido)

```
/mnt/Arquivos/GC Engine - EDU NEW CHAR STUDIO/
├── conversor antigo/Chaseconv-master/src/     conversor antigo, em Rust
│   ├── format/p3m/internal.rs                 layout P3M v0.5 (limpo e correto)
│   ├── format/p3m/exporter.rs                 escrita de P3M (base da nossa)
│   ├── format/frm/internal.rs                 layout FRM v1.0 e v1.1
│   ├── format/frm/exporter.rs                 escrita de FRM (tem um bug: trata
│   │                                          pos_z como delta; o correto é absoluto)
│   ├── format/gltf/mod.rs                     conversão left<->right handed
│   ├── format/gltf/importer.rs                importador quebrado (não reamostra)
│   └── conversion/scene.rs                    representação intermediária
└── GC Engine - EDU NEW CHAR STUDIO/CharacterStudio/
    └── FORMATOS_P3M_FRM_CHARACTERSTUDIO.md    spec de partida (1240 linhas)

/mnt/Arquivos/GRAND CHASE/       dados de teste
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

O índice de osso do vértice é **absoluto**: `indice_do_angle_bone +
numPositionBones`. Duas codificações, sem indicação no cabeçalho:
`(idx, idx, 0xFF, 0xFF)` ou `u32` little-endian (obrigatória acima de 255 ossos
totais).

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
  são absolutos. O exportador do chaseconv erra isso para `posZ`.
- As matrizes são **column-major**, a mesma ordem do glTF.
- **55 FPS**, constante do motor; não está no arquivo.
- v1.0 é igual, mas sem cabeçalho, com contadores de 1 byte e sem o bloco de `posZ`.
- **Medido:** das 93.319 matrizes dos 68 arquivos, **zero** têm translação (99,92%
  rotação pura, 0,08% zeradas). Exportar só rotação para o glTF não perde nada.

### Conversão left-handed ↔ right-handed

O Grand Chase usa left-handed Y-up (DirectX); o glTF usa right-handed Y-up. São
**quatro** operações, todas necessárias, e a operação é a sua própria inversa
(`Scene._flip_z`, exposta como `to_right_handed` / `to_left_handed`):

1. negar Z de posições, normais e translações de joint;
2. inverter o winding dos triângulos (trocar os índices 1 e 2 de cada trio);
3. negar Z da translação de raiz dos keyframes;
4. conjugar as matrizes de animação: `M' = S · M · S`, com `S = diag(1,1,-1)`.

**O item 4 é o que se esquece.** Negar só a translação deixa as rotações na mão
errada e o personagem anima ao contrário. Há um teste específico
(`test_flip_z_conjugate_reverses_rotation_sense`).

### Mapeamento para glTF

- joints = AngleBones, um para um.
- a translação de um joint vem do PositionBone que o lista como filho.
- posição final do vértice = `posição no SkinVertex + translação mundial do joint`.
- inverse bind matrix = translação pelo **negativo** da posição mundial do joint.
- hierarquia: joints `0..J-1`, depois um nó `"root"` (índice `J`) pai de todos os
  joints sem pai, depois os nós de malha.
- animação: o nó `"root"` recebe um canal de `translation`; cada joint recebe um
  canal de `rotation`.

### Reconstrução, no caminho de volta

- **um PositionBone por AngleBone** (1:1). `numPositionBones` muda em relação ao
  original (14 → 15, por exemplo), mas a lista de AngleBones fica idêntica, que é
  o que o jogo usa.
- `skinVertex.position = vertex.position - translação mundial do joint`.
- animações **reamostradas para 55 FPS**, com slerp na rotação.
- `plusX` volta a ser delta; `posY`/`posZ` continuam absolutos.

---

## Decisões tomadas, e por quê

| Decisão | Motivo |
|---------|--------|
| Python em vez de Rust | roda nos dois sistemas sem toolchain nem recompilação |
| Zero dependências | sem `pip install` para usar; executável de 9 MB em vez de 60 MB |
| DDS e PNG escritos à mão | evita depender de Pillow; verificado como idêntico a ele |
| tkinter | acompanha o Python; Qt traria dezenas de MB para uma janela simples |
| Paleta escura fixa, não a do sistema | detectar GTK/Windows dá trabalho e o tkinter não acompanha; fixa, a aparência é igual nas duas plataformas |
| Sentido deduzido, não escolhido | dado o que entrou, só existe um destino; oferecer escolha só cria chance de erro |
| Lista limpa ao terminar | o estado após converter é "concluído"; deixar os arquivos convida a reconverter por engano |
| GLB como saída | arquivo único, autocontido, importado nativamente em todo lugar |
| Matrizes column-major internamente | é a ordem do FRM **e** do glTF; elimina transposições |
| Vetores como tuplas imutáveis | evita aliasing acidental entre vértices |
| `to_right_handed`/`to_left_handed` explícitas | mantém a cena fiel ao arquivo em memória, o que permite depurar contra o hex dump |
| `export_glb` **recusa** cena left-handed, `scene_to_p3m` recusa right-handed | modelo espelhado é bug difícil de notar |
| `P3mFile` separada de `Scene` | permite distinguir erro de leitura de erro de interpretação; na escrita, permite inspecionar antes de gravar |
| Autodetectar u8 vs u32 pelos dados | nada no cabeçalho indica qual é; testar as hipóteses é confiável com milhares de vértices |
| Reordenar joints por `bone_N` | o Blender reordena; sem isso a numeração mudaria a cada volta e os `.frm` do jogo deixariam de casar |
| Posição no mundo fora do bind pose | é do FRM, não do P3M; contá-la duas vezes faz o modelo flutuar |
| Malha sem skinning → sem esqueleto (ida) e sentinela `0xFF` preservado (volta) | skin com pesos zero tem comportamento indefinido no glTF; preservar o sentinela fecha a ida e volta |
| Tolerar bytes extras, bloco truncado, normais ruins | são comuns nos arquivos reais; falhar por isso inutilizaria o conversor |
| **Não** tolerar índice de face fora do intervalo | é o sintoma de layout desalinhado; continuar geraria geometria corrompida em silêncio |
| Interpolação linear nas animações | o jogo usa Bézier com tangentes desconhecidas; a 55 Hz a diferença é desprezível |
| Sem `MERGE()` no PyInstaller | `MERGE` quebra build de arquivo único: o segundo binário fica sem libpython |
| Thread de trabalho comunica por `queue` | tkinter não é thread-safe; atualizar widget de outra thread trava de forma intermitente |
| `tkinterdnd2` opcional em runtime, embutido no build | tkinter não tem drag and drop; assim o usuário final ganha o recurso sem quebrar a regra de zero dependências para rodar |
| `AnimationIndex` compartilhado entre CLI e GUI | lê cada `.frm` uma vez e garante que as duas interfaces selecionem igual |
| Avisar quando nenhuma animação casa | antes era silencioso e parecia que o programa não suportava várias animações |
| Incluir todas as animações por padrão | a contagem de ossos é filtro grosseiro (7 esqueletos distintos com 15 ossos); descartar em silêncio parece defeito |
| Juntar num GLB só por padrão na GUI | um personagem vem em vários `.p3m`; um arquivo com tudo é mais útil |
| Agrupar por assinatura de esqueleto, não por contagem de ossos | há 18 esqueletos nos 127 modelos, 7 deles com 15 ossos; forçar um esqueleto só deformaria a malha |
| Uma `skin` por esqueleto dentro do mesmo GLB | o glTF permite várias; é o único jeito correto de ter tudo num arquivo |
| Animação vai para **um** grupo, não para todos os compatíveis | duplicar geraria várias actions de mesmo nome no Blender |
| DDS sem compressão na volta | 281 das 406 texturas do jogo já são sem compressão; é aceito e sem perda. DXT seria com perda por ganho só de espaço |
| `has_alpha` decidido pelos pixels, não pelo formato | nenhuma das 406 texturas do jogo tem transparência real; usar o formato faria toda textura opaca virar 32 bits |
| Sem mipmaps no DDS escrito | 326 das 406 texturas originais também não têm |
| Fallback de textura por prefixo, com aviso | os rostos têm uma textura por expressão e nem sempre a `_00`; pegar uma é melhor que nada, desde que avisado |
| Um executável por sistema, sem pasta em volta | com um ponto de entrada só, os lançadores e a cópia do código em `app/` eram embalagem em torno de um arquivo que já se basta |
| `dist/` e `release/` fora do git, binários via GitHub Release | binário commitado fica no histórico para sempre; cada rebuild somaria outros megabytes ao clone |
| Preferências ao lado do executável, não na pasta do sistema | deixa o programa portátil; a pasta do sistema é só reserva para quando não há permissão de escrita |
| `.exe` no subsistema gráfico, com o console recuperado à mão | o clique duplo é o uso normal, e uma janela preta atrás da interface a cada abertura é pior que a limitação do prompt não esperar |

---

## Armadilhas encontradas, para não repetir

Da direção direta:

1. **`SkinVertex` de 40 bytes, não 36.** A spec de partida dizia 36 no título mas
   a tabela de offsets somava 40. Sempre confira contra o tamanho real do arquivo.
2. **Índice de osso em duas codificações.** `mon_void_dragon3.p3m` (248+248 ossos)
   usa `u32`.
3. **Três arquivos sem skinning nenhum** (`AR 15 GC.p3m`, `ARMA.p3m`,
   `mesh_abta180169.p3m`): todos os vértices com `0xFF`.
4. **`pos_z` do FRM fica no fim do arquivo**, não dentro de cada frame.
5. **`plus_x` acumula, `pos_y`/`pos_z` não.**

Da direção inversa (as três primeiras foram bugs reais, achados por
`roundtrip_check.py` e pelo ciclo com o Blender):

6. **Escrever `bone_index & 0xFF` trunca acima de 255 ossos.** Escolher a
   codificação `u32` é obrigatório, não opcional.
7. **`JOINTS_0` indexa `skin.joints`, não os nós.** Confundir os dois *funciona*
   nos arquivos deste projeto (as ordens coincidem) e gruda vértices no osso errado
   em arquivos de outras ferramentas.
8. **Translação de ancestrais que não são ossos precisa ser acumulada.** O Blender
   põe transformação no nó do objeto Armature; ignorá-la deslocou o modelo 0,46 em Y.
9. **O Blender assa o primeiro keyframe do movimento da raiz no bind pose.** Se
   isso entrar no P3M, o deslocamento é contado duas vezes.
10. **Animações precisam ser reamostradas.** Assumir 55 FPS na entrada é o que
    quebrava o importador do conversor antigo.
11. **O Blender divide vértices em costuras de UV** (74 → 84 num caso). Geometria
    idêntica, contagem diferente.
12. **O Blender usa 24 FPS por padrão** e quantiza os keyframes nesse FPS ao
    exportar (120 → 118 frames).

De ferramental:

13. **`MERGE()` do PyInstaller quebra onefile.** Sintoma: "Failed to load Python
    shared library".
14. **Blender via Flatpak não vê o `/tmp` do host.** Ponha o script numa pasta do
    projeto.
15. **Caminhos com espaço quebram os argumentos do Blender.** Por isso
    `blender_check.py` e `blender_reexport.py` aceitam `--list arquivo.txt`.
16. **Blender exige caminho absoluto** no importador; relativo dá "Please select a
    file".
17. **O `abta180169.glb` do conversor antigo não é par do `mesh_abta180169.p3m`.**
    Nome interno da malha indica origem diferente. Não serve como referência.
18. **O tkdnd entrega os caminhos como lista Tcl**, com chaves nos que têm espaço:
    `{/a b/c.p3m} /d.frm`. Um `split()` quebra o caso comum, porque as pastas deste
    projeto têm espaço no nome. Ver `_parse_drop_data` e seus sete testes.
19. **A dica de lista vazia precisa de `_refresh_list()` na inicialização.**
    Chamar só `_refresh_direction()` deixava a dica de arrastar invisível ao abrir.
20. **`spectacle -a` captura a janela ativa, que pode não ser a do programa.** Para
    conferir a interface por screenshot, use `import -window "<titulo da janela>"`.
21. **Contagem de ossos NÃO identifica um esqueleto.** Nos 127 modelos há 18
    esqueletos distintos, sete deles com exatamente 15 ossos. Agrupar por contagem
    misturaria bind poses. Use `skeleton_signature` (translações + hierarquia).
22. **O índice de malha do nó tem de ser previsto antes de a malha existir.** Os
    nós são criados antes dos acessores; um contador corrido entre grupos resolve.
23. **`bpy.ops.import_scene.gltf` deixa os objetos importados selecionados.** Usar
    `bpy.context.selected_objects` é mais confiável que diferença de conjuntos: a
    cena inicial do Blender reaparece durante o import.
24. **Todo PNG que este projeto escreve é RGBA.** Se `has_alpha` seguisse o tipo de
    cor do PNG, toda textura opaca viraria DDS de 32 bits. Decida pelos pixels.
25. **O DDS guarda os bytes em ordem BGR(A)**, consequência das máscaras
    `R=0xFF0000 G=0xFF00 B=0xFF`. Trocar por RGB deixa o modelo azulado.
26. **Não pegue `materials[0]` às cegas** ao extrair textura de um glTF: use o
    material da primeira primitiva com geometria. Arquivos reais têm vários
    materiais e o índice 0 pode não ser o da malha principal.
27. **O numpy foi removido do sistema durante o desenvolvimento.** A validação
    cruzada agora usa só Pillow, comparando bytes de uma vez (rápido) e só entrando
    no caminho lento quando diferem.
28. **No modo `batch` os avisos dos arquivos bem-sucedidos não apareciam.** Só as
    falhas eram impressas; agora `-v` mostra todos.
29. **`AttachConsole` pode substituir os identificadores padrão do processo.** Num
    `.exe` do subsistema gráfico, ler os identificadores herdados **depois** dele
    fazia `gc3d.exe info a.p3m > lista.txt` escrever na tela em vez do arquivo. A
    leitura tem de vir antes. E `GetStdHandle` precisa de `restype = c_void_p`,
    senão o `ctypes` assume `c_int` e trunca o `HANDLE` em 64 bits.
30. **`pkill -f <padrão>` mata o próprio shell** quando o padrão aparece na linha
    de comando em execução. Use o truque do colchete: `pkill -f "[G]randChase"`.
31. **Ao salvar `.ico`, o Pillow não amplia.** Um tamanho pedido sem imagem
    correspondente em `append_images` é gerado a partir da **última** da lista, via
    `thumbnail()`, que só reduz. Fornecendo apenas as versões pequenas, o 48, o 64
    e o 128 nasciam do 32 e continuavam com 32 pixels. Entregue todos os tamanhos
    prontos, e confira o resultado.
32. **`ldd --version | head -1` sob `pipefail` "falha".** O `head` fecha o cano, o
    `ldd` morre com SIGPIPE e um `|| echo` no fim dispara mesmo tendo dado certo.
    Use `sed -n '1{s/.*[[:space:]]//;p}'`.
33. **`--userns=keep-id` do podman impede o `apt` no container** (`Permission
    denied` em `/var/lib/apt/lists`). Sem ela, o rootless já mapeia o root do
    container para o seu usuário, e os arquivos gerados saem com o dono certo.
34. **Gravar preferências só ao fechar perde tudo** quando a janela é destruída sem
    `WM_DELETE_WINDOW` — sessão encerrada, gerenciador de janelas matando o
    processo. Grave a cada mudança, com adiamento para juntar rajadas.
35. **O disco pode ser remontado em outro caminho.** Era
    `/run/media/eduardo/Arquivos`, virou `/mnt/Arquivos`. As ferramentas recebem
    caminhos por argumento, então nada no código quebrou.

---

## Ambiente onde foi desenvolvido

- Fedora Linux, Python 3.14.7, tkinter presente, git presente.
- **Sem** `cargo` (o conversor antigo não pôde ser compilado para comparar).
- **Sem** node/npm (o `gltf-validator` oficial não pôde ser usado; daí o
  `tools/glb_inspect.py` escrito à mão a partir da especificação).
- Pillow e numpy disponíveis — usados **só** para validação cruzada, e o Pillow
  também para gerar o ícone em `build/icone/`.
- Blender 5.2 via Flatpak (`flatpak run org.blender.Blender`).
- PyInstaller 6.x e `tkinterdnd2`, num ambiente virtual do projeto.
- `podman`, necessário para montar o AppImage no container Ubuntu 22.04.
- Nada disso é exigido para **usar** o programa, e nem para compilá-lo: os dois
  executáveis saem do GitHub Actions.

---

## Próximos passos sugeridos, em ordem de valor

1. **Abrir o `.exe` num Windows de verdade.** Ele é compilado e passa pelo teste de
   fumaça do CI, mas ninguém clicou nos botões da interface. Vale conferir o
   arrastar e soltar, o `gc3d.ini` nascendo ao lado do `.exe`, e o comportamento
   do console descrito em `gc3d_app.attach_console()`.
2. **Testar no jogo.** É a única camada de validação que falta.
3. **P3M v0.6 e v1.0.** Layout documentado. A v1.0 tem multi-bone skinning, que
   exige `Vertex` virar lista de `(joint, weight)`; o exportador GLB já escreve
   `VEC4`, então cabem 4 influências sem mudar o formato de saída.
4. **P3M v0.7 e v0.8.** Mais trabalhosas: exigem o algoritmo de face permutation
   (120 combinações) e autodetecção de layout de vértice. Ambos documentados.
5. **FRM v1.2.** Duas listas de matrizes (`Bones` = rotação, `Bones2` = translação)
   e bones degenerados em cerca de 37% dos arquivos.
6. **Compressão DXT na escrita de DDS.** A escrita sem compressão já funciona e é
   o padrão, mas gera arquivos grandes: uma textura 128×128 sai com 49 KB em vez
   dos 8 KB de um DXT1. Comprimir reduziria o tamanho no disco do jogo.
7. **AppImage para `aarch64`.** O `appimage_interno.sh` já usa `uname -m` e
   funcionaria; falta um job no CI e uma máquina para testar.
8. **Conversão paralela no lote.** `convert_batch` é sequencial; com
   `concurrent.futures.ProcessPoolExecutor` o ganho é linear no número de núcleos,
   já que cada arquivo é independente.

---

## Como verificar que nada quebrou

```bash
# 1. testes (rápido, sem dependências)
python3 -m unittest discover -s tests -t .

# 2. direção direta sobre a coleção de arquivos do jogo
python3 tools/validate_all.py --cross-check --out-dir out/glb "/caminho/GRAND CHASE"

# 3. ida e volta — pega o que as outras duas não pegam
python3 tools/roundtrip_check.py --anim-dir "/caminho/ANIM" "/caminho/GRAND CHASE"

# 4. importação real no Blender
ls -d "$PWD"/out/glb/*.glb > out/lista.txt
flatpak run org.blender.Blender --background --factory-startup \
    --python "$PWD/tools/blender_check.py" -- --list "$PWD/out/lista.txt"

# 5. interoperabilidade com glTF de outra ferramenta
flatpak run org.blender.Blender --background --factory-startup \
    --python "$PWD/tools/blender_reexport.py" -- --list out/lista.txt --out-dir out/blender
python3 gc3d_cli.py batch out/blender -o out/volta
```

Resultado esperado, registrado em `docs/VALIDACAO.md`: 131/131 lidos, 68/68 FRM
sem sobra, 406/406 DDS com erro máximo 0, 131/131 GLB válidos, Blender 131/131 com
`unweighted_verts: 0`, e ida e volta 131/131 modelos e 70/70 animações.

O passo 3 é o mais valioso ao mexer na conversão: compara o resultado com o arquivo
de origem, e foi ele que pegou o bug do índice `u32`.
