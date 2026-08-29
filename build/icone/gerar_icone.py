#!/usr/bin/env python3
"""Gera o icone do Grand Chase 3D Importer.

Sai daqui:

    gc3d.png   256x256, usado pelo AppImage e pelo atalho no Linux
    gc3d.ico   16 a 256, usado pelo .exe e pela barra de tarefas do Windows
    prova.png  folha de contato para conferir a olho (nao versionada)

Os dois primeiros sao VERSIONADOS no repositorio. Este script existe para o
icone ser reproduzivel e ajustavel, nao para rodar durante o build: nem o
GitHub Actions nem o build local precisam do Pillow, so quem for mexer no
desenho.

    python3 -m pip install Pillow
    python3 build/icone/gerar_icone.py

O desenho e um cubo isometrico ambar sobre fundo escuro. O cubo diz "3D", e uma
flecha de duas pontas atravessando a base diz "converte nos dois sentidos", que
e exatamente o que o programa faz.

A restricao que manda no desenho e o tamanho de 16 pixels da barra de tarefas do
Windows. Duas decisoes vem dela:

* nada de contorno fino, texto ou detalhe pequeno — tres faces planas de cores
  bem separadas continuam legiveis quando a imagem vira um carimbo;

* de 32 pixels para baixo a flecha e ABANDONADA e o cubo cresce para ocupar o
  espaco. Reduzir o desenho inteiro faz a flecha virar uma mancha cinza colada
  na base do cubo, que suja a silhueta sem comunicar nada. O `.ico` guarda um
  desenho proprio para esses tamanhos, e o Windows escolhe sozinho qual usar.

Tudo e desenhado numa tela 8 vezes maior e reduzido com LANCZOS no fim, porque
o Pillow nao tem antisserrilhado em poligono: as diagonais do cubo sairiam
escadinha se desenhassemos direto no tamanho final.
"""

from __future__ import annotations

import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - script de autor, nao de build
    sys.exit(
        "Este script precisa do Pillow:\n"
        "    python3 -m pip install Pillow\n"
        "Os arquivos gc3d.png e gc3d.ico ja versionados nao dependem dele."
    )

AQUI = os.path.dirname(os.path.abspath(__file__))

#: Fator de ampliacao da tela de desenho.
ESCALA = 8
LADO = 256
TELA = LADO * ESCALA

# Fundo: azul quase preto, na mesma familia do tema escuro da interface.
FUNDO_TOPO = (32, 38, 54)
FUNDO_BASE = (16, 19, 27)

# Cubo em ambar, que remete a paleta dourada do jogo. As tres faces em tons bem
# distantes um do outro e o que da a leitura de volume em tamanho pequeno.
FACE_TOPO = (255, 209, 102)
FACE_ESQUERDA = (232, 163, 61)
FACE_DIREITA = (176, 112, 28)

FLECHA = (245, 247, 250)

#: Tamanhos que entram no .ico.
TAMANHOS_ICO = [16, 24, 32, 48, 64, 128, 256]

#: Deste tamanho para baixo, desenho simplificado sem a flecha.
LIMITE_SIMPLIFICADO = 32


def _fundo(desenho: ImageDraw.ImageDraw) -> Image.Image:
    """Pinta o degrade e devolve a mascara de canto arredondado."""
    for y in range(TELA):
        fracao = y / (TELA - 1)
        cor = tuple(
            round(inicio + (fim - inicio) * fracao)
            for inicio, fim in zip(FUNDO_TOPO, FUNDO_BASE)
        )
        desenho.line([(0, y), (TELA, y)], fill=cor + (255,))

    mascara = Image.new("L", (TELA, TELA), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [(0, 0), (TELA - 1, TELA - 1)], radius=int(56 * ESCALA), fill=255
    )
    return mascara


def _cubo(desenho: ImageDraw.ImageDraw, centro_y: float, escala: float) -> None:
    """Cubo isometrico: um losango no topo e duas faces descendo.

    `centro_y` e o meio vertical do cubo e `escala` multiplica o tamanho, para o
    desenho simplificado poder usar o espaco que a flecha deixou livre.
    """
    centro_x = 128 * ESCALA
    largura = 60 * ESCALA * escala
    altura = 34 * ESCALA * escala
    profundidade = 58 * ESCALA * escala

    topo_y = centro_y - profundidade / 2

    cima = (centro_x, topo_y - altura)
    direita = (centro_x + largura, topo_y)
    baixo = (centro_x, topo_y + altura)
    esquerda = (centro_x - largura, topo_y)

    desenho.polygon([cima, direita, baixo, esquerda], fill=FACE_TOPO + (255,))
    desenho.polygon(
        [
            esquerda,
            baixo,
            (baixo[0], baixo[1] + profundidade),
            (esquerda[0], esquerda[1] + profundidade),
        ],
        fill=FACE_ESQUERDA + (255,),
    )
    desenho.polygon(
        [
            baixo,
            direita,
            (direita[0], direita[1] + profundidade),
            (baixo[0], baixo[1] + profundidade),
        ],
        fill=FACE_DIREITA + (255,),
    )


def _flecha_de_duas_pontas(desenho: ImageDraw.ImageDraw) -> None:
    """Flecha horizontal de duas pontas, atravessando a base do cubo.

    Fica SOBRE o cubo de proposito: separada, competiria por espaco e as duas
    coisas encolheriam. Por cima, ela le como "este objeto vai e volta".
    """
    y = 194 * ESCALA
    meio = 128 * ESCALA
    alcance = 78 * ESCALA
    grossura = 14 * ESCALA
    ponta = 30 * ESCALA
    abertura = 29 * ESCALA

    desenho.rectangle(
        [
            (meio - alcance + ponta * 0.55, y - grossura / 2),
            (meio + alcance - ponta * 0.55, y + grossura / 2),
        ],
        fill=FLECHA + (255,),
    )
    desenho.polygon(
        [
            (meio - alcance, y),
            (meio - alcance + ponta, y - abertura),
            (meio - alcance + ponta, y + abertura),
        ],
        fill=FLECHA + (255,),
    )
    desenho.polygon(
        [
            (meio + alcance, y),
            (meio + alcance - ponta, y - abertura),
            (meio + alcance - ponta, y + abertura),
        ],
        fill=FLECHA + (255,),
    )


def desenhar(com_flecha: bool = True) -> Image.Image:
    """Desenha na tela ampliada e devolve a imagem final de 256x256."""
    imagem = Image.new("RGBA", (TELA, TELA), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    mascara = _fundo(desenho)
    if com_flecha:
        _cubo(desenho, centro_y=120 * ESCALA, escala=1.0)
        _flecha_de_duas_pontas(desenho)
    else:
        # Sem a flecha, o cubo ocupa o centro e cresce.
        _cubo(desenho, centro_y=130 * ESCALA, escala=1.28)
    imagem.putalpha(mascara)
    return imagem.resize((LADO, LADO), Image.LANCZOS)


def main() -> int | str:
    completo = desenhar(com_flecha=True)
    simples = desenhar(com_flecha=False)

    png = os.path.join(AQUI, "gc3d.png")
    completo.save(png, "PNG")
    print(f"{png}  ({LADO}x{LADO})")

    # O .ico guarda varias resolucoes e o Windows escolhe a que precisa. Sem os
    # tamanhos pequenos ele reduziria o de 256 na hora, e o resultado fica
    # borrado na barra de tarefas.
    #
    # ATENCAO a uma armadilha do Pillow: para cada tamanho pedido ele procura,
    # entre as imagens fornecidas, uma daquele tamanho exato. Nao achando, ele
    # pega a ULTIMA da lista e chama thumbnail() — que nunca amplia. Fornecer so
    # as versoes pequenas fazia o 48, o 64 e o 128 nascerem do 32 e continuarem
    # com 32 pixels, e o arquivo saia com resolucoes repetidas e faltando as
    # grandes. Por isso entregamos TODOS os tamanhos prontos, sem deixar nenhum
    # para o Pillow improvisar.
    alternativas = [
        (simples if lado <= LIMITE_SIMPLIFICADO else completo).resize(
            (lado, lado), Image.LANCZOS
        )
        for lado in TAMANHOS_ICO
        if lado != LADO
    ]
    ico = os.path.join(AQUI, "gc3d.ico")
    completo.save(
        ico,
        "ICO",
        sizes=[(lado, lado) for lado in TAMANHOS_ICO],
        append_images=alternativas,
    )
    conferencia = sorted(largura for largura, _ in Image.open(ico).ico.sizes())
    if conferencia != sorted(TAMANHOS_ICO):
        return f"o .ico saiu com {conferencia}, esperado {sorted(TAMANHOS_ICO)}"
    simplificados = [t for t in TAMANHOS_ICO if t <= LIMITE_SIMPLIFICADO]
    print(
        f"{ico}  ({', '.join(str(t) for t in conferencia)}"
        f"; sem flecha em {', '.join(str(t) for t in simplificados)})"
    )

    # Folha de contato: mostra como cada tamanho realmente vai aparecer, ja
    # escolhendo entre o desenho completo e o simplificado como o Windows fara.
    contato = Image.new("RGBA", (LADO + 210, LADO), (26, 26, 26, 255))
    contato.alpha_composite(completo, (0, 0))
    x, y = LADO + 16, 8
    for lado in (128, 64, 48, 32, 24, 16):
        fonte = simples if lado <= LIMITE_SIMPLIFICADO else completo
        contato.alpha_composite(fonte.resize((lado, lado), Image.LANCZOS), (x, y))
        y += lado + 10
        if y > LADO - 20:
            y = 8
            x += 140
    prova = os.path.join(AQUI, "prova.png")
    contato.save(prova, "PNG")
    print(f"{prova}  (conferencia visual, nao versionado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
