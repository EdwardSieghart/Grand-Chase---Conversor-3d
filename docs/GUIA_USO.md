# Guia de uso

Manual detalhado do Grand Chase 3D Importer, incluindo o fluxo de trabalho no
Blender e solução de problemas.

Para instalação rápida, ver o [README](../README.md).

---

## Entendendo os arquivos do jogo

Antes de converter, ajuda saber o que é cada coisa.

| Extensão | Conteúdo | Observação |
|----------|----------|------------|
| `.p3m` | Um modelo: malha, esqueleto, skinning, UVs | O arquivo principal |
| `.frm` | Uma animação: uma pose por frame, a 55 FPS | Uma animação por arquivo |
| `.dds` | Uma textura | Costuma ter o mesmo nome do `.p3m` |

Um personagem completo é, portanto, **um** `.p3m` + **muitos** `.frm` + **uma**
`.dds`. Por exemplo, o modelo `Lança Uno.p3m` tem 67 animações associadas.

O jogo **não guarda** em nenhum lugar qual animação pertence a qual modelo. O
conversor descobre pelo número de ossos: um `.frm` só pode animar um `.p3m` com o
mesmo número de ossos. É um critério do próprio formato, não um palpite.

---

## Interface gráfica

```bash
python3 gc3d_gui.py       # rodando pelo código
./dist/gc3d-gui           # executável no Linux
dist\gc3d-gui.exe         # executável no Windows
```

### Fluxo básico

1. Em **Modelos**, clique em *Adicionar pasta* e escolha a pasta com os `.p3m`.
   A busca é recursiva.
2. Em **Animações**, clique em *Adicionar pasta* e escolha a pasta com os `.frm`.
   Deixe **"Casar automaticamente por número de ossos"** marcado.
3. Em **Pasta de saída**, escolha onde gravar.
4. Clique em **Converter**.

O registro mostra uma linha por modelo, em verde quando dá certo, com os avisos
indentados abaixo. A barra de progresso anda por arquivo. O botão **Cancelar**
interrompe entre arquivos, então não deixa `.glb` incompleto no disco.

### As opções

**Embutir textura** — procura a textura e a grava dentro do `.glb`. A busca usa,
nesta ordem: o nome declarado dentro do `.p3m` (quando utilizável), e o nome do
próprio modelo (`abta003.p3m` → `abta003.dds`). Procura na pasta de cada modelo.
Desmarque se você pretende aplicar texturas à mão.

**Faces dos dois lados** — deixa o material com `doubleSided`. Muitos modelos do
Grand Chase são superfícies abertas (capas, cabelo, saias) que ficam com buracos
se renderizadas de um lado só. Ligado por padrão.

**Casar automaticamente por número de ossos** — quando desmarcado, *todas* as
animações da lista são aplicadas a *todos* os modelos, o que gera resultado
errado se os esqueletos forem diferentes. Só desmarque se você tem certeza de que
tudo pertence ao mesmo personagem.

---

## Linha de comando

Três subcomandos: `info`, `convert` e `batch`.

### `info` — inspecionar sem converter

```bash
python3 gc3d_cli.py info abta003.p3m
```

```
abta003.p3m
  formato            P3M v0.5
  position bones     14
  angle bones        15  (= joints)
  vertices           74
  triangulos         84
  indice de osso     u8
  nome de textura    (vazio)
```

O número em **angle bones** é o que precisa bater com o dos `.frm`. Use para
descobrir quais animações servem para um modelo:

```bash
python3 gc3d_cli.py info animacoes/*.frm | grep -B3 "ossos              15"
```

### `convert` — um modelo

```bash
# só o modelo
python3 gc3d_cli.py convert abta003.p3m -o saida/

# com todas as animações compatíveis de uma pasta
python3 gc3d_cli.py convert abta003.p3m --anim-dir animacoes/ -o saida/

# com animações escolhidas a dedo
python3 gc3d_cli.py convert abta003.p3m -a andar.frm -a pular.frm -o saida/

# com nome de saída específico
python3 gc3d_cli.py convert abta003.p3m -o modelos/elesis.glb

# textura em outra pasta
python3 gc3d_cli.py convert abta003.p3m -o saida/ --texture-dir texturas/
```

### `batch` — muitos modelos

```bash
python3 gc3d_cli.py batch "GRAND CHASE/Models" \
    --anim-dir "GRAND CHASE/ANIMACOES" \
    -o saida/
```

Percorre recursivamente, converte todo `.p3m` encontrado e, para cada um, inclui
as animações compatíveis. Cada modelo gera `<nome>.glb` na pasta de saída.

```bash
# várias pastas de uma vez, sem entrar em subpastas
python3 gc3d_cli.py batch Models/ Faces/ Armas/ --no-recursive -o saida/
```

### Todas as opções

| Opção | Efeito |
|-------|--------|
| `-o`, `--output` | arquivo `.glb` ou pasta de destino |
| `-a`, `--anim` | uma animação a incluir; pode repetir |
| `--anim-dir` | inclui as animações compatíveis da pasta |
| `--texture` | usa esta textura específica |
| `--texture-dir` | pasta extra onde procurar; pode repetir |
| `--no-texture` | não procura nem embute textura |
| `--single-sided` | material de um lado só |
| `--alpha-mode` | `OPAQUE`, `MASK` ou `BLEND` (padrão: automático) |
| `--keep-normals` | não normaliza normais não unitárias |
| `--pretty-json` | grava o JSON do GLB indentado, para depuração |
| `--no-recursive` | (só no `batch`) não entra em subpastas |
| `-v`, `--verbose` | mostra todos os avisos |
| `-q`, `--quiet` | só erros |

Código de saída 0 em sucesso, diferente de 0 em falha — usável em script.

---

## No Blender

### Importar

`File → Import → glTF 2.0 (.glb/.gltf)`

Você recebe:

- um objeto de malha com a textura já aplicada;
- um objeto armature chamado `root`, com os ossos nomeados `bone_0`, `bone_1`...;
- uma **action** por animação, todas em `bpy.data.actions`.

### Trocar de animação

O importador do Blender atribui apenas a primeira action. Para ver as outras:

1. Selecione o armature.
2. Abra o editor **Dope Sheet → Action Editor**.
3. No campo de action, escolha na lista.

Com muitas animações, o **Nonlinear Animation** (NLA) editor é mais prático: cada
action aparece como um strip que você liga e desliga.

### Escala e orientação

Os modelos vêm em escala pequena (o típico fica em torno de 2 unidades de
altura). Se preferir escala de 1 unidade = 1 metro, escale o armature por 1.0 —
já está próximo. O eixo Y é para cima no glTF, e o Blender converte para Z-up na
importação automaticamente.

### As animações têm 55 keyframes por segundo

A taxa é do motor do jogo, não do arquivo. Se você for renderizar, ajuste o FPS
da cena para **55** em `Output Properties → Frame Rate → Custom`, senão a
animação toca em velocidade errada.

---

## Solução de problemas

### "P3M versao '0.7' ainda nao implementado"

Apenas a v0.5 está implementada, que cobre praticamente todo o conteúdo do Grand
Chase Classic. Arquivos de outras versões vêm de outras builds do jogo ou de
ferramentas de terceiros. O layout está documentado em
[ESPECIFICACAO_FORMATOS.md](ESPECIFICACAO_FORMATOS.md) para quem quiser
implementar.

A recusa é deliberada: interpretar v0.7 com o layout da v0.5 geraria geometria
corrompida sem nenhum aviso.

### O modelo aparece sem textura

Em ordem de probabilidade:

1. **O `.dds` não está junto do `.p3m`.** Use `--texture-dir` apontando para a
   pasta das texturas, ou copie os arquivos para a mesma pasta.
2. **O nome não corresponde.** O conversor procura `<nome do modelo>.dds`. Se a
   textura tem outro nome, indique com `--texture arquivo.dds`.
3. **No Blender, o viewport está em modo Solid.** Mude para *Material Preview*
   (a terceira esfera no canto superior direito).

Rode com `-v` para ver o que aconteceu na busca.

### O modelo aparece com partes faltando ou invertidas

Provavelmente back-face culling. Certifique-se de **não** ter usado
`--single-sided`. No Blender, verifique também
`Material Properties → Settings → Backface Culling` desmarcado.

### A animação não aparece

- Confira se o `.frm` é compatível: `info` no modelo e no `.frm`, e compare
  **angle bones** com **ossos**. Números diferentes significam esqueletos
  diferentes.
- No Blender, a action precisa ser selecionada manualmente (ver acima).
- Se `--anim-dir` reportou "0 animações compatíveis", nenhuma animação daquela
  pasta pertence ao modelo.

### A animação toca em velocidade errada

Ajuste o FPS da cena para 55.

### "nenhum vertice tem osso associado: exportado como malha estatica"

Não é erro. Esse `.p3m` não tem skinning — é um prop ou uma malha convertida de
outro formato. Você recebe uma malha estática, sem armature, que é o correto.

### Aviso "N normais nao unitarias normalizadas"

Normal. Vários arquivos oficiais têm normais fora de escala, e o glTF exige
normais unitárias. Use `--keep-normals` se por algum motivo quiser preservar os
valores originais (o resultado pode ficar com sombreamento estranho).

### Aviso "N bytes extras ignorados no fim do P3M"

Normal, aparece em 115 dos 131 arquivos analisados. São dados que o jogo não usa.

### A interface gráfica não abre

Falta o tkinter. No Windows, reinstale o Python marcando **"tcl/tk and IDLE"**.
No Linux, instale o pacote da sua distribuição:

```bash
sudo dnf install python3-tkinter     # Fedora
sudo apt install python3-tk          # Debian, Ubuntu
sudo pacman -S tk                    # Arch
```

A linha de comando funciona sem tkinter.

### Como saber se um `.glb` gerado está bom

```bash
python3 tools/glb_inspect.py inspect saida/abta003.glb
```

Mostra a estrutura e roda as verificações de conformidade com o glTF 2.0.

---

## Uso como biblioteca

O núcleo é importável, se você quiser automatizar algo específico.

```python
import sys
sys.path.insert(0, "src")

from gc3d import convert_model, ConvertOptions

resultado = convert_model(
    "abta003.p3m",
    "saida/abta003.glb",
    ["andar.frm", "pular.frm"],
    ConvertOptions(embed_texture=True, texture_dirs=["texturas/"]),
)
print(resultado.ok, resultado.summary)
for aviso in resultado.warnings:
    print("aviso:", aviso)
```

Inspecionando os dados crus:

```python
from gc3d.formats import p3m, frm

modelo = p3m.load_p3m("abta003.p3m")
print(modelo.num_angle_bones, len(modelo.skin_vertices))
print(modelo.position_bones[0].position, modelo.position_bones[0].children)

animacao = frm.load_frm("4528.frm")
print(animacao.num_frames, animacao.num_bones)
print(animacao.frames[0].bones[0])   # matriz 4x4 column-major, 16 floats
```

Trabalhando com a cena antes de exportar:

```python
from gc3d import build_scene
from gc3d.formats.glb import export_glb, GlbOptions

cena = build_scene("abta003.p3m", ["andar.frm"])
print(cena.summary())

for joint in cena.skeleton:
    print(joint.name, joint.translation, joint.parent)

cena.normalize_normals()
cena.to_right_handed()          # obrigatório antes de exportar
dados = export_glb(cena, GlbOptions(double_sided=True))
```

Convertendo texturas isoladamente:

```python
from gc3d.textures import dds_to_png

with open("abta003.dds", "rb") as origem:
    png = dds_to_png(origem.read())
with open("abta003.png", "wb") as destino:
    destino.write(png)
```
