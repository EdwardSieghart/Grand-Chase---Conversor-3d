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

### Rodando pelo Python (qualquer sistema)

Precisa apenas de **Python 3.10 ou mais novo**. Nenhum `pip install`.

```bash
git clone https://github.com/<seu-usuario>/grand-chase-3d-importer.git
cd grand-chase-3d-importer

python3 gc3d_gui.py          # interface gráfica
python3 gc3d_cli.py --help   # linha de comando
```

No Windows, use `python` em vez de `python3`. Ao instalar o Python, deixe marcado
**"tcl/tk and IDLE"** (vem marcado por padrão) — é o que fornece a interface.

### Pacotes prontos, uma pasta por sistema

```bash
python3 build/empacotar.py --zip
```

Monta duas pastas autocontidas em `release/`:

```
release/
├── GrandChase3D-Linux/
│   ├── Converter.sh            abre a interface
│   ├── Linha de comando.sh     abre um terminal com o comando gc3d
│   ├── LEIA-ME.txt
│   ├── gc3d, gc3d-gui          executáveis, se tiverem sido compilados
│   ├── app/                    código Python (usado se não houver executável)
│   └── exemplos/               arquivos do jogo para testar na hora
└── GrandChase3D-Windows/
    ├── Converter.bat
    ├── Linha de comando.bat
    └── ... o mesmo, com gc3d.exe e gc3d-gui.exe
```

Os lançadores funcionam **com ou sem** executável compilado: se o binário está na
pasta, é ele que roda; se não, o script chama o Python sobre o código em `app/`.
Assim a pasta serve tanto para quem baixou o pacote pronto quanto para quem só
tem o código.

### Compilando os executáveis

```bash
# Linux  ->  dist/linux/
./build/linux/build.sh

# Windows, rodando no Windows  ->  dist\windows\
build\windows\build.bat

# Windows, a partir do Linux, usando Wine  ->  dist/windows/
./build/windows/build_wine.sh
```

Precisa do PyInstaller (`pip install pyinstaller`) apenas para gerar; os binários
resultantes não dependem de nada instalado. Depois de compilar, rode
`build/empacotar.py` de novo para que os pacotes incluam os executáveis.

O PyInstaller não faz cross-compile — ele empacota o interpretador da plataforma
onde roda. O script `build_wine.sh` resolve isso rodando o PyInstaller **dentro
do Wine**, sobre um Python para Windows que ele baixa e instala num prefixo
próprio (`~/.gc3d-wine`, sem tocar no `~/.wine` do usuário).

---

## Uso

### Interface gráfica

```bash
python3 gc3d_gui.py       # ou ./dist/linux/gc3d-gui  /  dist\windows\gc3d-gui.exe
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

### Linha de comando

```bash
# extrair do jogo
python3 gc3d_cli.py convert abta003.p3m --anim-dir animacoes/ -o saida/

# devolver para o jogo (gera .p3m, .frm e .png)
python3 gc3d_cli.py convert personagem.glb -o saida/

# um personagem inteiro (varios .p3m) num unico .glb
python3 gc3d_cli.py convert corpo.p3m rosto.p3m arma.p3m --merge \
    --anim-dir animacoes/ -o saida/

# pastas inteiras, em qualquer sentido
python3 gc3d_cli.py batch "GRAND CHASE/Models" --anim-dir animacoes/ -o saida/
python3 gc3d_cli.py batch "GRAND CHASE/Models" --merge -o saida/   # tudo num arquivo
python3 gc3d_cli.py batch modelos_editados/ -o saida/

# inspecionar sem converter (aceita os três formatos)
python3 gc3d_cli.py info abta003.p3m 4528.frm personagem.glb
```

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
├── gc3d_cli.py            Linha de comando
├── gc3d_gui.py            Interface gráfica (tkinter, tema escuro)
├── src/gc3d/
│   ├── binary.py          Leitura/escrita binária little-endian
│   ├── mathutil.py        Vetores, matrizes 4x4, quaternions, slerp
│   ├── scene.py           Representação intermediária
│   ├── textures.py        DDS → RGBA → PNG, em Python puro
│   ├── convert.py         Pipeline nos dois sentidos
│   └── formats/
│       ├── p3m.py         Modelos: lê e escreve
│       ├── frm.py         Animações: lê e escreve
│       ├── glb.py         Escreve glTF 2.0 binário
│       └── gltf_in.py     Lê glTF 2.0 (.glb e .gltf)
├── requirements-optional.txt  Dependências opcionais (drag and drop, build)
├── tests/                 205 testes, só com a biblioteca padrão
├── tools/
│   ├── glb_inspect.py     Inspeciona, valida e compara GLB
│   ├── validate_all.py    Validação em massa da direção direta
│   ├── roundtrip_check.py Validação de ida e volta
│   ├── blender_check.py   Importa no Blender e confere o resultado
│   ├── blender_reexport.py Reexporta pelo Blender (teste de interoperabilidade)
│   └── publicar_github.sh Publica o repositório
├── samples/               Arquivos reais do jogo para teste
├── build/
│   ├── common/gc3d.spec   Receita compartilhada do PyInstaller
│   ├── linux/build.sh     Build Linux      -> dist/linux/
│   └── windows/           build.bat (no Windows) e build_wine.sh (do Linux)
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

205 testes, sem dependências. Validações mais pesadas, sobre arquivos reais:

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
- **A textura volta como `.png`**, não como `.dds`. Converta com uma ferramenta
  de imagem se o alvo exigir DDS.

---

## Publicando no GitHub

O e-mail da conta **não é suficiente** — o GitHub desativou autenticação por senha
em 2021, e o e-mail só serve para assinar os commits. Você precisa de um **token
pessoal** (`github.com/settings/tokens`, escopo `repo`) ou de uma **chave SSH**
(`github.com/settings/keys`).

```bash
# com token: cria o repositório e envia o código
read -rs GITHUB_TOKEN && export GITHUB_TOKEN
./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer

# anexa os pacotes prontos como Release
python3 build/empacotar.py --zip
./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer --release

# ou com chave SSH, criando antes o repositório vazio em github.com/new
./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer --ssh
```

Os pacotes vão como arquivos de uma **Release**, não como commits, e `release/`
está no `.gitignore`. Isso é deliberado: um executável de 26 MB commitado fica no
histórico do git para sempre, e cada recompilação somaria outros 26 MB ao tamanho
do clone. Numa Release o arquivo pode ser substituído e não pesa em quem clona.

Depois da primeira vez, o fluxo normal:

```bash
git add -A && git commit -m "descrição" && git push
git tag -a v1.5.0 -m "descrição" && git push --tags
```

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
