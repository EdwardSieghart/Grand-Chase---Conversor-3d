# Guia de uso

Manual detalhado do Grand Chase 3D Importer, incluindo o fluxo de trabalho no
Blender e solução de problemas.

Para instalação rápida, ver o [README](../README.md).

---

## Entendendo os arquivos do jogo

| Extensão | Conteúdo | Observação |
|----------|----------|------------|
| `.p3m` | Um modelo: malha, esqueleto, skinning, UVs | O arquivo principal |
| `.frm` | Uma animação: uma pose por frame, a 55 FPS | Uma animação por arquivo |
| `.dds` | Uma textura | Costuma ter o mesmo nome do `.p3m` |

Um personagem completo é **um** `.p3m` + **muitos** `.frm` + **uma** `.dds`. O
modelo `Lança Uno.p3m`, por exemplo, tem 67 animações associadas.

O jogo **não guarda** em nenhum lugar qual animação pertence a qual modelo. O
conversor descobre pelo número de ossos: um `.frm` só pode animar um `.p3m` com o
mesmo número de ossos. É uma restrição do próprio formato.

---

## Os dois sentidos

O sentido é deduzido das extensões, não escolhido:

```
.p3m / .frm   ──▶  .glb                  para editar no Blender
.glb / .gltf  ──▶  .p3m + .frm + .png    para voltar ao jogo
```

Misturar os dois numa mesma conversão não tem significado. Se houver mistura, o
glTF ganha e o resto é reportado como ignorado.

---

## Interface gráfica

```bash
python3 gc3d_app.py                             # pelo código
./GrandChase3D-1.6.0-x86_64.AppImage            # executável Linux
GrandChase3D-1.6.0.exe                          # executável Windows
```

É o mesmo arquivo da linha de comando: sem argumentos, ele abre a janela.
Arrastar arquivos sobre o ícone do programa também abre a janela, já com eles
carregados.

### Fluxo básico

1. **Arraste os arquivos ou pastas** para dentro da janela — ou use **Adicionar
   arquivos** / **Adicionar pasta**. Tudo vai para a mesma lista: modelos,
   animações e glTF juntos. Pastas são varridas recursivamente, e arquivos de
   extensão não suportada são descartados com aviso no registro.
2. Confira a faixa azul no topo: ela diz o sentido detectado e o que será feito,
   por exemplo `P3M + FRM -> GLB     3 modelo(s), 67 animacao(oes), casadas por ossos`.
3. Em **Animações**, escolha o modo (ver abaixo).
4. Escolha a pasta de saída.
5. **Converter**.

A lista é limpa ao terminar. O registro mostra uma linha por arquivo, em verde
quando dá certo, com os avisos indentados abaixo. **Cancelar** interrompe entre
arquivos, então não deixa arquivo incompleto no disco.

### Arrastar e soltar

Funciona com arquivos e com pastas, e aceita vários de uma vez. A lista fica
realçada enquanto você passa por cima dela.

O recurso depende do pacote opcional `tkinterdnd2`. Os executáveis prontos já o
incluem. Rodando pelo Python:

```bash
python3 -m pip install tkinterdnd2
```

Sem ele, a janela funciona exatamente igual, apenas pelos botões — e avisa isso no
registro ao abrir.

### Tudo em um único .glb

É o comportamento padrão, controlado pela opção **Juntar tudo em um único .glb**.
Todos os modelos e todas as animações carregados vão para o mesmo arquivo.

Faz sentido porque um personagem do Grand Chase costuma vir repartido em vários
`.p3m` — corpo, rosto, cabelo, arma — que pertencem ao mesmo boneco. Um arquivo com
tudo dentro é mais útil que um por peça.

Cada modelo mantém a **sua própria textura**: o `.glb` recebe um material por
malha. E se os modelos usarem esqueletos diferentes, cada um vira uma **armature
separada dentro do mesmo arquivo** — o glTF permite isso, e é o único jeito
correto, porque forçar um esqueleto só misturaria bind poses e deformaria a malha.

Desmarque a opção para gerar um `.glb` por modelo.

Testado com 83 modelos, 17 esqueletos, 30.157 vértices, 81 texturas e 68 animações
num único arquivo, importado no Blender sem nenhum vértice sem peso.

### Animações

**Todas as animações carregadas são sempre incluídas.** O número de ossos não é
usado como filtro por padrão, porque é um critério grosseiro: nos 127 modelos do
conjunto de teste há 18 esqueletos distintos, sete deles com exatamente 15 ossos.

No modo unificado, cada animação vai para o esqueleto cuja contagem de ossos ela
usa. Se nenhum casar, vai para o maior, com aviso no registro. Nenhuma animação é
descartada em silêncio.

Na linha de comando, `--match-bones` restringe às animações com o mesmo número de
ossos do modelo.

### A opção de textura

**Incluir textura** faz duas coisas diferentes conforme o sentido:

- indo para `.glb`: procura a textura e a embute dentro do arquivo;
- voltando para `.p3m`: grava a textura ao lado do modelo, em `.dds`.

A busca da textura tenta, nesta ordem:

1. o nome declarado dentro do `.p3m`, quando utilizável;
2. o nome do próprio modelo (`abta003.p3m` → `abta003.dds`) — resolve 119 dos 127
   modelos de teste;
3. o nome sem o último trecho `_algo` (`abta93827_m` → `abta93827.dds`);
4. qualquer imagem com o mesmo prefixo (`face_04_00` → `face_04_hited_01.dds`).

Os dois primeiros são exatos. Os dois últimos são aproximações, e o registro avisa
quando foram usados, dizendo quantas alternativas existem. Com essas regras, os
127 modelos de teste encontram textura.

A busca é feita na pasta de cada modelo. Use `--texture-dir` na linha de comando
para procurar em outras.

### Suas preferências ficam guardadas

A pasta de saída, a última pasta que você abriu, as duas caixas de opção e o
tamanho da janela são lembrados entre execuções, num arquivo `gc3d.ini` **na mesma
pasta do executável**.

Isso deixa o programa portátil: leve o executável e o INI num pendrive e as suas
configurações vão junto, sem deixar rastro na máquina emprestada.

Para ver onde o arquivo está:

```bash
python3 gc3d_app.py config
```

O registro da interface também diz isso ao abrir. O arquivo pode ser editado à
mão, com `sim` e `nao` nas opções de ligar e desligar:

```ini
[gc3d]
pasta_saida = /home/eu/gc3d_saida
ultima_pasta_aberta = /mnt/jogos/GRAND CHASE/Models
incluir_textura = sim
juntar_tudo = sim
janela = 1000x740
```

Apagar o arquivo devolve tudo ao padrão. Se ele ficar ilegível ou com um valor
inválido, o programa abre normalmente usando os padrões, em vez de recusar a
iniciar.

Quando a pasta do executável não aceita gravação — um `.exe` dentro de
`Program Files`, um AppImage num cartão travado — as preferências vão para
`~/.config/gc3d` ou `%APPDATA%\gc3d`, e a interface avisa no registro para você
não procurar um arquivo que nunca apareceu.

---

## Linha de comando

### `info` — inspecionar sem converter

Aceita os três formatos.

```bash
python3 gc3d_app.py info abta003.p3m
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

O número em **angle bones** é o que precisa bater com o dos `.frm`. Para descobrir
quais animações servem para um modelo:

```bash
python3 gc3d_app.py info animacoes/*.frm | grep -B3 "ossos              15"
```

Num glTF, `info` mostra o gerador, contagens e a lista de animações — útil para
conferir o que o Blender realmente exportou antes de converter.

### `convert` — um arquivo

```bash
# extrair do jogo
python3 gc3d_app.py convert abta003.p3m -o saida/
python3 gc3d_app.py convert abta003.p3m --anim-dir animacoes/ -o saida/
python3 gc3d_app.py convert corpo.p3m rosto.p3m arma.p3m --merge -o saida/
python3 gc3d_app.py convert abta003.p3m -a andar.frm -a pular.frm -o saida/
python3 gc3d_app.py convert abta003.p3m -o modelos/elesis.glb
python3 gc3d_app.py convert abta003.p3m -o saida/ --texture-dir texturas/

# voltar para o jogo
python3 gc3d_app.py convert personagem.glb -o saida/
python3 gc3d_app.py convert personagem.glb -o saida/ --no-animations
```

### `batch` — muitos arquivos

```bash
# extrair uma pasta inteira, casando animações automaticamente
python3 gc3d_app.py batch "GRAND CHASE/Models" \
    --anim-dir "GRAND CHASE/ANIMACOES" -o saida/

# devolver uma pasta de modelos editados
python3 gc3d_app.py batch modelos_editados/ -o saida/

# várias pastas, sem entrar em subpastas
python3 gc3d_app.py batch Models/ Faces/ Armas/ --no-recursive -o saida/
```

### Todas as opções

| Opção | Efeito |
|-------|--------|
| `-o`, `--output` | arquivo `.glb` ou pasta de destino |
| `-a`, `--anim` | uma animação a incluir; pode repetir |
| `--anim-dir` | inclui as animações compatíveis da pasta |
| `--merge` | junta tudo em um único `.glb` |
| `--match-bones` | inclui só as animações com o mesmo número de ossos |
| `--texture` | usa esta textura específica |
| `--texture-dir` | pasta extra onde procurar; pode repetir |
| `--no-texture` | não procura, embute nem extrai textura |
| `--texture-format` | `dds` (padrão) ou `png` na volta para o jogo |
| `--no-animations` | ao voltar para o jogo, não gera os `.frm` |
| `--single-sided` | material de um lado só |
| `--alpha-mode` | `OPAQUE`, `MASK` ou `BLEND` (padrão: automático) |
| `--keep-normals` | não normaliza normais não unitárias |
| `--pretty-json` | grava o JSON do GLB indentado, para depuração |
| `--no-recursive` | (só no `batch`) não entra em subpastas |
| `-v`, `--verbose` | mostra todos os avisos |
| `-q`, `--quiet` | só erros |

Código de saída 0 em sucesso, diferente de 0 em falha.

---

## No Blender

### Importar

`File → Import → glTF 2.0 (.glb/.gltf)`

Você recebe:

- um objeto de malha com a textura já aplicada;
- um objeto armature chamado `root`, com os ossos nomeados `bone_0`, `bone_1`...;
- uma **action** por animação, todas em `bpy.data.actions`.

Os nomes `bone_N` não são cosméticos: são eles que permitem devolver o modelo ao
jogo mantendo a numeração original dos ossos. **Não renomeie os ossos** se você
pretende reaproveitar os `.frm` que o jogo já tem.

### Trocar de animação

O importador do Blender atribui apenas a primeira action. Para ver as outras:

1. Selecione o armature.
2. Abra **Dope Sheet → Action Editor**.
3. Escolha na lista de actions.

Com muitas animações, o **Nonlinear Animation** (NLA) é mais prático: cada action
aparece como um strip que você liga e desliga.

### Ajuste importante: FPS 55

As animações do Grand Chase rodam a **55 FPS**. Antes de qualquer coisa, ponha a
cena em 55 em `Output Properties → Frame Rate → Custom`.

Isso importa por dois motivos: a animação toca na velocidade certa, e — se você
pretende exportar de volta — o Blender quantiza os instantes dos keyframes no FPS
da cena. Com 24 FPS (o padrão), uma animação de 120 frames volta com 118.

### Escala e orientação

Os modelos vêm em escala pequena (o típico fica em torno de 2 unidades de altura).
O eixo Y é para cima no glTF, e o Blender converte para Z-up na importação
automaticamente.

---

## Devolvendo um modelo ao jogo

### O que você recebe

```
personagem.p3m                 malha, esqueleto e skinning
personagem_<animacao>.frm      uma por animação presente no glTF
personagem.png                 a textura, se estava embutida
```

### Antes de exportar do Blender

Uma lista curta que evita a maioria dos problemas:

1. **Cena em 55 FPS.**
2. **Aplique as transformações** de objeto (`Object → Apply → All Transforms`). O
   bind pose do P3M só guarda translação; rotação ou escala num objeto acima dos
   ossos é perdida, e o conversor avisa quando isso acontece.
3. **Triangule a malha** (`Modifier → Triangulate`, ou marque a opção no
   exportador). Primitivas que não são triângulos são ignoradas.
4. **Mantenha os nomes `bone_N`** se quiser reaproveitar os `.frm` do jogo.
5. Ao exportar, marque **Include → Animations** e escolha o modo **Actions** para
   levar todas as animações, não só a ativa.

### O que o formato do jogo impõe

| Restrição | O que acontece se você passar |
|-----------|-------------------------------|
| **Um osso por vértice** | fica o de maior peso, com aviso da quantidade |
| **Uma malha por arquivo** | todas as primitivas são mescladas, com aviso |
| **Máximo 255 ossos** | erro explicando quanto reduzir |
| **Máximo 65535 vértices** | erro; use Decimate ou divida a malha |
| **Máximo 65535 triângulos** | erro |
| Sem morph targets | ignorados, com aviso |

As animações são **reamostradas para 55 FPS** automaticamente, então você pode
animar no FPS que preferir — mas veja a ressalva sobre quantização acima.

### Sobre a textura

Ela volta como **`.dds`**, o formato que o jogo lê — não é preciso converter nada.

O arquivo sai **sem compressão**: 24 bits quando a imagem é opaca, 32 bits quando
tem transparência, com as mesmas máscaras de canal dos arquivos originais do jogo.
Escolhi assim porque das 406 texturas do Grand Chase analisadas, 281 já são sem
compressão, então o formato é comprovadamente aceito, e a gravação não perde
nenhum pixel.

O único custo é tamanho em disco: uma textura de 128×128 ocupa 49 KB em vez dos
8 KB de um DXT1. Se isso importar, recomprima com o `texconv` da Microsoft, o GIMP
com plugin DDS ou o Paint.NET.

Use `--texture-format png` se preferir PNG (por exemplo para editar a textura
antes).

Se o glTF tiver **mais de uma textura**, o conversor usa a da primeira malha e
avisa — o P3M v0.5 guarda apenas uma. Se a textura estiver em JPEG, o arquivo é
gravado como está, com aviso, porque este conversor não decodifica JPEG.

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

1. **O `.dds` não está junto do `.p3m`.** Use `--texture-dir`, ou copie os
   arquivos para a mesma pasta.
2. **No Blender, o viewport está em modo Solid.** Mude para *Material Preview*.
3. **O nome não corresponde a nenhuma das regras.** Indique com
   `--texture arquivo.dds`.

Rode com `-v` para ver o que aconteceu na busca.

### "usando <arquivo> por semelhança de nome"

Não existe textura com o nome exato do modelo, então o conversor pegou uma com o
mesmo prefixo. Acontece com os rostos do jogo, que têm uma textura por expressão e
nem sempre a `_00`. O aviso diz quantas alternativas existem; se a escolhida não
for a certa, use `--texture` para indicar.

### O modelo aparece com partes faltando ou invertidas

Provavelmente back-face culling. Não use `--single-sided`. No Blender, verifique
`Material Properties → Settings → Backface Culling` desmarcado.

### "os modelos usam N esqueletos diferentes"

Aviso normal ao juntar modelos de personagens diferentes num arquivo. Cada
esqueleto vira uma armature separada dentro do mesmo `.glb`. Se você esperava um
esqueleto só, é sinal de que a seleção tem peças de mais de um personagem.

### "nenhum esqueleto do arquivo tem N osso(s)"

A animação não corresponde a nenhum dos esqueletos do arquivo. Ela foi incluída no
maior, para não ser perdida, mas provavelmente pertence a outro personagem.

### A animação não aparece

- Confira a compatibilidade: `info` no modelo e no `.frm`, e compare **angle
  bones** com **ossos**. Números diferentes significam esqueletos diferentes.
- No Blender, a action precisa ser selecionada manualmente (ver acima).
- Se `--anim-dir` reportou "0 animações compatíveis", nenhuma animação daquela
  pasta pertence ao modelo.

### A animação toca em velocidade errada

Ponha o FPS da cena em 55.

### "o glTF nao tem nenhuma malha triangulada para converter"

A malha não está triangulada, ou as primitivas usam um `mode` diferente de
TRIANGLES. Adicione um modifier Triangulate, ou marque a opção de triangular no
exportador do Blender.

### "o modelo tem N ossos e o P3M v0.5 aceita no maximo 255"

O esqueleto é grande demais. Junte ou remova ossos no Blender.

### "a malha tem N vertices e o P3M v0.5 aceita no maximo 65535"

O contador de vértices do formato é um inteiro de 16 bits. Use o modifier Decimate,
ou divida a malha em partes e exporte cada uma como um `.p3m`.

### "N vertice(s) tinham mais de um osso influente"

Aviso normal ao vir do Blender, que usa skinning suave. O P3M v0.5 só guarda um
osso por vértice, então fica o de maior peso. Se a deformação ficar ruim numa
articulação, ajuste os pesos no Blender para que um osso domine claramente.

### "o no raiz do esqueleto tem translacao ... tratada como posicao no mundo"

Aviso normal. O Blender assa o primeiro frame do movimento da raiz na pose de
descanso; o conversor separa isso de volta, porque essa posição pertence ao `.frm`
e não ao bind pose. Contá-la duas vezes faria o modelo flutuar no jogo.

### "os ossos foram reordenados para seguir a numeracao bone_N"

Aviso normal. O exportador do Blender usa sua própria ordem de joints; o conversor
restaura a numeração original do Grand Chase para que os `.frm` existentes
continuem casando.

### O modelo voltou com mais vértices do que tinha

O Blender divide vértices em costuras de UV e de normal. A geometria é a mesma. Se
isso for um problema (por causa do limite de 65535), use `Mesh → Merge → By
Distance` antes de exportar.

### Aviso "N normais nao unitarias normalizadas"

Normal. Vários arquivos oficiais têm normais fora de escala, e o glTF exige normais
unitárias. Use `--keep-normals` se quiser preservar os valores originais.

### Aviso "N bytes extras ignorados no fim do P3M"

Normal, aparece em 115 dos 131 arquivos analisados. São dados que o jogo não usa.

### O arrastar e soltar não funciona

Falta o pacote opcional `tkinterdnd2`. Instale com `pip install tkinterdnd2`, ou
use os botões de adicionar, que fazem o mesmo. Os executáveis prontos já vêm com o
recurso.

### A interface gráfica não abre

Falta o tkinter. No Windows, reinstale o Python marcando **"tcl/tk and IDLE"**. No
Linux:

```bash
sudo dnf install python3-tkinter     # Fedora
sudo apt install python3-tk          # Debian, Ubuntu
sudo pacman -S tk                    # Arch
```

A linha de comando funciona sem tkinter.

Isso vale apenas para quem roda pelo código. Os executáveis prontos já trazem o
tkinter dentro.

### O AppImage não executa

Se aparecer algo sobre `GLIBC_2.xx not found`, o seu sistema é mais antigo do que
o AppImage suporta. Ele exige **glibc 2.35 ou mais nova**, o que cobre Ubuntu
22.04+, Debian 12+, Fedora 36+ e RHEL 9+. Rode pelo código-fonte nesse caso.

Se a mensagem falar de **fuse** ou `libfuse.so.2`, a sua distribuição não traz
mais a biblioteca que monta AppImages. Duas saídas:

```bash
./GrandChase3D-1.6.0-x86_64.AppImage --appimage-extract-and-run
sudo apt install libfuse2            # Debian, Ubuntu
```

E se nada acontecer ao dar duplo clique, provavelmente falta a permissão de
execução:

```bash
chmod +x GrandChase3D-1.6.0-x86_64.AppImage
```

### No Windows, o prompt volta antes da saída do comando

É esperado, e não é defeito. O `.exe` é compilado no subsistema gráfico para que
o clique duplo não abra uma janela preta atrás da interface. O preço é que o
`cmd` não espera um programa gráfico terminar, então ele devolve o prompt e a
saída aparece depois, misturada com o prompt novo.

Em script, force a espera:

```bat
start /wait GrandChase3D-1.6.0.exe convert modelo.p3m -o saida\
```

Redirecionar para arquivo com `>` e canalizar com `|` funcionam normalmente.

### Minhas configurações não foram guardadas

Veja onde o programa está gravando:

```bash
python3 gc3d_app.py config
```

Se a linha `arquivo em uso` apontar para `~/.config/gc3d` ou `%APPDATA%`, a pasta
do executável não aceita gravação — é o caso de um `.exe` dentro de
`Program Files`. Mova o executável para uma pasta sua, como a Área de Trabalho ou
Documentos, se quiser o comportamento portátil.

### Como saber se um arquivo gerado está bom

```bash
# um GLB
python3 tools/glb_inspect.py inspect saida/abta003.glb

# um P3M que você acabou de gerar
python3 gc3d_app.py info saida/personagem.p3m

# ida e volta completa, comparando com o original
python3 tools/roundtrip_check.py --anim-dir animacoes/ modelos/
```

---

## Uso como biblioteca

```python
import sys
sys.path.insert(0, "src")

from gc3d import convert_model, convert_to_gc, ConvertOptions

# extrair do jogo
resultado = convert_model(
    "abta003.p3m",
    "saida/abta003.glb",
    ["andar.frm", "pular.frm"],
    ConvertOptions(embed_texture=True, texture_dirs=["texturas/"]),
)
print(resultado.ok, resultado.summary)

# devolver para o jogo
resultado = convert_to_gc("personagem.glb", "saida/")
print(resultado.outputs)   # ['saida/personagem.p3m', 'saida/personagem.png', ...]
for aviso in resultado.warnings:
    print("aviso:", aviso)
```

Inspecionando os dados crus:

```python
from gc3d.formats import p3m, frm, gltf_in

modelo = p3m.load_p3m("abta003.p3m")
print(modelo.num_angle_bones, len(modelo.skin_vertices))
print(modelo.position_bones[0].position, modelo.position_bones[0].children)

animacao = frm.load_frm("4528.frm")
print(animacao.frames[0].bones[0])   # matriz 4x4 column-major, 16 floats

documento = gltf_in.load_gltf("personagem.glb")
print(len(documento.nodes), len(documento.animations))
```

Montando e gravando uma cena à mão:

```python
from gc3d import build_scene
from gc3d.formats.glb import export_glb, GlbOptions
from gc3d.formats import p3m, frm

cena = build_scene("abta003.p3m", ["andar.frm"])
print(cena.summary())
cena.normalize_normals()

# para glTF
cena.to_right_handed()
dados = export_glb(cena, GlbOptions(double_sided=True))

# de volta para os formatos do jogo
cena.to_left_handed()
p3m.save_p3m(p3m.scene_to_p3m(cena), "saida.p3m")
for animacao in cena.animations:
    frm.save_frm(
        frm.animation_to_frm(animacao, len(cena.skeleton)),
        f"saida_{animacao.name}.frm",
    )
```

Convertendo texturas isoladamente:

```python
from gc3d.textures import dds_to_png

with open("abta003.dds", "rb") as origem:
    png = dds_to_png(origem.read())
with open("abta003.png", "wb") as destino:
    destino.write(png)
```
