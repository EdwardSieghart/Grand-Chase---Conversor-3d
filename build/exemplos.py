#!/usr/bin/env python3
"""Monta o zip de exemplos que acompanha a Release.

    python3 build/exemplos.py

Saida: release/GrandChase3D-<versao>-exemplos.zip

POR QUE ESTE ZIP EXISTE

A Release entrega um executavel por sistema e mais nada. Quem baixa so o `.exe`
fica sem nenhum arquivo do jogo para experimentar, e "abra um .p3m" nao ajuda
quem ainda nao extraiu nada do Grand Chase. Este zip resolve isso com alguns
modelos, uma animacao e as texturas correspondentes — o suficiente para o
primeiro teste dar certo e o usuario ver que o programa funciona antes de mexer
nos proprios arquivos.

Sao poucos e pequenos de proposito: o zip nao e um repositorio de assets.

O QUE ESTE SCRIPT NAO FAZ MAIS

Ele substituiu o antigo `build/empacotar.py`, que montava uma pasta por sistema
com o codigo Python, os binarios e lancadores `Converter.sh` e `Converter.bat`.
Aquilo existia porque havia dois executaveis e um modo de reserva rodando pelo
Python. Com um executavel unico por sistema, a pasta inteira era embalagem em
volta de um arquivo que ja se basta, e os lancadores so tinham como funcao
escolher entre coisas que nao existem mais.
"""

from __future__ import annotations

import os
import re
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AQUI)
RELEASE_DIR = os.path.join(PROJECT_ROOT, "release")

#: Quantos arquivos de cada tipo entram. Dois modelos mostram que da para
#: converter varios de uma vez; uma animacao basta para demonstrar o recurso; as
#: texturas precisam casar com os modelos escolhidos, e nao sao contadas aqui.
LIMITES = {"p3m": 2, "frm": 1}


def ler_versao() -> str:
    """Le a versao do pacote, sem importar o modulo."""
    caminho = os.path.join(PROJECT_ROOT, "src", "gc3d", "__init__.py")
    with open(caminho, encoding="utf-8") as arquivo:
        achado = re.search(r'__version__\s*=\s*"([^"]+)"', arquivo.read())
    return achado.group(1) if achado else "0.0.0"


def escolher_exemplos() -> list[tuple[str, str]]:
    """Escolhe os arquivos de exemplo. Devolve pares (caminho, nome no zip).

    As texturas nao sao escolhidas por contagem, e sim pelo nome dos modelos
    selecionados: um `.dds` de outro personagem no zip seria peso morto, e a
    ausencia da textura certa faria o primeiro teste do usuario sair sem cor.
    """
    origem = os.path.join(PROJECT_ROOT, "samples")
    if not os.path.isdir(origem):
        return []

    escolhidos: list[tuple[str, str]] = []
    modelos: list[str] = []

    for tipo, limite in LIMITES.items():
        pasta = os.path.join(origem, tipo)
        if not os.path.isdir(pasta):
            continue
        nomes = sorted(
            nome
            for nome in os.listdir(pasta)
            if nome.lower().endswith("." + tipo)
        )
        for nome in nomes[:limite]:
            escolhidos.append((os.path.join(pasta, nome), nome))
            if tipo == "p3m":
                modelos.append(os.path.splitext(nome)[0])

    pasta_dds = os.path.join(origem, "dds")
    if os.path.isdir(pasta_dds):
        for base in modelos:
            textura = base + ".dds"
            caminho = os.path.join(pasta_dds, textura)
            if os.path.isfile(caminho):
                escolhidos.append((caminho, textura))

    return escolhidos


def texto_leia_me(versao: str, exemplos: list[str]) -> str:
    listados = "\n".join(f"    {nome}" for nome in sorted(exemplos))
    return f"""\
Grand Chase 3D Importer {versao} — arquivos de exemplo
======================================================

Este zip NAO contem o programa. Sao apenas arquivos do jogo para voce testar o
conversor na primeira vez, sem precisar extrair nada antes.

O programa esta na mesma pagina de Release, um arquivo por sistema:

    Windows   GrandChase3D-{versao}.exe
    Linux     GrandChase3D-{versao}-x86_64.AppImage


O QUE TEM AQUI
--------------

{listados}

Os .p3m sao modelos, o .frm e uma animacao, e os .dds sao as texturas dos
modelos. Os nomes casam de proposito: o conversor acha a textura sozinho quando
ela tem o mesmo nome do modelo e esta na mesma pasta.


COMO TESTAR
-----------

Pela interface: abra o programa, arraste estes arquivos para a lista e clique em
converter. Ele percebe que entraram .p3m e .frm, e portanto que a saida e .glb.

Pela linha de comando:

    gc3d convert abta000.p3m -o saida/

Para o caminho de volta, converta o .glb gerado:

    gc3d convert saida/abta000.glb -o volta/

Devem sair um .p3m e um .dds. A textura volta em DDS porque e o formato que o
jogo le.


NO BLENDER
----------

O Grand Chase roda a 55 quadros por segundo, e o Blender comeca em 24. Ao abrir
um .glb com animacao, ajuste para 55 em Output Properties > Frame Rate > Custom,
senao a animacao roda em velocidade errada.

O Grand Chase usa Y como altura e o Blender usa Z. O conversor ja faz essa troca;
se um modelo aparecer deitado, o problema nao e o eixo.


ONDE FICAM AS CONFIGURACOES
---------------------------

Num arquivo gc3d.ini na mesma pasta do executavel, o que deixa o programa
portatil: leve o executavel e o INI num pendrive e as suas preferencias vao
junto. Para ver onde estao:

    gc3d config
"""


def main() -> int:
    versao = ler_versao()
    exemplos = escolher_exemplos()
    if not exemplos:
        print("ERRO: nenhum exemplo encontrado em samples/")
        return 1

    os.makedirs(RELEASE_DIR, exist_ok=True)
    destino = os.path.join(RELEASE_DIR, f"GrandChase3D-{versao}-exemplos.zip")

    print(f"Grand Chase 3D Importer {versao} — zip de exemplos")
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zip_saida:
        for caminho, nome in exemplos:
            zip_saida.write(caminho, nome)
            print(f"  {nome}  ({os.path.getsize(caminho) / 1024:.0f} KB)")
        leia_me = texto_leia_me(versao, [nome for _caminho, nome in exemplos])
        zip_saida.writestr("LEIA-ME.txt", leia_me)
        print("  LEIA-ME.txt")
        zip_saida.write(os.path.join(PROJECT_ROOT, "LICENSE"), "LICENSE")
        print("  LICENSE")

    print()
    print(f"{destino}  ({os.path.getsize(destino) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
