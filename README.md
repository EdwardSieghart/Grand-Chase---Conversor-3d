# Grand Chase 3D Importer

Conversor de modelos e animações do **Grand Chase Classic**, nos **dois
sentidos**, com interface gráfica e linha de comando, rodando igual no **Linux**
e no **Windows**.

```
P3M + FRM  ──▶  GLB          extrair do jogo para editar no Blender
GLB / glTF ──▶  P3M + FRM    devolver o modelo editado para o jogo
```

O sentido é **detectado sozinho** pelas extensões dos arquivos carregados. Não há
botão para escolher: dado o que entrou, só existe um destino possível.

| Formato | Conteúdo | Situação |
|---------|----------|----------|
| `.p3m` | Malha, esqueleto, skinning e UVs | v0.5 — **lê e escreve** |
| `.frm` | Animação por keyframes (55 FPS) | v1.1 — **lê e escreve**; v1.0 lê |
| `.glb` / `.gltf` | glTF 2.0 | **lê e escreve** |
| `.dds` | Textura | **lê** DXT1/3/5 e 16/24/32 bits; **escreve** 24/32 bits sem compressão |

---

## Por que este projeto existe

O conversor antigo (`chaseconv`, em Rust) só tinha executável para Windows,
exigia a toolchain do Rust para recompilar, e o importador de glTF vinha com um
aviso no próprio código: *"GLTF importing does not work properly yet"*.

Este projeto reimplementa tudo em **Python 3 sem nenhuma dependência externa**, o
que traz vantagens concretas:

- roda em Linux e Windows a partir do mesmo código, sem recompilar;
- funciona direto pelo Python, sem instalar nada, ou empacotado como executável;
- a **volta funciona**: 131 de 131 modelos e 70 de 70 animações sobrevivem ao
  ciclo completo sem perda mensurável;
- ganha textura embutida, casamento automático de animações e conversão em lote.

---

## Instalação

### Baixando o executável (recomendado)

Um arquivo por sistema, na [página de
Releases](https://github.com/EdwardSieghart/Grand-Chase---Conversor-3d/releases).
Nada para instalar, nada de Python:

| Sistema | Arquivo | Requisito |
|---------|---------|-----------|
| Windows | `GrandChase3D-<versão>.exe` | Windows 10 ou mais novo |
| Linux | `GrandChase3D-<versão>-x86_64.AppImage` | glibc 2.35+ (Ubuntu 22.04+, Debian 12+, Fedora 36+, RHEL 9+) |

No Linux, marque como executável antes do primeiro uso:

```bash
chmod +x GrandChase3D-*-x86_64.AppImage
```

**Abrir sem argumentos abre a interface gráfica.** O mesmo arquivo também é a
linha de comando — não há dois programas:

```bash
./GrandChase3D-1.6.0-x86_64.AppImage                          # interface
./GrandChase3D-1.6.0-x86_64.AppImage convert modelo.p3m -o .  # linha de comando
```

Arrastar arquivos sobre o ícone do programa abre a interface com eles já
carregados.

Há também um `GrandChase3D-<versão>-exemplos.zip` na mesma página, com alguns
modelos e uma animação do jogo, para o primeiro teste não depender de você já ter
extraído arquivos. Os mesmos arquivos estão em
[`samples/`](samples/) neste repositório.

Se a sua distribuição não tiver mais a `libfuse2`, rode o AppImage com
`--appimage-extract-and-run`.

### Rodando pelo Python (qualquer sistema)

Precisa apenas de **Python 3.10 ou mais novo**. Nenhum `pip install`.

```bash
git clone https://github.com/EdwardSieghart/Grand-Chase---Conversor-3d.git
cd Grand-Chase---Conversor-3d

python3 gc3d_app.py            # interface gráfica
python3 gc3d_app.py --help     # linha de comando
```

No Windows, use `python` em vez de `python3`. Ao instalar o Python, deixe marcado
**"tcl/tk and IDLE"** (vem marcado por padrão) — é o que fornece a interface.

### Compilando você mesmo

Não é preciso: o [GitHub Actions](.github/workflows/release.yml) compila os dois
executáveis a cada tag `v*` e os anexa à Release. Para compilar localmente:

```bash
# Linux, para testar na sua própria máquina  ->  dist/linux/gc3d
./build/linux/build.sh

# Linux, o AppImage distribuível  ->  dist/GrandChase3D-<versão>-x86_64.AppImage
./build/linux/appimage.sh

# Windows, rodando no Windows  ->  dist\windows\gc3d.exe
build\windows\build.bat
```

Precisa do PyInstaller (`pip install pyinstaller`) apenas para gerar; o binário
resultante não depende de nada instalado.

O `appimage.sh` roda o build **dentro de um container Ubuntu 22.04** (podman ou
docker), e isso não é frescura: o PyInstaller liga o binário contra a glibc da
máquina onde roda, e glibc só é compatível para trás. Compilado num sistema
atual, o AppImage exigiria uma glibc que a maioria das máquinas não tem. O
`build.sh` sozinho serve para testar, não para distribuir.

O PyInstaller também não faz compilação cruzada, então o `.exe` precisa de um
Windows de verdade — é o que o CI fornece.

---

## Uso

### Interface gráfica

```bash
python3 gc3d_app.py       # ou ./dist/linux/gc3d  /  dist\windows\gc3d.exe
```

Uma tela só, tema escuro:

1. **Arraste arquivos ou pastas** para a janela, ou use **Adicionar arquivos** /
   **Adicionar pasta**. Tudo vai para a mesma lista — modelos, animações e glTF
   juntos. Pastas soltas são varridas recursivamente.
2. A faixa azul no topo mostra o sentido detectado e o que será feito, por exemplo
   `P3M + FRM -> GLB     3 modelo(s), 67 animacao(oes), casadas por ossos`.
3. Escolha a pasta de saída e clique em **Converter**.

Por padrão, **tudo vira um único `.glb`**: todos os modelos e todas as animações
no mesmo arquivo. É o que faz sentido para um personagem, que costuma vir em
vários `.p3m` (corpo, rosto, cabelo, arma). Desmarque *Juntar tudo em um único
.glb* para gerar um arquivo por modelo.

As animações são **sempre incluídas**, sem exigir que o número de ossos case.

A lista é limpa ao terminar, então o próximo trabalho começa do zero sem risco de
reconverter por engano. A conversão roda em segundo plano (a janela não congela) e
pode ser cancelada entre arquivos.

O arrastar e soltar depende do pacote opcional `tkinterdnd2`. Os executáveis
prontos já o incluem; rodando pelo Python, instale com
`pip install tkinterdnd2` — sem ele a janela funciona igual, só pelos botões.

### Onde ficam as suas configurações

Num arquivo `gc3d.ini` **na mesma pasta do executável**. Isso deixa o programa
portátil: leve o executável e o INI num pendrive e as suas preferências vão
junto, sem deixar rastro na máquina emprestada.

Ficam guardados a pasta de saída, a última pasta que você abriu, as duas caixas de
opção e o tamanho da janela. O arquivo é gravado a cada mudança, não só ao fechar,
e pode ser editado à mão — use `sim` e `nao` nas opções:

```ini
[gc3d]
pasta_saida = /home/eu/gc3d_saida
incluir_textura = sim
juntar_tudo = sim
```

Para ver onde ele está:

```bash
gc3d config
```

Se a pasta do executável não aceitar gravação (um `.exe` dentro de
`Program Files`, ou um AppImage em mídia travada), as preferências vão para
`~/.config/gc3d` ou `%APPDATA%\gc3d`, e a interface avisa no registro. Apagar o
arquivo devolve tudo ao padrão.

### Linha de comando

```bash
# extrair do jogo
python3 gc3d_app.py convert abta003.p3m --anim-dir animacoes/ -o saida/

# devolver para o jogo (gera .p3m, .frm e .dds)
python3 gc3d_app.py convert personagem.glb -o saida/

# um personagem inteiro (varios .p3m) num unico .glb
python3 gc3d_app.py convert corpo.p3m rosto.p3m arma.p3m --merge \
    --anim-dir animacoes/ -o saida/

# pastas inteiras, em qualquer sentido
python3 gc3d_app.py batch "GRAND CHASE/Models" --anim-dir animacoes/ -o saida/
python3 gc3d_app.py batch "GRAND CHASE/Models" --merge -o saida/   # tudo num arquivo
python3 gc3d_app.py batch modelos_editados/ -o saida/

# inspecionar sem converter (aceita os três formatos)
python3 gc3d_app.py info abta003.p3m 4528.frm personagem.glb

# onde estao as configuracoes
python3 gc3d_app.py config
```

Trocando `python3 gc3d_app.py` pelo executável baixado, os comandos são os
mesmos:

```bash
./GrandChase3D-1.6.0-x86_64.AppImage convert abta003.p3m -o saida/
GrandChase3D-1.6.0.exe convert abta003.p3m -o saida/
```

No Windows há um detalhe: o `.exe` é compilado no subsistema gráfico, para o
clique duplo não abrir uma janela preta atrás da interface. A saída aparece
normalmente no `cmd`, mas o prompt volta antes dela, porque o Windows não faz o
`cmd` esperar um programa gráfico terminar. Em script, use
`start /wait GrandChase3D-1.6.0.exe ...`. Redirecionar para arquivo com `>` e
canalizar com `|` funcionam como o esperado.

Opções que costumam ser úteis:

| Opção | Efeito |
|-------|--------|
| `--anim-dir PASTA` | inclui as animações compatíveis da pasta |
| `-a ARQUIVO.frm` | inclui uma animação específica (pode repetir) |
| `--merge` | junta tudo em um único `.glb` |
| `--match-bones` | inclui só as animações com o mesmo número de ossos (o padrão é incluir todas) |
| `--texture-dir PASTA` | procura texturas também nesta pasta |
| `--texture ARQUIVO` | usa uma textura específica |
| `--no-texture` | não embute nem extrai textura |
| `--texture-format` | `dds` (padrão) ou `png` na volta para o jogo |
| `--no-animations` | ao voltar para o jogo, não gera os `.frm` |
| `--single-sided` | material de um lado só (padrão é dois lados) |
| `-v` | mostra todos os avisos |

Código de saída 0 em sucesso, diferente de 0 em falha — usável em script.

---

## Como as animações são associadas aos modelos

O jogo não guarda em nenhum lugar qual `.frm` pertence a qual `.p3m`. O conversor
usa o único critério confiável disponível: **um FRM só pode animar um modelo com
o mesmo número de ossos**. É uma restrição do próprio formato, não um palpite.

Funciona bem porque os personagens do Grand Chase usam poucos esqueletos
distintos (15 e 23 ossos nos arquivos analisados).

**Por padrão as animações são todas incluídas**, sem filtro. O número de ossos é um
critério grosseiro — medindo os 127 modelos do conjunto de teste há **18 esqueletos
distintos, e sete deles com exatamente 15 ossos** —, e uma animação descartada em
silêncio parece um defeito do programa. Use `--match-bones` para restringir.

No modo unificado, cada animação entra no esqueleto cuja contagem de ossos ela usa.
Se nenhum casar, entra no maior, com aviso. Nenhuma animação é descartada.

---

## Voltando um modelo editado para o jogo

Ao converter um `.glb`, você recebe:

```
personagem.p3m                 malha, esqueleto e skinning
personagem_<animacao>.frm      uma por animação presente no glTF
personagem.dds                 a textura, no formato que o jogo lê
```

A textura sai em **DDS sem compressão** (24 bits, ou 32 quando há
transparência), com as mesmas máscaras de canal que o jogo usa nos seus próprios
arquivos. Não é escolha arbitrária: das 406 texturas do jogo analisadas, **281 já
são sem compressão**, então esse formato é comprovadamente aceito e a gravação é
sem perda. O custo é tamanho em disco — uma textura de 128×128 sai com 49 KB em
vez dos 8 KB de um DXT1. Use `--texture-format png` se preferir PNG.

Três coisas que o formato do jogo impõe, e que o conversor avisa quando aplicam:

- **Um osso por vértice.** O P3M v0.5 não tem skinning suave. Se um vértice tiver
  vários ossos influentes, fica o de maior peso.
- **Uma malha só.** Várias malhas ou primitivas são mescladas em uma.
- **Limites do formato:** 255 ossos, 65535 vértices, 65535 triângulos.
  Passar disso gera erro explicando o que reduzir.

As animações são **reamostradas para 55 FPS**, a taxa do motor do jogo. Você pode
animar no Blender no FPS que preferir. Ainda assim vale pôr a cena em 55 FPS
(`Output Properties → Frame Rate → Custom`), porque o exportador do Blender
quantiza os tempos dos keyframes no FPS da cena, e um FPS baixo perde precisão.

---

## Estrutura do projeto

```
.
├── gc3d_app.py            Ponto de entrada único: decide entre interface e CLI
├── gc3d_cli.py            Linha de comando
├── gc3d_gui.py            Interface gráfica (tkinter, tema escuro)
├── src/gc3d/
│   ├── binary.py          Leitura/escrita binária little-endian
│   ├── mathutil.py        Vetores, matrizes 4x4, quaternions, slerp
│   ├── scene.py           Representação intermediária
│   ├── textures.py        DDS → RGBA → PNG, em Python puro
│   ├── settings.py        Preferências no gc3d.ini ao lado do executável
│   ├── convert.py         Pipeline nos dois sentidos
│   └── formats/
│       ├── p3m.py         Modelos: lê e escreve
│       ├── frm.py         Animações: lê e escreve
│       ├── glb.py         Escreve glTF 2.0 binário
│       └── gltf_in.py     Lê glTF 2.0 (.glb e .gltf)
├── requirements-optional.txt  Dependências opcionais (drag and drop, build)
├── tests/                 239 testes, só com a biblioteca padrão
├── tools/
│   ├── glb_inspect.py     Inspeciona, valida e compara GLB
│   ├── validate_all.py    Validação em massa da direção direta
│   ├── roundtrip_check.py Validação de ida e volta
│   ├── blender_check.py   Importa no Blender e confere o resultado
│   └── blender_reexport.py Reexporta pelo Blender (interoperabilidade)
├── samples/               Arquivos reais do jogo para teste
├── build/
│   ├── common/gc3d.spec   Receita do PyInstaller (um binário)
│   ├── icone/             gerar_icone.py e o gc3d.png / gc3d.ico versionados
│   ├── exemplos.py        Monta o zip de exemplos da Release
│   ├── linux/
│   │   ├── build.sh       Binário Linux para teste  -> dist/linux/
│   │   ├── appimage.sh    AppImage distribuível, em container Ubuntu 22.04
│   │   └── appimage_interno.sh  Monta o AppDir e empacota (roda no container)
│   └── windows/build.bat  gc3d.exe, rodando no Windows
├── .github/workflows/
│   ├── testes.yml         Suíte em Linux e Windows a cada push
│   └── release.yml        Compila os dois executáveis e publica na tag
└── docs/
    ├── ESPECIFICACAO_FORMATOS.md   Layout byte a byte de P3M, FRM e BON
    ├── ARQUITETURA.md              Como o código está organizado e por quê
    ├── GUIA_USO.md                 Manual e solução de problemas
    ├── VALIDACAO.md                O que foi verificado e com que evidência
    └── CONTEXTO_PROJETO.md         Contexto para continuar o desenvolvimento
```

---

## Testes

```bash
python3 -m unittest discover -s tests -t .
```

239 testes, sem dependências. Rodam também no [CI](.github/workflows/testes.yml),
em Linux e Windows, a cada push. Validações mais pesadas, sobre arquivos reais:

```bash
# direção direta: lê tudo e confere os GLB gerados
python3 tools/validate_all.py --cross-check "/caminho/GRAND CHASE"

# ida e volta: P3M/FRM -> GLB -> P3M/FRM, comparando com o original
python3 tools/roundtrip_check.py --anim-dir "/caminho/ANIM" "/caminho/GRAND CHASE"

# importação real no Blender
ls -d "$PWD"/out/glb/*.glb > lista.txt
blender --background --factory-startup \
    --python tools/blender_check.py -- --list lista.txt
```

---

## O que foi verificado

| Verificação | Resultado |
|-------------|-----------|
| Leitura de P3M | 131/131 arquivos |
| Leitura de FRM | 68/68, consumindo o arquivo byte a byte sem sobra |
| Decodificação de DDS | 406/406 **idênticos** ao Pillow (erro máximo 0) |
| GLB estruturalmente válido | 131/131 |
| Importação no Blender | 131/131, zero vértices sem peso, todos com UV |
| **Ida e volta** | **131/131 modelos e 70/70 animações idênticos** |
| Interoperabilidade com o Blender | bind pose idêntico (desvio 0) após `GLB → Blender → GLB → P3M` |

Detalhes, metodologia e os bugs que a validação encontrou em
[docs/VALIDACAO.md](docs/VALIDACAO.md).

---

## Limitações conhecidas

- **Versões de P3M além da 0.5** (0.6, 0.7, 0.8, 1.0) estão documentadas em
  `docs/ESPECIFICACAO_FORMATOS.md` mas não implementadas. O programa detecta e
  recusa com mensagem clara, em vez de gerar geometria corrompida em silêncio.
- **FRM v1.2 e v1.2_Origin** também são detectados e recusados.
- **Escrita apenas em P3M v0.5 e FRM v1.1**, que é o que o Grand Chase Classic usa.
- **Interpolação linear** nas animações. O jogo usa curvas Bézier com tangentes
  desconhecidas; a 55 Hz a diferença é desprezível.
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
pertencem a KOG Studios. É uma ferramenta independente de interoperabilidade, sem
conteúdo do jogo incluído além de pequenas amostras usadas para teste.
