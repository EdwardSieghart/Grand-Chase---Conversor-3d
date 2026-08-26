# Validação

O que foi verificado, com que método e qual foi o resultado. Todos os números
deste documento são saída real das ferramentas em `tools/`, reproduzíveis com os
comandos indicados.

---

## Por que validar assim

Formato binário reverso-engenheirado tem um risco específico: um layout errado
pode produzir um arquivo **plausível**. Números de ponto flutuante lidos com
offset deslocado geram coordenadas estranhas mas não absurdas, e o resultado abre
sem erro. Ler a especificação e conferir se o código corresponde a ela não
detecta isso — se a especificação estiver errada, o código fica errado junto.

Por isso a validação aqui é em quatro camadas, cada uma capaz de pegar o que a
anterior não pega:

1. **Aritmética de tamanho de arquivo** — o layout previsto tem que somar
   exatamente o tamanho real do arquivo.
2. **Invariantes semânticas** — índices de face dentro do número de vértices,
   índices de osso dentro do número de ossos, pesos ≈ 1, normais ≈ unitárias.
3. **Comparação com implementação independente** — o decodificador de DDS foi
   comparado pixel a pixel com o do Pillow.
4. **Consumo por software real** — os arquivos gerados foram importados no
   Blender.

Um erro de layout que sobrevive às quatro é bem improvável.

---

## Como reproduzir

```bash
# testes unitários e de integração (não precisa de arquivos externos além de samples/)
python3 -m unittest discover -s tests -t .

# validação em massa sobre uma coleção de arquivos do jogo
python3 tools/validate_all.py --cross-check --out-dir out/glb "/caminho/GRAND CHASE"

# validação end-to-end no Blender
ls -d "$PWD"/out/glb/*.glb > out/lista.txt
blender --background --factory-startup \
    --python tools/blender_check.py -- --list "$PWD/out/lista.txt"
```

A flag `--cross-check` exige Pillow e numpy. **Eles não são necessários para
usar o conversor** — servem só como implementação de referência independente
para comparar o decodificador de DDS.

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

A linha decisiva é a terceira. Para todos os 68 arquivos, o layout previsto
consumiu o arquivo **byte a byte, sem sobra nem falta** — incluindo o bloco de
`pos_z`, que fica depois de todos os frames. Se a ordem dos campos do frame
estivesse errada, ou se `pos_z` estivesse dentro do frame em vez de no fim, essa
conta não fecharia em nenhum arquivo.

### 3. Decodificação de DDS

```
decodificados: 406/406
formatos: {'DXT1': 112, 'DXT5': 13, 'RGB24': 251, 'RGB32': 30}
comparados com Pillow: 406
erro maximo por canal: 0
```

**Erro máximo 0** significa que o decodificador escrito à mão produz exatamente
os mesmos bytes que o do Pillow, em todos os 406 arquivos, incluindo a
descompressão de blocos DXT1 e DXT5 e as duas variantes de superfície não
comprimida. Não é "próximo": é idêntico.

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

A validação estrutural (`tools/glb_inspect.py`) confere invariantes que
importadores glTF reais cobram: `byteOffset` de acessor alinhado ao tamanho do
componente, `bufferView` dentro do buffer, `buffer.byteLength` igual ao chunk
BIN, nenhum nó com dois pais na hierarquia, número de inverse bind matrices igual
ao de joints, contagem de índices múltipla de 3, todo índice menor que o número
de vértices, e acessores de tempo de animação com `min`/`max`.

### 5. Importação no Blender

Blender 5.2, importador glTF nativo, 131 arquivos:

```
{
 "total": 131,
 "ok": 131,
 "failed": 0,
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
  skinning (todos os vértices com índice de osso `0xFF`), e nenhum outro.

Teste separado com animações, no modelo `Lança Uno.p3m` mais os 67 `.frm`
compatíveis: Blender importou **67 actions**, 23 bones, 23 grupos de vértice e a
textura de 128×128 embutida.

---

## Descobertas que a validação produziu

Coisas que só apareceram por medir contra os arquivos reais, e não estavam
corretas na documentação de partida.

### O `SkinVertex` da v0.5 tem 40 bytes, não 36

A especificação de partida anunciava "36 bytes" no título da seção, mas a
própria tabela de offsets dela somava 40 (`0x20` + 8 = `0x28`). A medição
resolveu: com 40 bytes por `SkinVertex` e 32 por `MeshVertex`, o tamanho previsto
fecha; com 36, sobra lixo e os índices de face saem do intervalo válido.

O campo de índice de osso ocupa **4 bytes**, não 1. A correção está anotada na
própria `ESPECIFICACAO_FORMATOS.md`.

### Existem duas codificações de índice de osso

- `(idx, idx, 0xFF, 0xFF)` — 130 dos 131 arquivos.
- `u32` little-endian — 1 arquivo (`mon_void_dragon3.p3m`, com 248 + 248 ossos).

O segundo caso é necessário porque um índice absoluto de 248 a 495 não cabe em um
byte. Nada no cabeçalho indica qual está em uso; a detecção é feita testando
qual hipótese coloca **todos** os vértices no intervalo válido
`[numPositionBones, numPositionBones + numAngleBones)`. Antes dessa descoberta,
esse arquivo era o único que falhava.

### Três arquivos não têm skinning nenhum

`AR 15 GC.p3m`, `ARMA.p3m` e `mesh_abta180169.p3m` têm `0xFF` em todos os
vértices. Todos têm 1 PositionBone e 1 AngleBone e foram gerados pelo próprio
conversor antigo a partir de malhas sem rig. São exportados como malha estática,
sem esqueleto — a alternativa (skin com pesos zero) tem comportamento indefinido
na especificação do glTF.

### 115 de 131 arquivos têm bytes extras no fim

Tipicamente 42 bytes por AngleBone. O conteúdo não é usado pelo jogo e o
conversor antigo também os ignorava. São contados e reportados como aviso, não
como erro.

### Três arquivos têm bloco `MeshVertex` truncado

`face_alice.p3m`, `face_21_00.p3m` e `mon_void_dragon3.p3m` terminam antes de
completar o bloco. Como a conversão usa apenas os `SkinVertex`, o truncamento é
inofensivo — mas um parser que exigisse o bloco completo rejeitaria os três.

### Três arquivos têm peso 0.5

`abta003.p3m`, `abta008.p3m` e `abta013.p3m` trazem peso 0.5 em vez de 1.0. O
valor é preservado como está, em vez de ser normalizado para 1.0, para não
divergir do que o jogo faz.

### Normais não unitárias são comuns

Foram medidos comprimentos de normal entre 0.0 e 3.98. O glTF exige normais
unitárias, então elas são normalizadas na conversão, com aviso e contagem. Normal
de comprimento zero vira `(0,0,0)` em vez de causar divisão por zero.

---

## O que não foi possível validar

Registrado por honestidade, porque afeta o grau de confiança.

**Comparação direta com a saída do conversor antigo.** A pasta do `chaseconv` tem
arquivos `.glb` e `.p3m`, mas eles não formam pares. O candidato mais promissor,
`abta180169.glb` + `mesh_abta180169.p3m`, tem datas iguais mas o nome interno da
malha no GLB é `mesh_abta180169`, o que indica que o arquivo de origem se chamava
`abta180169.p3m` — um arquivo diferente, que não está disponível. A comparação
foi feita e apontou 1101 vs 1108 vértices e 23 vs 1 joints, divergência
consistente com fontes diferentes, não com erro de conversão.

A ferramenta de comparação (`tools/glb_inspect.py compare`) ficou pronta e
funcional. Se aparecer um par verdadeiro P3M + GLB do conversor antigo, a
comparação atributo por atributo pode ser feita em um comando.

**FRM v1.0.** Implementada seguindo o conversor antigo, mas não havia nenhum
arquivo v1.0 na coleção. Conta apenas com testes sintéticos e com a verificação
de tamanho em tempo de leitura.

**P3M v0.6 a v1.0 e FRM v1.2.** Não implementadas, portanto não validadas. São
detectadas e recusadas com mensagem explícita.

---

## Cobertura dos testes automatizados

100 testes, executados com `python3 -m unittest discover -s tests -t .`:

| Arquivo | Cobre |
|---------|-------|
| `test_core.py` | leitor/escritor binário, truncamento, vetores, multiplicação de matrizes, conjugação de espelhamento em Z, extração de quaternion (incluindo matriz degenerada e com escala) |
| `test_p3m.py` | detecção de versão, layout com dados sintéticos, sentinelas de filho, bytes extras, bloco truncado, as duas codificações de índice de osso, achatamento da hierarquia dual, malha sem skinning |
| `test_frm.py` | detecção de v1.0/v1.1/v1.2, ordem column-major das matrizes, posição do bloco de `pos_z`, acúmulo de `plus_x`, rejeição de arquivo truncado |
| `test_glb_textures.py` | recusa de cena left-handed, inversão de winding, idempotência, cabeçalho GLB, layout de nós, inverse bind matrices, canais de animação, cena estática sem skin, textura embutida, PNG, DXT1 com dimensão não múltipla de 4 |
| `test_cli.py` | os três subcomandos, saída para arquivo e para pasta, códigos de saída, mensagens de erro |
| `test_samples.py` | integração sobre os arquivos reais em `samples/` |

Dois testes merecem menção porque cobrem erros silenciosos:

- `test_matrices_are_column_major` — se o parser lesse row-major, a translação
  apareceria nos índices 3, 7, 11 em vez de 12, 13, 14. O modelo abriria, e as
  animações estariam sutilmente erradas.
- `test_flip_z_conjugate_reverses_rotation_sense` — verifica que espelhar Z
  inverte o sentido de uma rotação em torno de Y. Esquecer a conjugação das
  matrizes é o erro que faz o personagem animar ao contrário, e nenhuma
  validação estrutural pega.
