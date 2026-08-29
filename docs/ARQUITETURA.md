# Arquitetura

Documento sobre **como** o código está organizado e, principalmente, **por quê**.
Para o layout dos arquivos binários, ver
[ESPECIFICACAO_FORMATOS.md](ESPECIFICACAO_FORMATOS.md).

---

## Decisões de base

### Python 3, sem dependências externas

A escolha mais consequente do projeto. O motivo é operacional: o programa
precisa rodar em Linux e Windows sem que o usuário monte um ambiente de
desenvolvimento.

- **Python em vez de Rust** (a linguagem do conversor antigo): não exige
  toolchain nem recompilação por plataforma. O mesmo arquivo `.py` roda nos dois
  sistemas. O custo é desempenho, e ele não importa aqui — o maior modelo do
  conjunto de teste tem 54 mil vértices e converte em menos de um segundo.
- **Zero dependências**, nem `numpy` nem `Pillow`. Consequências: `pip install`
  nunca é necessário para usar; o executável empacotado fica em torno de 8 MB em
  vez de 60 MB; e não há risco de quebra por atualização de biblioteca de
  terceiros. Em troca, foi preciso escrever o decodificador de DDS e o
  codificador de PNG à mão (`textures.py`). Valeu a pena: são 400 linhas, e o
  resultado foi verificado como **idêntico** ao do Pillow em 406 arquivos.
- **tkinter para a interface**: acompanha o Python no Windows e está disponível
  em qualquer distribuição Linux. Um toolkit mais bonito (Qt, wxWidgets) traria
  uma dependência de dezenas de megabytes para uma janela com duas listas e um
  botão.

### glTF binário (`.glb`) como saída

Um arquivo único, autocontido, importado nativamente pelo Blender, Unity, Godot,
Three.js e pelo visualizador do Windows. As alternativas eram piores: FBX é
proprietário e complexo de escrever corretamente; `.x` (do DirectX) está
obsoleto; e OBJ não suporta esqueleto nem animação, que é justamente o conteúdo
mais valioso do Grand Chase.

---

## Fluxo de dados

Tudo passa por uma representação intermediária. Nenhum leitor conhece nenhum
escritor, e é isso que torna a conversão bidirecional barata.

```
                    ┌──────────────────────────────────────┐
   abta003.p3m ───▶ │ p3m.read_p3m   ──▶ p3m_to_scene      │──┐
   4528.frm ──────▶ │ frm.read_frm   ──▶ frm_to_animation  │  │
                    └──────────────────────────────────────┘  │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │      Scene      │
                                                     │  (left-handed)  │
                                                     └─────────────────┘
                                                        ▲          │
                       to_left_handed()  ───────────────┘          │  to_right_handed()
                                                                   ▼
                                                     ┌─────────────────┐
                                                     │      Scene      │
                                                     │ (right-handed)  │
                                                     └─────────────────┘
                                                        ▲          │
                    ┌───────────────────────────────────┘          │
   personagem.glb ─▶│ gltf_in.read_gltf ──▶ gltf_to_scene          │
                    └──────────────────────────────────────────────┘
                                                                   │
   ┌───────────────────────────────────────────────────────────────┘
   │
   ├──▶ glb.export_glb ─────────────────────────▶ abta003.glb
   │
   └──▶ scene_to_p3m + animation_to_frm ───────▶ personagem.p3m
                                                 personagem_andar.frm
```

O ganho de ter a `Scene` no meio é que cada formato custa **um** módulo, não
N × M conversores. Escrever `.fbx` amanhã significa escrever `formats/fbx.py` e
nada mais.

### Por que existem `P3mFile` e `Scene` separados

`P3mFile` é o arquivo, transcrito fielmente: tem `position_bones` e `angle_bones`
separados, índices de osso absolutos, o campo de textura com o lixo binário que
estiver lá. Serve para inspeção e depuração — é o que o comando `info` mostra.

`Scene` é a *interpretação*: um único tipo de joint, índices resolvidos, posições
em espaço de cena. Separar os dois evita o erro clássico de parsers "espertos"
que já interpretam na leitura e, quando o resultado sai errado, não deixam
distinguir se o problema foi na leitura ou na interpretação.

Na direção inversa a separação paga de novo: `scene_to_p3m` produz um `P3mFile`,
e `write_p3m` o serializa. Dá para inspecionar o resultado antes de gravar, e o
teste de escrita não precisa mexer com bytes.

---

## Módulos

| Módulo | Responsabilidade | Não sabe sobre |
|--------|------------------|----------------|
| `binary.py` | Cursor de bytes little-endian, erros de truncamento com offset | P3M, FRM, glTF |
| `mathutil.py` | Vetores, matrizes 4×4, quaternions, slerp | formatos de arquivo |
| `scene.py` | Estruturas neutras e conversão de sistema de coordenadas | formatos de arquivo |
| `textures.py` | DDS e PNG nos dois sentidos, busca de arquivo de textura | 3D |
| `formats/p3m.py` | Ler e escrever modelos, achatar/reconstruir a hierarquia de ossos | animação, glTF |
| `formats/frm.py` | Ler e escrever animações | geometria, glTF |
| `formats/glb.py` | Escrever glTF 2.0 binário | P3M, FRM |
| `formats/gltf_in.py` | Ler glTF 2.0, reamostrar animações | P3M, FRM |
| `convert.py` | Detectar o sentido, amarrar tudo, coletar avisos, lote | interface |
| `settings.py` | Preferências no `gc3d.ini`, e achar a pasta do executável | conversão |
| `gc3d_app.py` | Escolher entre interface e linha de comando; console no Windows | formatos binários |
| `gc3d_cli.py` / `gc3d_gui.py` | Interface com o usuário | formatos binários |

Ler e escrever glTF ficam em módulos separados porque as duas metades quase não
compartilham código: escrever é montar acessores; ler é resolver acessores,
hierarquia e reamostragem de animação. Juntá-las produziria um arquivo grande sem
ganho nenhum.

As duas interfaces são intercambiáveis porque chamam exatamente as mesmas funções
de `convert.py`. Um comportamento que funciona na linha de comando funciona na
janela, por construção.

---

## Convenções que valem conhecer antes de mexer

### Matrizes são 16 floats em column-major

```python
# elemento da linha r, coluna c:
valor = m[c * 4 + r]

# a translação fica nos índices 12, 13, 14
```

Não foi escolha estética: é a ordem em que o FRM grava as matrizes **e** a ordem
que o glTF exige. Adotar a mesma internamente elimina duas transposições e a
classe de bug mais irritante deste tipo de conversor.

### Vetores são tuplas imutáveis

`(x, y, z)`, não listas nem uma classe `Vec3`. Imutável evita aliasing acidental
— dois vértices apontando para o mesmo objeto de posição e um deles alterando o
outro. Tuplas também são mais rápidas de criar em massa.

### A conversão de coordenadas acontece uma vez, explicitamente

`Scene.to_right_handed()` é chamada só na exportação, nunca no import. Enquanto
a cena está em memória ela é fiel ao arquivo original, o que torna a depuração
possível: um valor lido pode ser comparado diretamente com o hex dump.

O método é idempotente (marca `right_handed = True`) e `export_glb()` **recusa**
uma cena que não passou por ele. Errar esse passo produz um modelo espelhado,
que é um bug difícil de notar em personagem humanoide simétrico — daí a
verificação explícita.

São quatro operações, e todas as quatro são necessárias:

1. negar Z de posições, normais e translações de joint;
2. inverter o winding dos triângulos (espelhar um eixo inverte a orientação das
   faces, que passariam a ser descartadas pelo back-face culling);
3. negar Z da translação de raiz dos keyframes;
4. conjugar as matrizes de animação: `M' = S · M · S`, com `S = diag(1,1,-1)`.

O item 4 é o que se esquece. Negar só a translação deixa as rotações na mão
errada, e o personagem anima ao contrário. Há um teste específico para isso
(`test_flip_z_conjugate_reverses_rotation_sense`).

---

## Pontos onde o formato exigiu decisão de engenharia

### Hierarquia dual de ossos

O Grand Chase alterna dois tipos de nó: `AngleBone` carrega rotação (e é o que
vértices e keyframes referenciam), `PositionBone` carrega apenas o deslocamento
dos filhos.

```
AngleBone ──filho──▶ PositionBone ──filho──▶ AngleBone ──▶ ...
 (rotação)            (translação)            (rotação)
```

Esqueletos convencionais têm um único tipo de nó. `build_joints()` achata:
**um joint por AngleBone**, herdando a translação do PositionBone que o lista
como filho, ligando joint a joint através do PositionBone intermediário. O
PositionBone desaparece do resultado.

### Índice de osso do vértice: duas codificações

O campo ocupa 4 bytes e existem duas convenções em circulação, sem nada no
cabeçalho que diga qual:

- `(idx, idx, 0xFF, 0xFF)` — o índice num byte, repetido, mais dois bytes não
  usados. É o dos arquivos oficiais.
- `u32` little-endian — necessário quando o modelo passa de 255 ossos.

`_resolve_bone_indices()` decide **pelos dados**: em ambas as convenções o
índice é absoluto e tem que cair em `[numPositionBones, numPositionBones +
numAngleBones)`. Testa as duas hipóteses contra *todos* os vértices e adota a
que fecha. Com milhares de vértices, a chance de a hipótese errada fechar é
desprezível. Na dúvida (as duas fecham), prefere `u8`, a dos originais.

Foi assim que `mon_void_dragon3.p3m` (248 + 248 ossos) passou a ser lido: com a
suposição de `u8` ele apontava para ossos inexistentes.

### Vértices sem osso

Três arquivos têm `0xFF` em todos os vértices — não têm skinning. A cena é
devolvida **sem esqueleto**, virando malha estática. A alternativa (uma malha com
skin e pesos todos zero) tem comportamento indefinido na especificação do glTF.

Se apenas *alguns* vértices estiverem sem osso, eles são amarrados ao joint raiz
com peso 1, para acompanharem o modelo em vez de ficarem para trás durante a
animação. Nos dois casos o `convert_model` emite aviso.

### Tolerância a arquivos imperfeitos

Os dados reais têm defeitos, e o conversor não pode desistir por causa deles:

| Situação | Frequência | Tratamento |
|----------|-----------|------------|
| Bytes extras no fim do arquivo | 115 de 131 arquivos | ignorados, contados no aviso |
| Bloco `MeshVertex` truncado | 3 arquivos | tolerado (esses vértices não são usados) |
| Normais não unitárias | comum | normalizadas, com aviso |
| Campo de textura com lixo binário | alguns | descartado por `_clean_texture_name` |
| Peso 0.5 em vez de 1.0 | 3 arquivos | preservado como está |

O que **não** é tolerado: índice de face fora do intervalo de vértices. Esse é o
sintoma de layout desalinhado, e continuar produziria geometria corrompida em
silêncio. Aí o leitor levanta erro com o índice e o limite na mensagem.

---

## A direção inversa: glTF de volta para o jogo

Esta metade é mais difícil que a direta, por um motivo simples: na ida, a entrada
é um arquivo de um jogo específico, com convenções fixas. Na volta, a entrada pode
ter vindo de qualquer ferramenta, cada uma com suas próprias escolhas dentro do que
o glTF permite.

### Reamostragem de animação para 55 FPS

O importador do conversor antigo trazia um aviso no topo do arquivo — *"GLTF
importing does not work properly yet"* — e a causa principal era assumir que os
keyframes já vinham amostrados a 55 FPS. Nenhuma ferramenta de autoria faz isso: o
Blender exporta keyframes nos instantes em que o animador os criou, com espaçamento
irregular.

`gltf_in._read_animation` reamostra: calcula a duração pelo maior tempo declarado,
percorre a grade de `1/55 s` e avalia cada canal no instante exato, respeitando a
interpolação declarada (`LINEAR`, `STEP`, `CUBICSPLINE`). Rotação usa **slerp**, não
interpolação componente a componente — esta última encurta o arco e produz variação
de velocidade visível.

Na prática, uma animação que o Blender exportou com 52 keyframes volta com 118.

### Reconstrução da hierarquia dual

Ao escrever, o caminho inverso do achatamento: **um PositionBone por AngleBone**,
em correspondência 1 para 1.

```
PositionBone[i] = posição do joint i, filhos = [i]
AngleBone[i]    = filhos = joint[i].children
```

Isso difere um pouco dos arquivos originais, onde um mesmo PositionBone às vezes
serve a dois AngleBones raiz — daí `numPositionBones` mudar de 14 para 15 num
ciclo de ida e volta. Mas o que o jogo usa é a lista de **AngleBones**, e ela fica
idêntica, na mesma ordem e com os mesmos índices. O teste de ida e volta verifica
exatamente isso: compara o *joint resolvido* de cada vértice, não o índice
absoluto.

### Índice de osso: escolher a codificação certa

O escritor decide entre `u8` e `u32` pelo total de ossos:

```python
total_bones = num_position_bones + len(angle_bones)
use_u32 = total_bones > 255
```

Isso não é zelo preventivo: sem essa escolha, um modelo com 248 ossos gerava
`bone_index` truncado por `& 0xFF` e vértices grudados no osso errado. Foi um bug
real, pego pelo teste de ida e volta.

### Preservar a numeração dos ossos

O exportador do Blender reordena `skin.joints`. Se aceitássemos a ordem dele, a
numeração dos ossos mudaria a cada ida e volta, e os `.frm` que o jogo já tem
deixariam de casar com o `.p3m` novo.

`_joint_order` resolve: quando todos os ossos têm nome `bone_N`, os joints são
reordenados por N, restaurando a numeração original do Grand Chase. Isso permite
trocar a malha no Blender e continuar usando as animações existentes.

### Onde mora a posição do personagem no mundo

Este foi o ponto mais sutil. O `pos_y` do FRM é a posição **absoluta** do
personagem, e na exportação para glTF ela vira um canal de `translation` no nó
`root`. O Blender, ao importar e reexportar, **assa o primeiro keyframe desse
canal na pose de descanso** — o offset aparece tanto no nó `root` quanto nos dados
de `POSITION`.

Se essa translação entrasse no bind pose do P3M, o jogo somaria o deslocamento
duas vezes e o modelo flutuaria. A regra adotada:

> A posição do personagem no mundo pertence à animação, não ao bind pose.

Concretamente, o nó raiz do esqueleto é excluído da acumulação
(`_world_translation(..., stop_at=root)`) **e** seu offset é subtraído das posições
dos vértices (`_root_world_offset`). Com isso, o bind pose reconstruído bate
exatamente com o original — desvio de bounding box zero — mesmo depois de passar
pelo Blender.

### `JOINTS_0` indexa `skin.joints`, não os nós

Erro fácil de cometer e difícil de notar: os valores em `JOINTS_0` são índices no
array `skin.joints`, não índices de nó. Nos arquivos gerados por este próprio
conversor as duas ordens coincidem, então tratar um pelo outro *funciona* — e
gruda os vértices no osso errado em qualquer arquivo de outra ferramenta.

O importador monta `skin_index_to_joint` explicitamente, e há um teste com
`skin.joints` invertido de propósito para travar esse comportamento.

### Texturas: por que DDS sem compressão

Voltando para o jogo, a textura sai em **DDS sem compressão** — 24 bits quando a
imagem é opaca, 32 bits quando tem transparência, com as máscaras
`R=0xFF0000 G=0xFF00 B=0xFF` (ordem de bytes BGR/BGRA).

A escolha veio de medir os arquivos do próprio jogo, não de preferência:

| Formato | Arquivos | Máscaras |
|---------|----------|----------|
| 24 bits | 251 | `R=0xFF0000 G=0xFF00 B=0xFF` |
| DXT1 | 112 | — |
| 32 bits | 30 | idem + `A=0xFF000000` |
| DXT5 | 13 | — |

**281 das 406 texturas do jogo já são sem compressão**, então gravar assim é
comprovadamente aceito e é sem perda. Um compressor DXT seria com perda e traria
ganho apenas de espaço em disco.

Duas medições guiaram detalhes:

- **326 das 406 texturas não têm mipmaps**, então o escritor também não gera.
- **Nenhuma das 406 tem transparência real** — mesmo as DXT5 e as de 32 bits são
  totalmente opacas. Por isso `has_alpha` é decidido pelos pixels, não pelo formato
  do arquivo: usar o formato faria toda textura opaca virar 32 bits sem necessidade.

Escrever DDS exigiu **decodificar PNG**, porque é assim que a textura chega dentro
do glTF. O decodificador cobre os cinco tipos de cor, profundidades de 1 a 16 bits
e `tRNS`, e foi verificado como idêntico ao do Pillow nas 406 texturas. PNG
entrelaçado é recusado com mensagem clara: nenhum exportador de glTF gera
entrelaçado.

### Achar a textura de um modelo

O campo `textureName` do P3M vem vazio na maioria dos arquivos oficiais, e às vezes
com lixo binário. `resolve_texture` tenta quatro estratégias e **informa qual
funcionou**, para o chamador poder avisar quando o resultado foi um chute:

| Estratégia | Exemplo | Resultado nos 127 modelos |
|------------|---------|---------------------------|
| nome declarado no P3M | — | 0 (o campo é sempre inútil na prática) |
| nome do modelo | `abta003.p3m` → `abta003.dds` | 119 |
| sem o último trecho `_algo` | `abta93827_m` → `abta93827.dds` | 1 |
| qualquer imagem com o mesmo prefixo | `face_04_00` → `face_04_hited_01.dds` | 7 |

As duas primeiras são exatas; as duas últimas são aproximações e viram aviso. A
última existe porque os rostos do jogo têm uma textura por expressão e nem sempre
existe a `_00` — todas servem à mesma malha e ao mesmo UV, então pegar uma é mais
útil que não pegar nada, desde que o usuário saiba.

Com essas regras, os 127 modelos de teste encontram textura, contra 119 antes.

### Perdas inevitáveis, e por que não importam aqui

| Recurso do glTF | O que acontece | Por que é aceitável |
|-----------------|----------------|---------------------|
| Vários ossos por vértice | fica o de maior peso | o P3M v0.5 não tem skinning suave |
| Várias malhas/primitivas | mescladas em uma | o P3M v0.5 guarda uma malha |
| Rotação/escala em nó acima dos ossos | perdida, com aviso | o bind pose do P3M é só translação |
| Mais de uma textura | usa a da primeira malha, com aviso | o P3M v0.5 tem um campo de textura |
| Textura em JPEG | gravada como está, com aviso | não há decodificador de JPEG aqui |
| Translação por osso na animação | não gravada | medimos: **zero** das 93.319 matrizes dos 68 FRM oficiais têm translação (99,92% rotação pura, 0,08% zeradas) |
| Morph targets | ignorados, com aviso | não existem no FRM |

A linha da translação por osso é a mais interessante: em vez de supor, medimos a
coleção inteira. Exportar só canais de rotação para o glTF não perde nada.

---

## Interface gráfica e threads

A janela é uma tela só, e o **sentido da conversão não é escolhido pelo usuário**:
é derivado das extensões do que foi carregado. Dado o conteúdo da lista, só existe
um destino possível, e oferecer a escolha seria criar a chance de errar. Se
houver mistura de glTF com arquivos do jogo, o glTF ganha e o resto é reportado
como ignorado — converter nos dois sentidos ao mesmo tempo não tem significado.

A lista é limpa ao terminar. É deliberado: o estado depois da conversão é
"trabalho concluído", e deixar os arquivos ali convida a clicar em Converter de
novo por engano.

O tema escuro é aplicado à mão, em `apply_dark_theme`, porque o tkinter não tem
um. O tema `clam` é recolorido widget por widget, e os widgets clássicos
(`Listbox`, `Text`) recebem cores direto, porque não passam pelo `ttk.Style`. A
paleta é fixa em vez de seguir o sistema: detectar GTK ou o tema do Windows daria
trabalho e o tkinter não acompanharia de todo jeito. Fixa, a aparência é a mesma
nas duas plataformas.

### Arrastar e soltar como dependência opcional

O tkinter não tem arrastar e soltar de arquivos. O `tkinterdnd2` fornece isso
embutindo a extensão Tcl `tkdnd`, com binários para Linux e Windows, Tcl 8 e 9.

Isso colide com a regra de zero dependências, e a saída foi torná-la **opcional em
tempo de execução e embutida no empacotamento**: o import está num `try`, e sem o
pacote a janela funciona igual, apenas pelos botões, com um aviso no registro. Os
executáveis gerados incluem o pacote (declarado como `datas` no `.spec`, porque são
arquivos de extensão Tcl e não imports), então o usuário final tem o recurso
sempre. Quem roda pelo código escolhe se quer instalar.

O ponto delicado é o **parser dos caminhos soltos**. O tkdnd entrega uma lista
Tcl, com chaves em volta dos caminhos que têm espaço:

```
{/run/media/GRAND CHASE/Lança Uno.p3m} /tmp/b.frm
```

Um `split()` quebraria justamente o caso comum, porque as pastas deste projeto têm
espaço no nome. `_parse_drop_data` interpreta as chaves, e há sete testes cobrindo
caminhos com espaço, mistura de com e sem chaves, caminhos do Windows e separação
por nova linha.

### Seleção de animações

`AnimationIndex` lê cada `.frm` uma única vez e os agrupa por número de ossos.
Converter 83 modelos com 68 animações disponíveis passou de 83 × 68 leituras para
68 — e a mesma instância é usada pela linha de comando e pela janela, então as duas
selecionam do mesmo jeito.

A parte que importa não é o desempenho, e sim o **feedback**. Antes, quando o
casamento por ossos não encontrava nada, o modelo saía sem animação e a causa ficava
invisível: parecia que o conversor não suportava várias animações. Agora
`select_for` devolve um aviso que diz quantos ossos o modelo tem, quantos as
animações têm, e que a verificação pode ser desligada.

A opção de desligar existe porque o critério é uma heurística, ainda que baseada no
formato: pode haver casos legítimos em que o usuário sabe mais que a contagem de
ossos.

### Threads

A conversão roda em uma thread separada, mas **essa thread nunca toca em
widgets**. Ela empilha mensagens numa `queue.Queue`, e a thread da interface
consome a fila a cada 80 ms em `_drain_queue`. Tkinter não é thread-safe;
atualizar widget de outra thread causa travamento intermitente, do tipo que só
aparece na máquina do usuário.

O cancelamento usa `threading.Event`, checado entre arquivos. Não interrompe uma
conversão pela metade, o que evita arquivo truncado no disco.

---

## Empacotamento

`build/` é organizado por plataforma para que as saídas não se misturem:

```
build/common/gc3d.spec        receita do PyInstaller, um binário só
build/icone/                  gerar_icone.py e o gc3d.png / gc3d.ico versionados
build/exemplos.py             ->  release/GrandChase3D-<versão>-exemplos.zip
build/linux/build.sh          ->  dist/linux/gc3d       (para testar localmente)
build/linux/appimage.sh       ->  dist/*.AppImage       (em container Ubuntu 22.04)
build/linux/appimage_interno.sh  monta o AppDir e empacota; roda no container
build/windows/build.bat       ->  dist\windows\gc3d.exe (rodando no Windows)
```

Três decisões que custaram depuração:

**Um executável, e por isso sem `MERGE()`.** Antes eram dois binários, `gc3d` e
`gc3d-gui`, e o `MERGE` do PyInstaller era tentador para não duplicar as
dependências. Ele move as dependências compartilhadas para o primeiro executável,
o que funciona em build de pasta (onedir) e **quebra** em arquivo único: o segundo
binário fica sem a `libpython` e morre no boot com *"Failed to load Python shared
library"*. Com um único ponto de entrada (`gc3d_app.py`) o problema deixou de
existir, e o resultado ainda ficou menor que os dois binários somados.

**O `.exe` sai do CI, não do Wine.** O PyInstaller não faz compilação cruzada —
empacota o interpretador da plataforma onde roda. Houve uma tentativa por Wine, e
ela chegou a produzir o executável de linha de comando, mas **nunca** a interface:
a `tcl86t.dll` não carrega ali, e o PyInstaller precisa importar o tkinter para
analisar o módulo. Num Windows de verdade o problema não existe, e é o que o
`.github/workflows/release.yml` fornece.

**O AppImage é montado em container, e isso é obrigatório.** O PyInstaller liga o
binário contra a glibc do ambiente, e glibc só é compatível para trás: compilado
num sistema atual, o AppImage exige uma glibc que a maioria das máquinas não tem —
o oposto do que um AppImage existe para resolver. O `appimage.sh` roda o build
dentro de `ubuntu:22.04` (glibc 2.35), e a exigência resultante, medida com
`objdump`, é exatamente 2.35. O `build.sh` sozinho serve para testar na própria
máquina, não para distribuir.

---

## Ferramentas de verificação

`tools/` não faz parte do programa; existe para provar que ele funciona.

- **`glb_inspect.py`** — parser de GLB independente do escritor. Verifica
  invariantes que importadores reais cobram: alinhamento de acessor, bufferView
  dentro do buffer, hierarquia de nós sem nó com dois pais, contagem de inverse
  bind matrices igual à de joints, índices dentro do número de vértices. Também
  compara dois GLB atributo por atributo.
- **`validate_all.py`** — varre uma coleção inteira na direção direta e confere
  cada saída.
- **`roundtrip_check.py`** — `P3M/FRM → GLB → P3M/FRM`, comparando com o
  original. Foi esta ferramenta que encontrou o bug do índice `u32`.
- **`blender_check.py`** — importa os arquivos no Blender de verdade e relata
  malha, esqueleto, pesos, UVs, textura e animações. Validação estrutural diz que
  o arquivo está bem formado; isto diz que ele é *utilizável*.
- **`blender_reexport.py`** — reexporta pelo Blender, fechando o ciclo
  `nosso GLB → Blender → GLB do Blender → nosso P3M`. Foi este ciclo que expôs os
  dois bugs mais sutis do importador (o `JOINTS_0` e a translação de ancestrais).

A separação é intencional: o inspetor foi escrito a partir da especificação do
glTF, não do código do exportador. Se os dois compartilhassem lógica, um erro de
entendimento comum passaria despercebido nos dois.

---

## Onde mexer para estender

| Objetivo | Onde |
|----------|------|
| Suportar P3M v0.6/0.7/0.8/1.0 na leitura | `formats/p3m.py`: novo `_read_vXX`, registrar em `SUPPORTED_VERSIONS` e no dispatch de `read_p3m` |
| Suportar FRM v1.2 | `formats/frm.py`: novo `_read_v12`; ver a seção de v1.2 da especificação (Bones = rotação, Bones2 = translação) |
| Skinning suave (vários ossos por vértice) | `scene.Vertex` precisa virar lista de `(joint, weight)`; `glb.py` já escreve `VEC4`, então cabem 4 influências sem mudar o formato de saída |
| Novo formato de saída | novo módulo em `formats/`, consumindo `Scene` |
| Novo formato de entrada | novo módulo em `formats/`, produzindo `Scene` |
| Exportar textura como `.dds` | `textures.py`: escritor de DDS A8R8G8B8 sem compressão; `convert.convert_to_gc` decide a extensão |
| Mudar aparência do material | `formats/glb.py`, função `_add_material` |
| Mudar a paleta da interface | `gc3d_gui.py`, classe `Dark` |

Ao acrescentar suporte a uma versão de formato, o caminho que funcionou aqui foi:
primeiro medir o tamanho previsto do arquivo contra o real em toda a coleção
disponível, depois checar invariantes semânticas (índices de face no intervalo,
índices de osso no intervalo, pesos ≈ 1, normais ≈ unitárias). Layout errado
quase sempre viola uma dessas antes de gerar um arquivo plausível.

E, ao mexer na conversão, rode `roundtrip_check.py`: ele pega classes de erro que
nem os testes unitários nem a validação estrutural do glTF pegam, porque compara o
resultado com o arquivo de origem.
