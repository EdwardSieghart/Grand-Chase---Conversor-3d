"""Ponto de entrada unico do Grand Chase 3D Importer.

Um executavel so, que se comporta de tres jeitos conforme como e chamado:

    gc3d                          abre a interface grafica
    gc3d convert modelo.p3m -o .  age como linha de comando
    gc3d modelo.p3m               abre a interface com o arquivo ja carregado

O terceiro caso existe por causa do arrastar e soltar sobre o icone do programa:
o sistema entrega os caminhos como argumentos, e quem faz isso quer a janela, nao
a linha de comando. Como a linha de comando SEMPRE exige um subcomando
(`convert`, `batch` ou `info`), distinguir os dois casos e simples e nao ha
ambiguidade a resolver.

Antes existiam dois binarios, `gc3d` e `gc3d-gui`. Um arquivo unico e mais facil
de distribuir — nada de pasta com lancadores — e o preco e o remendo do console
no Windows, explicado abaixo.


O problema do console no Windows
--------------------------------

No Windows um programa e compilado para um dos dois subsistemas, e a escolha e
gravada no executavel:

* subsistema de console: a linha de comando funciona certo, mas ao abrir por
  clique duplo aparece uma janela preta vazia atras da interface;
* subsistema grafico: o clique duplo fica limpo, mas o processo nasce sem saida
  padrao, e `gc3d.exe info modelo.p3m` no `cmd` nao imprime nada.

Escolhemos o subsistema grafico, porque o clique duplo e o uso normal, e
recuperamos a saida a mao quando ha argumentos: `AttachConsole` pendura o
processo no console de quem o chamou e reabrimos `stdout`, `stderr` e `stdin`.

Um detalhe importante e a ordem dessa recuperacao. Se a saida foi redirecionada
ou canalizada (`gc3d.exe info a.p3m > lista.txt`, ou `| more`), o `cmd` ja
entregou os identificadores certos ao processo, e escrever no console
atropelaria o redirecionamento — o arquivo sairia vazio. Por isso tentamos
primeiro os identificadores herdados, e so caimos no console (`CONOUT$`) quando
nao houver nenhum.

Resta uma limitacao que nao tem contorno dentro de um executavel unico: o `cmd`
nao espera um programa do subsistema grafico terminar, entao ele devolve o prompt
antes da saida aparecer, e as linhas saem embaralhadas com o prompt novo. Para
uso em script, `start /wait gc3d.exe ...` resolve. No Linux nada disso existe.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

#: Subcomandos da linha de comando. Se o primeiro argumento for um destes, ou
#: comecar com '-', o usuario quer a linha de comando.
CLI_COMMANDS = frozenset({"convert", "batch", "info", "config"})


def wants_cli(argv: list[str]) -> bool:
    """O usuario esta pedindo a linha de comando, e nao a interface?

    Sem argumentos, nao. Com um subcomando conhecido ou uma opcao (`--version`,
    `--help`), sim. Com apenas caminhos de arquivo — o que acontece ao arrastar
    arquivos sobre o icone do programa — nao: abre a janela com eles carregados.
    """
    if not argv:
        return False
    first = argv[0]
    return first in CLI_COMMANDS or first.startswith("-")


# ------------------------------------------------------------ console (Windows)


def attach_console() -> bool:
    """Devolve a saida padrao a um processo do subsistema grafico no Windows.

    Devolve True se ha para onde escrever depois desta chamada. Fora do Windows,
    ou rodando pelo interprete Python, nao ha nada a fazer e devolve True.
    """
    if sys.platform != "win32":
        return True
    # Rodando por 'python gc3d_app.py' o console ja e do processo.
    if not getattr(sys, "frozen", False):
        return True

    import ctypes
    import msvcrt

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ATTACH_PARENT_PROCESS = -1
    STD_INPUT, STD_OUTPUT, STD_ERROR = -10, -11, -12

    # Declarar os tipos nao e capricho: o ctypes assume `c_int` como retorno
    # padrao, e um HANDLE do Windows tem o tamanho de um ponteiro. Em 64 bits o
    # valor seria truncado em silencio e o identificador viraria lixo.
    kernel32.GetStdHandle.argtypes = [ctypes.c_uint]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.AttachConsole.argtypes = [ctypes.c_uint]
    kernel32.AttachConsole.restype = ctypes.c_int

    #: GetStdHandle devolve isto quando nao ha identificador. O 32 bits aparece
    #: como 0xFFFFFFFF e o 64 bits como 0xFFFFFFFFFFFFFFFF; nenhum dos dois e
    #: igual a -1 depois de passar por c_void_p, entao conferimos os tres.
    INVALIDOS = (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)

    def identificador(handle_id: int) -> int | None:
        try:
            handle = kernel32.GetStdHandle(handle_id)
        except Exception:  # noqa: BLE001
            return None
        if handle is None or int(handle) in INVALIDOS:
            return None
        return int(handle)

    # Os identificadores herdados sao lidos ANTES de mexer no console, e a ordem
    # importa: o AttachConsole pode substituir os identificadores padrao do
    # processo pelos do console, e ai `gc3d.exe info a.p3m > lista.txt` perderia
    # o arquivo e escreveria na tela — o oposto do que o usuario pediu.
    herdados = {
        STD_OUTPUT: identificador(STD_OUTPUT),
        STD_ERROR: identificador(STD_ERROR),
        STD_INPUT: identificador(STD_INPUT),
    }

    # Pode falhar quando nao existe console nenhum — clique duplo, ou arquivo
    # arrastado sobre o icone. Nao e erro: seguimos e a interface assume.
    attached = bool(kernel32.AttachConsole(ATTACH_PARENT_PROCESS))

    def inherited(handle_id: int, write: bool):
        """Fluxo a partir do identificador que o processo pai entregou.

        E o caminho do redirecionamento e do canal. Tem prioridade sobre o
        console: se a saida vai para um arquivo, e no arquivo que ela deve cair.
        """
        handle = herdados.get(handle_id)
        if handle is None:
            return None
        try:
            flags = os.O_WRONLY if write else os.O_RDONLY
            descriptor = msvcrt.open_osfhandle(handle, flags)
            return os.fdopen(
                descriptor,
                "w" if write else "r",
                buffering=1,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, ValueError):
            return None

    def console(device: str, write: bool):
        """Fluxo ligado direto ao console, quando nao ha identificador herdado."""
        if not attached:
            return None
        try:
            return open(
                device,
                "w" if write else "r",
                buffering=1,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None

    if sys.stdout is None:
        sys.stdout = inherited(STD_OUTPUT, True) or console("CONOUT$", True)
    if sys.stderr is None:
        sys.stderr = inherited(STD_ERROR, True) or console("CONOUT$", True)
    if sys.stdin is None:
        sys.stdin = inherited(STD_INPUT, False) or console("CONIN$", False)

    return sys.stdout is not None


def _report_without_console(argv: list[str]) -> None:
    """Ultimo recurso: mostra o erro numa janela quando nao ha console.

    Acontece se alguem criar um atalho do subsistema grafico passando
    argumentos de linha de comando. Sem isto o programa sumiria calado.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Grand Chase 3D Importer",
            "Este comando precisa de um terminal para mostrar a saida:\n\n"
            f"    gc3d {' '.join(argv)}\n\n"
            "Abra o Prompt de Comando e rode o programa por lá, ou abra o "
            "programa sem argumentos para usar a interface grafica.",
        )
        root.destroy()
    except Exception:  # noqa: BLE001 - sem console e sem janela, nada a fazer
        pass


# ------------------------------------------------------------------- despacho


def run_cli(argv: list[str]) -> int:
    if not attach_console():
        _report_without_console(argv)
        return 1
    import gc3d_cli

    return gc3d_cli.main(argv)


def run_gui(preload: list[str]) -> int:
    import gc3d_gui

    return gc3d_gui.main(preload=preload)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if wants_cli(argv):
        return run_cli(argv)
    return run_gui(argv)


if __name__ == "__main__":
    sys.exit(main())
