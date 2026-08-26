# Grand Chase 3D Importer

Conversor de modelos e animações do **Grand Chase Classic** para **glTF 2.0
binário (.glb)**, com interface gráfica e linha de comando, rodando igual no
**Linux** e no **Windows**.

Lê os formatos proprietários do jogo:

| Formato | O que contém | Situação |
|---------|--------------|----------|
| `.p3m` | Malha, esqueleto, skinning e UVs | v0.5 lida e validada contra 131 arquivos reais |
| `.frm` | Animação por keyframes (55 FPS) | v1.1 validada contra 68 arquivos reais; v1.0 implementada |
| `.dds` | Textura | DXT1, DXT3, DXT5 e superfícies de 16/24/32 bits |

E grava um único `.glb` autocontido — geometria, esqueleto, todas as animações e
a textura embutida — que abre direto no **Blender, Unity, Godot, Three.js** e no
visualizador 3D do Windows, sem plugin nenhum.

---

## Por que este projeto existe

O conversor antigo (`chaseconv`, escrito em Rust) funcionava, mas só tinha
executável para Windows e exigia a toolchain do Rust para recompilar. Este
projeto reimplementa a conversão em **Python 3 sem nenhuma dependência externa**,
o que traz três coisas concretas:

- roda em Linux e Windows a partir do mesmo código, sem recompilar;
- pode ser executado direto pelo Python, sem instalar nada, ou empacotado como
  executável único;
- ganha textura embutida, seleção automática de animações compatíveis e
  conversão em lote, que o conversor antigo não tinha.

---

## Instalação

### Rodando pelo Python (qualquer sistema)

Precisa apenas de **Python 3.10 ou mais novo**. Nenhum `pip install`.

```bash
git clone https://github.com/<seu-usuario>/grand-chase-3d-importer.git
cd grand-chase-3d-importer

python3 gc3d_gui.py          # interface gráfica
python3 gc3d_cli.py --help   # linha de comando
```

No Windows, use `python` em vez de `python3`. Ao instalar o Python, deixe
marcado **"tcl/tk and IDLE"** (vem marcado por padrão) — é o que fornece a
interface gráfica.

### Executáveis prontos

```bash
# Linux
./build/build_linux.sh

# Windows
build\build_windows.bat
```

Gera `dist/gc3d` (linha de comando) e `dist/gc3d-gui` (interface gráfica), com
`.exe` no Windows. Precisa do PyInstaller (`pip install pyinstaller`) apenas
para gerar; os binários resultantes não dependem de nada instalado.

O PyInstaller não faz cross-compile: para gerar o `.exe` do Windows é preciso
rodar o script em uma máquina Windows.

---

## Uso

### Interface gráfica

```bash
python3 gc3d_gui.py
```

1. **Adicionar arquivos** ou **Adicionar pasta** na lista de modelos.
2. Opcionalmente, adicione a pasta de animações `.frm`. Com **"Casar
   automaticamente por número de ossos"** marcado, cada modelo recebe só as
   animações compatíveis com ele.
3. Escolha a pasta de saída e clique em **Converter**.

O registro mostra o que foi feito, com avisos por arquivo. A conversão roda em
segundo plano, então a janela não congela, e pode ser cancelada.

### Linha de comando

```bash
# um modelo
python3 gc3d_cli.py convert abta003.p3m -o saida/

# modelo com todas as animações compatíveis de uma pasta
python3 gc3d_cli.py convert abta003.p3m --anim-dir animacoes/ -o saida/

# animações específicas
python3 gc3d_cli.py convert modelo.p3m -a andar.frm -a correr.frm -o saida/

# pasta inteira, casando animações automaticamente
python3 gc3d_cli.py batch "GRAND CHASE/Models" --anim-dir "GRAND CHASE/ANIM" -o saida/

# inspecionar sem converter
python3 gc3d_cli.py info abta003.p3m 4528.frm
```

Opções que costumam ser úteis:

| Opção | Efeito |
|-------|--------|
| `--texture-dir PASTA` | procura texturas também nesta pasta |
| `--texture ARQUIVO` | usa uma textura específica |
| `--no-texture` | não embute textura |
| `--single-sided` | material de um lado só (padrão é dois lados) |
| `--alpha-mode MASK` | força o modo de transparência |
| `-v` | mostra todos os avisos |

`gc3d_cli.py` devolve código de saída 0 em sucesso e diferente de 0 em falha,
então dá para usar em script.

---

## Como as animações são associadas aos modelos

O jogo não guarda em nenhum lugar qual `.frm` pertence a qual `.p3m`. O
conversor usa o único critério confiável disponível: **um FRM só pode animar um
modelo com o mesmo número de ossos**. É isso que `--anim-dir` e a opção de
casamento automático da interface fazem.

Na prática funciona bem porque os personagens do Grand Chase usam poucos
esqueletos distintos (15 e 23 ossos nos arquivos analisados). Se um modelo
receber animações que não são dele, converta indicando os `.frm` um por um com
`-a`.

---

## Estrutura do projeto

```
.
├── gc3d_cli.py            Linha de comando
├── gc3d_gui.py            Interface gráfica (tkinter)
├── src/gc3d/
│   ├── binary.py          Leitura/escrita binária little-endian
│   ├── mathutil.py        Vetores, matrizes 4x4, quaternions
│   ├── scene.py           Representação intermediária (Scene, Mesh, Joint...)
│   ├── textures.py        DDS → RGBA → PNG, em Python puro
│   ├── convert.py         Pipeline de conversão
│   └── formats/
│       ├── p3m.py         Leitor de modelos
│       ├── frm.py         Leitor de animações
│       └── glb.py         Escritor glTF 2.0 binário
├── tests/                 100 testes, só com a biblioteca padrão
├── tools/
│   ├── glb_inspect.py     Inspeciona, valida e compara arquivos GLB
│   └── blender_check.py   Validação end-to-end importando no Blender
├── samples/               Arquivos reais do jogo para teste
├── build/                 Scripts de empacotamento
└── docs/
    ├── ESPECIFICACAO_FORMATOS.md   Layout byte a byte de P3M, FRM e BON
    ├── ARQUITETURA.md              Como o código está organizado e por quê
    ├── GUIA_USO.md                 Manual detalhado e solução de problemas
    ├── VALIDACAO.md                O que foi verificado e com que evidência
    └── CONTEXTO_PROJETO.md         Contexto para continuar o desenvolvimento
```

---

## Testes

```bash
python3 -m unittest discover -s tests -t .
```

100 testes, sem dependências. Cobrem o leitor binário, a matemática de
conversão de coordenadas, os parsers com dados sintéticos construídos byte a
byte, o escritor GLB, o decodificador DDS, a CLI e uma bateria de integração
sobre os arquivos reais em `samples/`.

Validação extra, opcional, que confere se o resultado é aceito por um consumidor
glTF real:

```bash
python3 tools/glb_inspect.py inspect saida/abta003.glb

ls -d "$PWD"/saida/*.glb > lista.txt
blender --background --factory-startup \
    --python tools/blender_check.py -- --list lista.txt
```

---

## O que foi verificado

| Verificação | Resultado |
|-------------|-----------|
| Leitura de P3M | 131/131 arquivos |
| Leitura de FRM | 68/68 arquivos, consumindo o arquivo byte a byte sem sobra |
| Decodificação de DDS | 406/406 arquivos, **idênticos** ao decodificador do Pillow (erro máximo 0) |
| Round-trip PNG | 406/406 exatos |
| GLB estruturalmente válido | 131/131 |
| Importação no Blender | 132/132, zero vértices sem peso, todos com UV |

Detalhes e metodologia em [docs/VALIDACAO.md](docs/VALIDACAO.md).

---

## Limitações conhecidas

- **Versões de P3M além da 0.5** (0.6, 0.7, 0.8, 1.0) estão documentadas em
  `docs/ESPECIFICACAO_FORMATOS.md` mas não implementadas. O programa detecta e
  recusa com mensagem clara, em vez de gerar geometria corrompida em silêncio.
- **FRM v1.2 e v1.2_Origin** também são detectados e recusados.
- **A conversão é só de entrada.** Não escreve `.p3m` nem `.frm` de volta.
- **Interpolação linear** nas animações. O jogo usa curvas Bézier com tangentes
  desconhecidas; como os frames são densos (55 Hz), a diferença visual é
  desprezível.
- **Um material por modelo.** O P3M v0.5 tem só um campo de textura.

---

## Créditos

- Formato e algoritmo de conversão levantados a partir do
  [chaseconv](https://github.com/gabrielfaria/chaseconv) de Gabriel Faria e dos
  parsers do GC Engine — Character Studio.
- Especificação byte a byte consolidada em `docs/ESPECIFICACAO_FORMATOS.md`.

## Licença

MIT. Ver [LICENSE](LICENSE).

Este projeto lida com formatos de arquivo do Grand Chase, cujos direitos
pertencem a KOG Studios. É uma ferramenta independente de interoperabilidade,
sem nenhum conteúdo do jogo incluído além de pequenas amostras usadas para teste.
