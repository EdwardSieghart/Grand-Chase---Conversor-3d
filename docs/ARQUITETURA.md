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
escritor.

```
   abta003.p3m ──▶ p3m.read_p3m() ──▶ P3mFile ──▶ p3m_to_scene() ──┐
                     (bytes crus)     (bytes         (semântica)   │
                                    interpretados)                 │
                                                                   ▼
   4528.frm ────▶ frm.read_frm() ──▶ FrmFile ──▶ frm_to_animation() ──▶  Scene
                                                                   ▲     (left-handed)
   4529.frm ────▶ ...                                              │        │
                                                                   ┘        │
                                                                            ▼
                                                          Scene.to_right_handed()
                                                                            │
                                                                            ▼
                                                              glb.export_glb()
                                                                            │
                                                                            ▼
                                                                   abta003.glb
```

O ganho de ter a `Scene` no meio é que adicionar um formato custa **um** módulo,
não N × M conversores. Escrever `.fbx` amanhã significa escrever
`formats/fbx.py` e nada mais.

### Por que existem `P3mFile` e `Scene` separados

`P3mFile` é o arquivo, transcrito fielmente: tem `position_bones` e
`angle_bones` separados, índices de osso absolutos, o campo de textura com o
lixo binário que estiver lá. Serve para inspeção e depuração — é o que o comando
`info` mostra.

`Scene` é a *interpretação*: um único tipo de joint, índices resolvidos,
posições em espaço de cena. Separar os dois evita o erro clássico de parsers
"espertos" que já interpretam na leitura e, quando o resultado sai errado, não
deixam distinguir se o problema foi na leitura ou na interpretação.

---

## Módulos

| Módulo | Responsabilidade | Não sabe sobre |
|--------|------------------|----------------|
| `binary.py` | Cursor de bytes little-endian, erros de truncamento com offset | P3M, FRM, glTF |
| `mathutil.py` | Vetores, matrizes 4×4, quaternions | formatos de arquivo |
| `scene.py` | Estruturas neutras e conversão de sistema de coordenadas | formatos de arquivo |
| `textures.py` | DDS → RGBA → PNG, busca de arquivo de textura | 3D |
| `formats/p3m.py` | Ler modelos, achatar a hierarquia de ossos | animação, glTF |
| `formats/frm.py` | Ler animações | geometria, glTF |
| `formats/glb.py` | Escrever glTF 2.0 binário | P3M, FRM |
| `convert.py` | Amarrar tudo, coletar avisos, lote | interface |
| `gc3d_cli.py` / `gc3d_gui.py` | Interface com o usuário | formatos binários |

As duas interfaces são intercambiáveis porque chamam exatamente as mesmas
funções de `convert.py`. Um comportamento que funciona na linha de comando
funciona na janela, por construção.

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
| Bytes extras no fim do arquivo | 84 de 131 arquivos | ignorados, contados no aviso |
| Bloco `MeshVertex` truncado | 2 arquivos | tolerado (esses vértices não são usados) |
| Normais não unitárias | comum | normalizadas, com aviso |
| Campo de textura com lixo binário | alguns | descartado por `_clean_texture_name` |
| Peso 0.5 em vez de 1.0 | 3 arquivos | preservado como está |

O que **não** é tolerado: índice de face fora do intervalo de vértices. Esse é o
sintoma de layout desalinhado, e continuar produziria geometria corrompida em
silêncio. Aí o leitor levanta erro com o índice e o limite na mensagem.

---

## Interface gráfica e threads

A conversão roda em uma thread separada, mas **essa thread nunca toca em
widgets**. Ela empilha mensagens numa `queue.Queue`, e a thread da interface
consome a fila a cada 100 ms em `_drain_queue`. Tkinter não é thread-safe;
atualizar widget de outra thread causa travamento intermitente, do tipo que só
aparece na máquina do usuário.

O cancelamento usa `threading.Event`, checado entre arquivos. Não interrompe uma
conversão pela metade, o que evita arquivo `.glb` truncado no disco.

---

## Ferramentas de verificação

`tools/` não faz parte do programa; existe para provar que ele funciona.

- **`glb_inspect.py`** — parser de GLB independente do escritor. Verifica
  invariantes que importadores reais cobram: alinhamento de acessor,
  bufferView dentro do buffer, hierarquia de nós sem nó com dois pais, contagem
  de inverse bind matrices igual à de joints, índices dentro do número de
  vértices. Também compara dois GLB atributo por atributo.
- **`blender_check.py`** — importa os arquivos no Blender de verdade e relata
  malha, esqueleto, pesos, UVs, textura e animações. Validação estrutural diz
  que o arquivo está bem formado; isto diz que ele é *utilizável*.

A separação é intencional: o inspetor foi escrito a partir da especificação do
glTF, não do código do exportador. Se os dois compartilhassem lógica, um erro de
entendimento comum passaria despercebido nos dois.

---

## Onde mexer para estender

| Objetivo | Onde |
|----------|------|
| Suportar P3M v0.6/0.7/0.8/1.0 | `formats/p3m.py`: novo `_read_vXX`, registrar em `SUPPORTED_VERSIONS` e no dispatch de `read_p3m` |
| Suportar FRM v1.2 | `formats/frm.py`: novo `_read_v12`; ver a seção de v1.2 da especificação (Bones = rotação, Bones2 = translação) |
| Novo formato de saída | novo módulo em `formats/`, consumindo `Scene`; nada mais muda |
| Escrever P3M de volta | `formats/p3m.py`: função de escrita usando `BinaryWriter`, mais um importador de glTF |
| Mudar aparência do material | `formats/glb.py`, função `_add_material` |

Ao acrescentar suporte a uma versão, o caminho que funcionou aqui foi: primeiro
medir o tamanho previsto do arquivo contra o real em toda a coleção disponível,
depois checar invariantes semânticas (índices de face no intervalo, índices de
osso no intervalo, pesos ≈ 1, normais ≈ unitárias). Layout errado quase sempre
viola uma dessas antes de gerar um arquivo plausível.
