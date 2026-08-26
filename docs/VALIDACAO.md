# Validação

O que foi verificado, com que método e qual foi o resultado. Todos os números
deste documento são saída real das ferramentas em `tools/`, reproduzíveis com os
comandos indicados.

---

## Por que validar assim

Formato binário reverso-engenheirado tem um risco específico: um layout errado
pode produzir um arquivo **plausível**. Números de ponto flutuante lidos com
offset deslocado geram coordenadas estranhas mas não absurdas, e o resultado abre
sem erro. Ler a especificação e conferir se o código corresponde a ela não detecta
isso — se a especificação estiver errada, o código fica errado junto.

Por isso a validação é em cinco camadas, cada uma capaz de pegar o que a anterior
não pega:

1. **Aritmética de tamanho de arquivo** — o layout previsto tem que somar
   exatamente o tamanho real do arquivo.
2. **Invariantes semânticas** — índices de face dentro do número de vértices,
   índices de osso dentro do número de ossos, pesos ≈ 1, normais ≈ unitárias.
3. **Comparação com implementação independente** — o decodificador de DDS foi
   comparado pixel a pixel com o do Pillow.
4. **Ida e volta** — converter para glTF e voltar, comparando com o arquivo de
   origem. Esta camada é a que pega erro de *interpretação*, não de leitura.
5. **Consumo por software real** — importar no Blender, e reexportar por ele para
   testar interoperabilidade com um glTF que não foi feito por nós.

Um erro que sobreviva às cinco é bem improvável. As camadas 4 e 5 encontraram
três bugs que as três primeiras não pegaram.

---

## Como reproduzir

```bash
# testes unitários e de integração
python3 -m unittest discover -s tests -t .

# direção direta, sobre uma coleção de arquivos do jogo
python3 tools/validate_all.py --cross-check --out-dir out/glb "/caminho/GRAND CHASE"

# ida e volta
python3 tools/roundtrip_check.py --anim-dir "/caminho/ANIM" "/caminho/GRAND CHASE"

# importação no Blender
ls -d "$PWD"/out/glb/*.glb > out/lista.txt
blender --background --factory-startup \
    --python tools/blender_check.py -- --list "$PWD/out/lista.txt"

# interoperabilidade: nosso GLB -> Blender -> GLB do Blender -> nosso P3M
blender --background --factory-startup \
    --python tools/blender_reexport.py -- --list out/lista.txt --out-dir out/blender
python3 gc3d_cli.py batch out/blender -o out/volta
```

A flag `--cross-check` exige Pillow e numpy. **Eles não são necessários para usar
o conversor** — servem só como implementação de referência independente.

---

## Resultados

Coleção usada: 131 arquivos `.p3m`, 68 `.frm` e 406 `.dds`, vindos da pasta de
dados do jogo e da pasta do conversor antigo.

### 1. Leitura de P3M

```
lidos: 131/131
versoes: {'0.5': 131}
codificacao do indice de osso: {'u8': 130, 'u32': 1}
numero de ossos observado: [1, 2, 4, 7, 8, 15, 17, 19, 23, 25, 27, 29, 248]
com bytes extras no fim: 115
com bloco MeshVertex truncado: 3
com peso diferente de 1.0: 3
```

### 2. Leitura de FRM

```
lidos: 68/68
versoes: {'1.1': 68}
numero de ossos observado: [15, 23]
consumiram o arquivo exatamente (0 bytes de sobra): 68/68
total de keyframes: 4081
```

A linha decisiva é a terceira. Para todos os 68 arquivos o layout previsto
consumiu o arquivo **byte a byte, sem sobra nem falta** — incluindo o bloco de
`pos_z`, que fica depois de todos os frames. Se a ordem dos campos do frame
estivesse errada, ou se `pos_z` estivesse dentro do frame, essa conta não fecharia
em nenhum arquivo.

### 3. Decodificação de DDS

```
decodificados: 406/406
formatos: {'DXT1': 112, 'DXT5': 13, 'RGB24': 251, 'RGB32': 30}
comparados com Pillow: 406
erro maximo por canal: 0
```

**Erro máximo 0** significa que o decodificador escrito à mão produz exatamente os
mesmos bytes que o do Pillow, em todos os 406 arquivos, incluindo a descompressão
de blocos DXT1 e DXT5. Não é "próximo": é idêntico.

O codificador de PNG também foi verificado por round-trip: os 406 PNGs gerados
foram reabertos com o Pillow e comparados com os pixels de origem — 406/406
exatos.

### 4. Conversão para GLB e validação estrutural

```
convertidos: 131/131
GLB com problema estrutural: 0
exportados como malha estatica (sem skinning): 3
total gravado: 8.2 MB
```

`tools/glb_inspect.py` confere invariantes que importadores glTF reais cobram:
`byteOffset` de acessor alinhado ao tamanho do componente, `bufferView` dentro do
buffer, `buffer.byteLength` igual ao chunk BIN, nenhum nó com dois pais, número de
inverse bind matrices igual ao de joints, contagem de índices múltipla de 3, todo
índice menor que o número de vértices, e acessores de tempo com `min`/`max`.

### 5. Ida e volta: P3M/FRM → GLB → P3M/FRM

```
modelos: 131
animacoes de referencia: 2 (uma por contagem de ossos: [15, 23])

modelos identicos apos ida e volta: 131/131
animacoes identicas apos ida e volta: 70/70
```

O que é comparado, e a tolerância:

| Item | Tolerância |
|------|-----------|
| Número de ossos, vértices e triângulos | igualdade exata |
| Índices de face | igualdade exata |
| Joint de cada vértice | igualdade exata |
| Posição de vértice, UV, translação de joint | arredondamento f32 (medido: ≤ 1e-7) |
| Rotação por osso e frame | comparada como quaternion, tratando `q` e `-q` como iguais (medido: ≤ 7.5e-7) |

Duas diferenças são **esperadas e por decisão de projeto**, e o comparador as
trata como tal:

- `numPositionBones` muda (por exemplo 14 → 15), porque a escrita usa um
  PositionBone por AngleBone, enquanto os arquivos originais às vezes compartilham
  um PositionBone entre dois AngleBones raiz. O índice de osso absoluto muda junto,
  mas o *joint resolvido* é o mesmo — e é ele que o jogo usa.
- Matrizes de osso zeradas voltam como identidade. São 0,08% dos casos.

### 6. Importação no Blender

Blender 5.2, importador glTF nativo, 131 arquivos:

```
{
 "total": 131, "ok": 131, "failed": 0,
 "unweighted_verts": 0,
 "files_with_unweighted": [],
 "without_uv": [],
 "without_armature": ["AR 15 GC.glb", "ARMA.glb", "mesh_abta180169.glb"]
}
```

- **131/131 importados** sem erro.
- **`unweighted_verts: 0`** — nenhum vértice de malha com armature ficou sem peso
  de skinning. Vértice sem peso não acompanha o osso e ficaria parado durante a
  animação; é um defeito que a validação estrutural do glTF não detecta.
- **`without_uv: []`** — todas as malhas têm coordenadas de textura.
- **`without_armature`** contém exatamente os 3 arquivos que de fato não têm
  skinning, e nenhum outro.

Teste com animações, no modelo `Lança Uno.p3m` mais os 67 `.frm` compatíveis:
Blender importou **67 actions**, 23 bones, 23 grupos de vértice e a textura de
128×128 embutida.

### 7. Interoperabilidade: glTF que não foi feito por nós

Ciclo completo `nosso GLB → Blender → GLB do Blender → nosso P3M`, comparando o
bind pose reconstruído com o P3M original:

| Modelo | Vértices | Desvio de bounding box | Vizinho mais próximo | Joints por vértice |
|--------|----------|------------------------|----------------------|--------------------|
| `abta000` (sem animação) | 647 → 647 | 0 | 1,6e-08 | iguais |
| `Lança Uno` (3 animações) | 542 → 542 | 0 | 4,9e-08 | iguais |
| `abta003` (1 animação) | 74 → 84 | 0 | 6,3e-08 | — |

`pos_y` do FRM também sobrevive: o original varia de 0,45633 a 0,46024, e o
arquivo reconstruído a partir do GLB do Blender traz 0,45634 a 0,46024.

Este é o teste que importa de verdade para a direção inversa, porque o arquivo de
entrada foi produzido por outra ferramenta, com suas próprias convenções de nome
de nó, ordem de joints, instantes de keyframe e layout de acessor.

Duas observações sobre o comportamento do Blender, que não são defeitos do
conversor:

- **`abta003` passa de 74 para 84 vértices.** O Blender divide vértices em
  costuras de UV e de normal. A geometria é a mesma — a distância ao vizinho mais
  próximo de 6,3e-08 mostra isso — só a contagem muda.
- **Contagem de frames cai um pouco** (120 → 118). O Blender usa 24 FPS por
  padrão e quantiza os instantes dos keyframes nesse FPS ao exportar. Pôr a cena
  em 55 FPS resolve.

---

## Bugs que a validação encontrou

Três bugs reais, todos na direção inversa, todos pegos pelas camadas 4 e 5. Nenhum
deles seria detectado por leitura de especificação, testes unitários sintéticos ou
validação estrutural do glTF.

### 1. Índice de osso truncado acima de 255 ossos

**Sintoma:** `roundtrip_check.py` falhou em `mon_void_dragon3.p3m`, com
*"vértice 192 aponta para o osso 44, fora do intervalo esperado [248, 496)"*.

**Causa:** o escritor gravava sempre `bone_index & 0xFF`. Com 248 PositionBones +
248 AngleBones, o índice absoluto vai até 495 e não cabe em um byte.

**Correção:** `_pack_bone_index` escolhe a codificação `u32` quando o total passa
de 255 — a mesma que o arquivo original usava. Antes disso, os vértices ficavam
grudados no osso errado.

### 2. `JOINTS_0` interpretado como índice de nó

**Sintoma:** ao converter o GLB reexportado pelo Blender, os joints por vértice
não batiam com o original.

**Causa:** os valores em `JOINTS_0` são índices no array `skin.joints`, não índices
de nó. Nos arquivos gerados por este conversor as duas ordens coincidem, então o
erro **passava despercebido** — e grudava os vértices no osso errado em qualquer
arquivo de outra ferramenta, porque o Blender reordena os joints.

**Correção:** mapa `skin_index_to_joint` explícito. Há um teste com `skin.joints`
invertido de propósito (`test_joints_0_indexes_skin_joints_not_nodes`) para travar
o comportamento.

### 3. Translação de ancestrais que não são ossos era ignorada

**Sintoma:** modelos que passaram pelo Blender voltavam deslocados exatamente
0,46 unidade em Y.

**Causa:** `_world_translation` subia apenas pela cadeia de ossos. O Blender põe
transformação no nó do objeto Armature, que fica acima dela.

**Correção:** acumular **todos** os ancestrais. Rotação e escala em ancestrais não
são representáveis no bind pose do P3M e agora geram aviso explícito.

### E uma decisão de projeto que a validação forçou

O nó raiz do esqueleto carrega a posição do personagem no mundo, que pertence ao
`pos_y` do FRM e não ao bind pose do P3M. O Blender assa o primeiro keyframe desse
canal na pose de descanso, o que duplicava a informação: o modelo ficaria 0,46
acima do chão no jogo, porque o deslocamento seria contado duas vezes.

A regra adotada — *a posição no mundo pertence à animação* — é implementada
excluindo o nó raiz da acumulação (`stop_at`) e subtraindo seu offset das posições
dos vértices (`_root_world_offset`). Com isso o bind pose reconstruído bate
exatamente com o original, com desvio de bounding box zero.

---

## Descobertas sobre os dados

### O `SkinVertex` da v0.5 tem 40 bytes, não 36

A especificação de partida anunciava "36 bytes" no título da seção, mas a própria
tabela de offsets dela somava 40 (`0x20` + 8 = `0x28`). A medição resolveu: com 40
bytes por `SkinVertex` e 32 por `MeshVertex`, o tamanho previsto fecha; com 36,
sobra lixo e os índices de face saem do intervalo válido. O campo de índice de
osso ocupa **4 bytes**, não 1. A correção está anotada na própria
`ESPECIFICACAO_FORMATOS.md`.

### Existem duas codificações de índice de osso

`(idx, idx, 0xFF, 0xFF)` em 130 dos 131 arquivos, e `u32` little-endian em 1
(`mon_void_dragon3.p3m`, com 248 + 248 ossos). Nada no cabeçalho indica qual está
em uso; a detecção testa qual hipótese coloca **todos** os vértices no intervalo
válido `[numPositionBones, numPositionBones + numAngleBones)`.

### As matrizes de osso do FRM são rotação pura

Medição sobre as **93.319** matrizes dos 68 arquivos:

```
rotacao pura: 93243 (99.92%)
zerada:          76 (0.08%)
com translacao:   0 (0.00%)
```

**Zero** matrizes com translação. Isso justifica exportar apenas canais de rotação
para o glTF: não se perde nada. Era uma suposição do conversor antigo (que tinha um
`TODO` sobre translações de joint); aqui virou fato medido.

### Três arquivos não têm skinning nenhum

`AR 15 GC.p3m`, `ARMA.p3m` e `mesh_abta180169.p3m` têm `0xFF` em todos os
vértices. Todos têm 1 PositionBone e 1 AngleBone. São exportados como malha
estática, sem esqueleto — a alternativa (skin com pesos zero) tem comportamento
indefinido na especificação do glTF. Na volta, o sentinela `0xFF` é preservado, o
que faz esses três arquivos sobreviverem à ida e volta byte a byte.

### Outras irregularidades toleradas

- **115 de 131 arquivos** têm bytes extras no fim (tipicamente 42 por AngleBone).
- **3 arquivos** têm o bloco `MeshVertex` truncado (`face_alice.p3m`,
  `face_21_00.p3m`, `mon_void_dragon3.p3m`). Como a conversão usa apenas os
  `SkinVertex`, é inofensivo.
- **3 arquivos** têm peso 0.5 em vez de 1.0 (`abta003`, `abta008`, `abta013`). O
  valor é preservado.
- **Normais não unitárias são comuns**, com comprimentos medidos de 0,0 a 3,98.
  São normalizadas, com aviso e contagem.

---

## O que não foi possível validar

Registrado por honestidade, porque afeta o grau de confiança.

**Comparação direta com a saída do conversor antigo.** A pasta do `chaseconv` tem
arquivos `.glb` e `.p3m`, mas eles não formam pares. O candidato mais promissor,
`abta180169.glb` + `mesh_abta180169.p3m`, tem datas iguais mas o nome interno da
malha no GLB indica que a origem era um `abta180169.p3m` diferente, que não está
disponível. A ferramenta de comparação
(`tools/glb_inspect.py compare`) está pronta: se aparecer um par verdadeiro, a
comparação atributo por atributo sai em um comando.

**Teste no jogo.** Os arquivos gerados não foram carregados no Grand Chase. A
evidência disponível é de consistência: o formato é reproduzido byte a byte nos
campos que importam, e o ciclo de ida e volta é fechado. Não é o mesmo que ver o
modelo animando no jogo.

**FRM v1.0.** Implementada seguindo o conversor antigo, mas não havia nenhum
arquivo v1.0 na coleção. Conta apenas com testes sintéticos e com a verificação de
tamanho em tempo de leitura.

**P3M v0.6 a v1.0 e FRM v1.2.** Não implementadas, portanto não validadas. São
detectadas e recusadas com mensagem explícita.

---

## Cobertura dos testes automatizados

130 testes, executados com `python3 -m unittest discover -s tests -t .`:

| Arquivo | Cobre |
|---------|-------|
| `test_core.py` | leitor/escritor binário, truncamento, vetores, multiplicação de matrizes, conjugação de espelhamento em Z, extração de quaternion (incluindo matriz degenerada e com escala) |
| `test_p3m.py` | detecção de versão, layout com dados sintéticos, sentinelas de filho, bytes extras, bloco truncado, as duas codificações de índice de osso, achatamento da hierarquia dual, malha sem skinning |
| `test_frm.py` | detecção de v1.0/v1.1/v1.2, ordem column-major das matrizes, posição do bloco de `pos_z`, acúmulo de `plus_x`, rejeição de arquivo truncado |
| `test_glb_textures.py` | recusa de cena left-handed, inversão de winding, idempotência, cabeçalho GLB, layout de nós, inverse bind matrices, canais de animação, cena estática sem skin, textura embutida, PNG, DXT1 com dimensão não múltipla de 4 |
| `test_reverse.py` | container GLB e `.gltf` com `data:` URI, acessor normalizado, hierarquia de joints, `JOINTS_0` indexando `skin.joints`, reordenação canônica por `bone_N`, exclusão da posição no mundo, reamostragem para 55 FPS, escritores de P3M e FRM, limites do formato, ida e volta sintética e sobre arquivos reais |
| `test_cli.py` | os três subcomandos, saída para arquivo e para pasta, códigos de saída, mensagens de erro |
| `test_samples.py` | integração sobre os arquivos reais em `samples/` |

Quatro testes merecem menção porque cobrem erros silenciosos — do tipo que produz
arquivo válido e resultado errado:

- `test_matrices_are_column_major` — se o parser lesse row-major, a translação
  apareceria nos índices 3, 7, 11 em vez de 12, 13, 14. O modelo abriria, e as
  animações estariam sutilmente erradas.
- `test_flip_z_conjugate_reverses_rotation_sense` — verifica que espelhar Z
  inverte o sentido de uma rotação em torno de Y. Esquecer a conjugação das
  matrizes é o erro que faz o personagem animar ao contrário.
- `test_joints_0_indexes_skin_joints_not_nodes` — trava o bug nº 2 acima, com
  `skin.joints` invertido de propósito.
- `test_root_node_translation_is_not_baked_into_bind_pose` — trava a decisão sobre
  onde mora a posição no mundo.
