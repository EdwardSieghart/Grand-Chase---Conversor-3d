#!/usr/bin/env python3
"""Interface grafica do Grand Chase 3D Importer.

Tela unica, tema escuro, e o sentido da conversao deduzido do que for carregado:

* entram `.p3m` e `.frm`  ->  sai `.glb`
* entra  `.glb` / `.gltf` ->  saem `.p3m` e `.frm`

Nao ha botao de escolher o sentido: dado o que o usuario carregou, so existe um
destino possivel, e perguntar seria redundante.

Usa apenas tkinter, que vem junto com o Python no Windows e esta disponivel em
qualquer distribuicao Linux. Isso mantem o programa com zero dependencias e faz o
executavel empacotado ficar pequeno. O tema escuro e aplicado a mao, porque o
tkinter nao tem um: o tema "clam" e recolorido widget por widget, e o mesmo
codigo produz a mesma aparencia no Linux e no Windows.

A conversao roda em uma thread separada para a janela nao congelar; a thread
nunca toca em widgets diretamente, apenas empilha mensagens numa fila que a
thread da interface consome a cada 80 ms. Esse e o unico jeito seguro de
atualizar tkinter de outra thread.

Executar:
    python3 gc3d_gui.py
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from gc3d import (  # noqa: E402
    AnimationIndex,
    ConvertOptions,
    Direction,
    __version__,
    classify_path,
    collect_inputs,
    convert_merged,
    convert_model,
    convert_to_gc,
)
from gc3d.settings import CONFIG_NAME, Settings, executable_dir  # noqa: E402

# Arrastar e soltar arquivos nao existe no tkinter. O tkinterdnd2 fornece isso
# embutindo a extensao Tcl "tkdnd", com binarios para Linux e Windows. E uma
# dependencia OPCIONAL: sem ela a janela funciona igual, apenas sem o recurso.
# Os executaveis empacotados a incluem, entao para o usuario final o recurso vem
# sempre ligado.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except Exception:  # noqa: BLE001 - qualquer falha de carga desativa o recurso
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]
    DND_AVAILABLE = False

APP_TITLE = f"Grand Chase 3D Importer {__version__}"

#: Pasta de saida sugerida na primeira execucao, antes de existir um gc3d.ini.
DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "gc3d_saida")


def _merged_output_name(model_paths: list[str]) -> str:
    """Nome do arquivo unico ao juntar varios modelos.

    Com um modelo, usa o nome dele. Com varios, usa o prefixo comum quando
    existir (`abta000`, `abta001` -> `abta00.glb`), porque as pecas de um mesmo
    personagem tendem a compartilhar prefixo. Sem prefixo util, cai no nome da
    pasta de origem, e por fim num nome fixo.
    """
    stems = [os.path.splitext(os.path.basename(p))[0] for p in model_paths]
    if len(stems) == 1:
        return stems[0] + ".glb"

    common = os.path.commonprefix(stems).strip(" _-")
    if len(common) >= 3:
        return common + ".glb"

    folder = os.path.basename(os.path.dirname(os.path.abspath(model_paths[0])))
    if folder:
        return folder + ".glb"
    return "modelo_completo.glb"


class Dark:
    """Paleta do tema escuro.

    Valores fixos de proposito: seguir o tema do sistema exigiria detectar
    GTK/Windows e ainda assim o tkinter nao acompanharia. Uma paleta propria
    garante a mesma aparencia nas duas plataformas.
    """

    BG = "#1e1f22"
    SURFACE = "#2b2d31"
    SURFACE_HI = "#35373c"
    BORDER = "#45474d"
    FG = "#e3e5e8"
    FG_MUTED = "#9a9ca1"
    ACCENT = "#4a9eff"
    ACCENT_HOVER = "#63aeff"
    OK = "#57c46b"
    WARN = "#e3b341"
    ERROR = "#f2555a"
    SELECT_BG = "#3d4d63"


def apply_dark_theme(root: tk.Tk) -> None:
    """Recolore o tema `clam` para escuro, em todas as plataformas."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=Dark.BG)

    style.configure(".", background=Dark.BG, foreground=Dark.FG)
    style.configure("TFrame", background=Dark.BG)
    style.configure("TLabel", background=Dark.BG, foreground=Dark.FG)
    style.configure(
        "Muted.TLabel", background=Dark.BG, foreground=Dark.FG_MUTED
    )
    style.configure(
        "Heading.TLabel",
        background=Dark.BG,
        foreground=Dark.FG,
        font=("TkDefaultFont", 11, "bold"),
    )
    style.configure(
        "Direction.TLabel",
        background=Dark.SURFACE,
        foreground=Dark.ACCENT,
        font=("TkDefaultFont", 10, "bold"),
        padding=8,
        relief="flat",
    )

    style.configure(
        "TLabelframe",
        background=Dark.BG,
        foreground=Dark.FG,
        bordercolor=Dark.BORDER,
        darkcolor=Dark.BG,
        lightcolor=Dark.BG,
    )
    style.configure(
        "TLabelframe.Label", background=Dark.BG, foreground=Dark.FG_MUTED
    )

    style.configure(
        "TButton",
        background=Dark.SURFACE,
        foreground=Dark.FG,
        bordercolor=Dark.BORDER,
        darkcolor=Dark.SURFACE,
        lightcolor=Dark.SURFACE,
        focuscolor=Dark.ACCENT,
        padding=(10, 5),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("disabled", Dark.BG),
            ("pressed", Dark.BORDER),
            ("active", Dark.SURFACE_HI),
        ],
        foreground=[("disabled", Dark.FG_MUTED)],
    )

    style.configure(
        "Accent.TButton",
        background=Dark.ACCENT,
        foreground="#ffffff",
        bordercolor=Dark.ACCENT,
        darkcolor=Dark.ACCENT,
        lightcolor=Dark.ACCENT,
        padding=(14, 7),
        relief="flat",
        font=("TkDefaultFont", 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", Dark.SURFACE),
            ("pressed", "#3a86e0"),
            ("active", Dark.ACCENT_HOVER),
        ],
        foreground=[("disabled", Dark.FG_MUTED)],
    )

    style.configure(
        "TEntry",
        fieldbackground=Dark.SURFACE,
        foreground=Dark.FG,
        bordercolor=Dark.BORDER,
        lightcolor=Dark.BORDER,
        darkcolor=Dark.BORDER,
        insertcolor=Dark.FG,
        padding=5,
    )

    style.configure(
        "TCheckbutton",
        background=Dark.BG,
        foreground=Dark.FG,
        indicatorbackground=Dark.SURFACE,
        indicatorforeground=Dark.ACCENT,
        focuscolor=Dark.BG,
    )
    style.map(
        "TCheckbutton",
        background=[("active", Dark.BG)],
        indicatorbackground=[
            ("selected", Dark.ACCENT),
            ("active", Dark.SURFACE_HI),
        ],
    )

    style.configure(
        "TProgressbar",
        background=Dark.ACCENT,
        troughcolor=Dark.SURFACE,
        bordercolor=Dark.SURFACE,
        darkcolor=Dark.ACCENT,
        lightcolor=Dark.ACCENT,
        thickness=8,
    )

    style.configure(
        "Vertical.TScrollbar",
        background=Dark.SURFACE,
        troughcolor=Dark.BG,
        bordercolor=Dark.BG,
        arrowcolor=Dark.FG_MUTED,
        darkcolor=Dark.SURFACE,
        lightcolor=Dark.SURFACE,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", Dark.SURFACE_HI)],
    )


class ConverterApp(ttk.Frame):
    """Janela principal: uma tela, uma lista, um botao."""

    def __init__(self, master: tk.Tk, settings: Settings | None = None) -> None:
        super().__init__(master, padding=14)
        self.master.title(APP_TITLE)
        self.master.minsize(820, 620)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        #: Preferencias lidas do gc3d.ini ao lado do executavel.
        self.settings = settings if settings is not None else Settings.load()

        #: Caminhos carregados, em ordem de insercao.
        self.paths: list[str] = []
        self.output_dir = tk.StringVar(
            value=self.settings.pasta_saida or DEFAULT_OUTPUT_DIR
        )
        #: Pasta onde os dialogos de arquivo abrem. Lembrada entre execucoes para
        #: o usuario nao precisar navegar ate a pasta do jogo toda vez.
        self.last_dir: str = self.settings.ultima_pasta_aberta
        self.direction_text = tk.StringVar()
        self.status = tk.StringVar(value="Pronto.")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.with_texture = tk.BooleanVar(value=self.settings.incluir_textura)
        #: Juntar todos os modelos e animacoes num unico .glb. Ligado por padrao:
        #: um personagem costuma vir em varios .p3m (corpo, rosto, arma) e um
        #: arquivo com tudo dentro e mais util que um arquivo por peca.
        self.merge_all = tk.BooleanVar(value=self.settings.juntar_tudo)

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        #: Gravacao de preferencias agendada, para juntar rajadas de mudancas.
        self._save_job: str | None = None
        #: Barra gravacoes agendadas depois que a janela comecou a fechar.
        self._closing = False

        self._build_ui()
        # Digitar a pasta de saida a mao no campo tambem conta como mudanca; sem
        # este observador, so o botao "Escolher..." seria lembrado.
        self.output_dir.trace_add("write", self._on_output_typed)
        self._restore_geometry()
        # Fechar a janela pelo X tem que passar pelo nosso codigo, senao as
        # preferencias nao seriam gravadas.
        master.protocol("WM_DELETE_WINDOW", self._on_close)
        # Chama _refresh_list (nao _refresh_direction) para que a dica de lista
        # vazia seja posicionada ja na abertura.
        self._refresh_list()
        self.after(80, self._drain_queue)

    # ----------------------------------------------------------- preferencias

    def _restore_geometry(self) -> None:
        """Devolve a janela ao tamanho da ultima vez, se ainda couber na tela.

        A verificacao existe porque quem desconecta um monitor externo ficaria
        com a janela restaurada fora da area visivel, sem jeito de traze-la de
        volta. Guardamos apenas tamanho, nao posicao, o que evita o caso pior e
        deixa o gerenciador de janelas centralizar.
        """
        saved = self.settings.janela.strip()
        if not saved:
            return
        try:
            width_text, height_text = saved.lower().split("x", 1)
            width, height = int(width_text), int(height_text)
        except ValueError:
            return
        if width < 820 or height < 620:
            return
        if width > self.master.winfo_screenwidth():
            return
        if height > self.master.winfo_screenheight():
            return
        self.master.geometry(f"{width}x{height}")

    def _store_settings(self) -> None:
        self.settings.pasta_saida = self.output_dir.get()
        self.settings.ultima_pasta_aberta = self.last_dir
        self.settings.incluir_textura = bool(self.with_texture.get())
        self.settings.juntar_tudo = bool(self.merge_all.get())
        self.settings.janela = (
            f"{self.master.winfo_width()}x{self.master.winfo_height()}"
        )

    def _save_settings_soon(self) -> None:
        """Agenda a gravacao das preferencias para daqui a pouco.

        Gravar so ao fechar nao basta: se a sessao cair, o gerenciador de janelas
        destruir a janela sem pedir licenca, ou o programa for encerrado a força,
        o `WM_DELETE_WINDOW` nunca chega e tudo que o usuario ajustou se perde
        calado. Gravando a cada mudanca, o pior caso passa a ser irrelevante.

        O adiamento junta rajadas de eventos numa gravacao so — marcar duas
        caixas seguidas, ou digitar um caminho letra por letra, nao escreve o
        arquivo uma vez por tecla.
        """
        if self._closing:
            return
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        try:
            self._save_job = self.after(800, self._save_settings_now)
        except tk.TclError:
            # A janela ja foi destruida; nao ha mais o que agendar.
            self._save_job = None

    def _on_output_typed(self, *_ignored: object) -> None:
        self._save_settings_soon()

    def _save_settings_now(self) -> None:
        self._save_job = None
        self._store_settings()
        self.settings.save()

    def _on_close(self) -> None:
        """Grava as preferencias e fecha.

        Se uma conversao estiver rodando, pede confirmacao: fechar no meio
        deixaria arquivos pela metade na pasta de saida.
        """
        if self._worker is not None and self._worker.is_alive():
            if not messagebox.askyesno(
                APP_TITLE,
                "Uma conversao esta em andamento. Fechar agora pode deixar "
                "arquivos incompletos na pasta de saida.\n\nFechar mesmo assim?",
            ):
                return
            self._cancel.set()
        self._closing = True
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        # Aqui, e nao no _save_settings_soon, e onde o tamanho da janela e
        # capturado de verdade: e a ultima chance de le-lo antes do destroy().
        self._store_settings()
        self.settings.save()
        self.master.destroy()

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        # A lista e o registro sao os unicos que crescem com a janela.
        self.rowconfigure(2, weight=3)
        self.rowconfigure(5, weight=2)

        # ---- cabecalho
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Arquivos a converter",
            style="Heading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Aceita .p3m, .frm, .glb e .gltf — o sentido e detectado sozinho",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # ---- indicador de direcao
        self.direction_label = ttk.Label(
            self, textvariable=self.direction_text, style="Direction.TLabel"
        )
        self.direction_label.grid(row=1, column=0, sticky="ew", pady=(10, 8))

        # ---- lista unica
        list_frame = tk.Frame(
            self, bg=Dark.BORDER, highlightthickness=0, bd=0
        )
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.file_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            activestyle="none",
            bg=Dark.SURFACE,
            fg=Dark.FG,
            selectbackground=Dark.SELECT_BG,
            selectforeground=Dark.FG,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.file_list.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        list_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.file_list.yview
        )
        list_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        self.file_list.configure(yscrollcommand=list_scroll.set)

        # Texto de fundo mostrado quando a lista esta vazia. E aqui que o usuario
        # descobre que pode arrastar arquivos.
        self.empty_hint = tk.Label(
            self.file_list,
            text=(
                "Arraste arquivos ou pastas para cá"
                if DND_AVAILABLE
                else "Use os botões abaixo para adicionar arquivos"
            ),
            bg=Dark.SURFACE,
            fg=Dark.FG_MUTED,
            font=("TkDefaultFont", 10),
        )
        self._register_drop_target()

        # ---- botoes da lista
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            buttons, text="Adicionar arquivos...", command=self._add_files
        ).pack(side="left")
        ttk.Button(
            buttons, text="Adicionar pasta...", command=self._add_folder
        ).pack(side="left", padx=6)
        ttk.Button(
            buttons, text="Remover selecionados", command=self._remove_selected
        ).pack(side="left")
        ttk.Button(buttons, text="Limpar lista", command=self._clear).pack(
            side="left", padx=6
        )

        # ---- saida
        output = ttk.LabelFrame(self, text="Pasta de saida", padding=10)
        output.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        output.columnconfigure(0, weight=1)
        ttk.Entry(output, textvariable=self.output_dir).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(output, text="Escolher...", command=self._choose_output).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(output, text="Abrir", command=self._open_output).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Checkbutton(
            output,
            text="Incluir textura (embutir no .glb, ou extrair como .png)",
            variable=self.with_texture,
            command=self._save_settings_soon,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.merge_check = ttk.Checkbutton(
            output,
            text="Juntar tudo em um único .glb (modelos e animações)",
            variable=self.merge_all,
            command=self._on_merge_toggled,
        )
        self.merge_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # ---- registro
        log_frame = ttk.LabelFrame(self, text="Registro", padding=(2, 6, 2, 2))
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            state="disabled",
            bg=Dark.SURFACE,
            fg=Dark.FG,
            insertbackground=Dark.FG,
            selectbackground=Dark.SELECT_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
            padx=8,
            pady=6,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.tag_configure("erro", foreground=Dark.ERROR)
        self.log.tag_configure("aviso", foreground=Dark.WARN)
        self.log.tag_configure("ok", foreground=Dark.OK)
        self.log.tag_configure("muted", foreground=Dark.FG_MUTED)

        # ---- rodape
        footer = ttk.Frame(self)
        footer.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(2, weight=1)

        self.convert_button = ttk.Button(
            footer,
            text="Converter",
            style="Accent.TButton",
            command=self._start,
        )
        self.convert_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(
            footer, text="Cancelar", command=self._cancel_conversion, state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, padx=8)
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel").grid(
            row=0, column=2, sticky="e"
        )
        self.progress = ttk.Progressbar(
            footer, variable=self.progress_value, maximum=100.0
        )
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    # ------------------------------------------------------ arrastar e soltar

    def _register_drop_target(self) -> None:
        """Liga o arrastar e soltar, se o tkinterdnd2 estiver disponivel."""
        if not DND_AVAILABLE:
            return
        for widget in (self.file_list, self):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            except Exception:  # noqa: BLE001 - widget sem suporte, ignora
                continue

    def _on_drop_enter(self, event):  # noqa: ANN001, ARG002
        """Realca a lista enquanto o arquivo esta sobre a janela."""
        self.file_list.configure(bg=Dark.SURFACE_HI)
        self.empty_hint.configure(bg=Dark.SURFACE_HI)
        return event.action if hasattr(event, "action") else None

    def _on_drop_leave(self, event):  # noqa: ANN001, ARG002
        self.file_list.configure(bg=Dark.SURFACE)
        self.empty_hint.configure(bg=Dark.SURFACE)
        return None

    def _on_drop(self, event):  # noqa: ANN001
        """Recebe os caminhos soltos na janela."""
        self._on_drop_leave(event)
        paths = self._parse_drop_data(getattr(event, "data", "") or "")
        if not paths:
            return None

        # Pastas soltas sao expandidas recursivamente, igual ao botao
        # "Adicionar pasta".
        expanded: list[str] = []
        folders = 0
        for path in paths:
            if os.path.isdir(path):
                folders += 1
                models, animations, gltfs = collect_inputs([path], recursive=True)
                expanded.extend(models + animations + gltfs)
            elif os.path.isfile(path):
                expanded.append(path)
        if folders:
            self._log(f"{folders} pasta(s) solta(s), varrida(s) recursivamente.", "muted")
        self._add_paths(expanded)
        return None

    @staticmethod
    def _parse_drop_data(data: str) -> list[str]:
        """Separa a lista de caminhos que o tkdnd entrega como string Tcl.

        O formato e uma lista Tcl: caminhos sem espaco vem soltos, e caminhos com
        espaco vem entre chaves — `{/home/eu/Grand Chase/a.p3m} /tmp/b.frm`.
        Um `split()` simples quebraria justamente os caminhos com espaco, que sao
        a regra nas pastas deste projeto.
        """
        paths: list[str] = []
        current = ""
        depth = 0
        for char in data:
            if char == "{":
                if depth == 0 and current.strip():
                    paths.append(current.strip())
                    current = ""
                depth += 1
                if depth == 1:
                    continue
            elif char == "}":
                depth -= 1
                if depth == 0:
                    paths.append(current)
                    current = ""
                    continue
            if depth > 0:
                current += char
            elif char.isspace():
                if current.strip():
                    paths.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            paths.append(current.strip())
        return [p for p in (path.strip() for path in paths) if p]

    # ------------------------------------------------------- direcao e lista

    def _counts(self) -> tuple[int, int, int]:
        models = sum(1 for p in self.paths if classify_path(p) == "p3m")
        animations = sum(1 for p in self.paths if classify_path(p) == "frm")
        gltfs = sum(1 for p in self.paths if classify_path(p) == "gltf")
        return models, animations, gltfs

    def _direction(self) -> str | None:
        models, animations, gltfs = self._counts()
        if gltfs:
            return Direction.TO_GC
        if models or animations:
            return Direction.TO_GLTF
        return None

    def _refresh_direction(self) -> None:
        """Atualiza o indicador de sentido conforme o conteudo da lista."""
        models, animations, gltfs = self._counts()
        direction = self._direction()

        if direction is None:
            self.direction_text.set(
                "Nenhum arquivo carregado — adicione .p3m/.frm para gerar .glb, "
                "ou .glb para gerar .p3m/.frm"
            )
        elif direction == Direction.TO_GC:
            extra = ""
            if models or animations:
                extra = (
                    f"  ({models + animations} arquivo(s) do jogo serao ignorados: "
                    f"nao se mistura os dois sentidos)"
                )
            self.direction_text.set(
                f"GLB -> P3M + FRM     {gltfs} arquivo(s) glTF{extra}"
            )
        else:
            if models:
                animacao_txt = (
                    f"{animations} animacao(oes)" if animations else "sem animacoes"
                )
                if self.merge_all.get():
                    destino = "um unico .glb"
                else:
                    destino = f"{models} arquivo(s) .glb"
                self.direction_text.set(
                    f"P3M + FRM -> GLB     {models} modelo(s), {animacao_txt}"
                    f"  ->  {destino}"
                )
            else:
                self.direction_text.set(
                    f"P3M + FRM -> GLB     {animations} animacao(oes), mas nenhum "
                    f"modelo .p3m — adicione o modelo"
                )

    def _refresh_list(self) -> None:
        self.file_list.delete(0, "end")
        labels = {"p3m": "modelo   ", "frm": "animacao ", "gltf": "glTF     "}
        for path in self.paths:
            kind = classify_path(path) or "?"
            self.file_list.insert(
                "end", f"  {labels.get(kind, 'outro    ')}  {os.path.basename(path)}"
            )
        # A dica de fundo aparece so com a lista vazia.
        if self.paths:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
        self._refresh_direction()

    def _add_paths(self, paths: list[str]) -> None:
        added = 0
        ignored = 0
        for path in paths:
            if not path:
                continue
            if classify_path(path) is None:
                ignored += 1
                continue
            if path not in self.paths:
                self.paths.append(path)
                added += 1
                # Lembra de onde veio o ultimo arquivo aceito, para o proximo
                # dialogo abrir ali. Vale para o arrastar e soltar tambem.
                folder = os.path.dirname(os.path.abspath(path))
                if os.path.isdir(folder):
                    self.last_dir = folder
        self._refresh_list()
        if added:
            self._log(f"{added} arquivo(s) adicionado(s). Total: {len(self.paths)}.")
            # A pasta lembrada mudou; garante que sobreviva a um fim anormal.
            self._save_settings_soon()
        if ignored:
            self._log(
                f"{ignored} arquivo(s) ignorado(s): extensao nao suportada.", "muted"
            )

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Escolher arquivos",
            initialdir=self._initial_dir(),
            filetypes=[
                ("Todos os suportados", "*.p3m *.frm *.glb *.gltf"),
                ("Modelos Grand Chase", "*.p3m"),
                ("Animacoes Grand Chase", "*.frm"),
                ("glTF binario", "*.glb"),
                ("glTF texto", "*.gltf"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        self._add_paths(list(paths))

    def _add_folder(self) -> None:
        directory = filedialog.askdirectory(
            title="Escolher pasta", initialdir=self._initial_dir()
        )
        if not directory:
            return
        models, animations, gltfs = collect_inputs([directory], recursive=True)
        self._add_paths(models + animations + gltfs)

    def _initial_dir(self) -> str:
        """Pasta onde os dialogos de arquivo devem abrir.

        A pasta lembrada pode ter sido apagada ou estar num disco desconectado
        desde a ultima execucao; nesse caso o tkinter ignora o pedido, mas
        conferimos aqui para nao insistir num caminho morto.
        """
        if self.last_dir and os.path.isdir(self.last_dir):
            return self.last_dir
        return os.path.expanduser("~")

    def _remove_selected(self) -> None:
        for index in reversed(self.file_list.curselection()):
            del self.paths[index]
        self._refresh_list()

    def _clear(self) -> None:
        self.paths.clear()
        self._refresh_list()

    # --------------------------------------------------------------- saida

    def _on_merge_toggled(self) -> None:
        self._refresh_direction()
        self._save_settings_soon()

    def _choose_output(self) -> None:
        current = self.output_dir.get()
        directory = filedialog.askdirectory(
            title="Escolher pasta de saida",
            initialdir=current if os.path.isdir(current) else self._initial_dir(),
        )
        if directory:
            self.output_dir.set(directory)
            self._save_settings_soon()

    def _open_output(self) -> None:
        directory = self.output_dir.get()
        if not os.path.isdir(directory):
            messagebox.showinfo(APP_TITLE, "A pasta de saida ainda nao existe.")
            return
        # Cada sistema tem seu proprio jeito de abrir o gerenciador de arquivos.
        try:
            if sys.platform == "win32":
                os.startfile(directory)  # type: ignore[attr-defined]
            else:
                import subprocess

                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, directory])
        except OSError as error:
            messagebox.showerror(
                APP_TITLE, f"Nao foi possivel abrir a pasta:\n{error}"
            )

    # ------------------------------------------------------------------- log

    def _log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or "")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------- conversao

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        direction = self._direction()
        if direction is None:
            messagebox.showwarning(
                APP_TITLE, "Adicione arquivos .p3m, .frm, .glb ou .gltf."
            )
            return

        models = [p for p in self.paths if classify_path(p) == "p3m"]
        animations = [p for p in self.paths if classify_path(p) == "frm"]
        gltfs = [p for p in self.paths if classify_path(p) == "gltf"]

        if direction == Direction.TO_GLTF and not models:
            messagebox.showwarning(
                APP_TITLE,
                "Ha animacoes .frm na lista, mas nenhum modelo .p3m.\n\n"
                "Uma animacao sozinha nao tem esqueleto para ser aplicada: "
                "adicione o .p3m correspondente.",
            )
            return

        output_dir = self.output_dir.get().strip()
        if not output_dir:
            messagebox.showwarning(APP_TITLE, "Escolha a pasta de saida.")
            return
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as error:
            messagebox.showerror(
                APP_TITLE, f"Nao foi possivel criar a pasta:\n{error}"
            )
            return

        options = ConvertOptions(
            embed_texture=self.with_texture.get(),
            extract_texture=self.with_texture.get(),
            texture_dirs=sorted(
                {os.path.dirname(os.path.abspath(p)) for p in self.paths}
            ),
        )

        self._cancel.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress_value.set(0.0)
        self._log("")
        self._log(f"{Direction.LABELS[direction]}  ->  {output_dir}", "muted")

        merge = direction == Direction.TO_GLTF and self.merge_all.get()
        self._worker = threading.Thread(
            target=self._run,
            args=(direction, models, animations, gltfs, output_dir, options, merge),
            daemon=True,
        )
        self._worker.start()

    def _cancel_conversion(self) -> None:
        self._cancel.set()
        self.status.set("Cancelando...")

    def _run(
        self,
        direction: str,
        models: list[str],
        animations: list[str],
        gltfs: list[str],
        output_dir: str,
        options: ConvertOptions,
        merge: bool = False,
    ) -> None:
        """Roda na thread de trabalho. Comunica-se apenas pela fila."""
        # Modo "tudo em um arquivo": um unico trabalho, um unico GLB.
        if merge:
            self._queue.put(("progress", 10.0))
            self._queue.put(
                ("status", f"Juntando {len(models)} modelo(s) em um .glb...")
            )
            name = _merged_output_name(models)
            output_path = os.path.join(output_dir, name)
            result = convert_merged(models, animations, output_path, options)
            self._queue.put(("progress", 100.0))
            if result.ok:
                self._queue.put(
                    ("log", (f"[ok] {len(models)} modelo(s) -> {name}", "ok"))
                )
                self._queue.put(("log", (f"     {result.summary}", "muted")))
                for warning in result.warnings:
                    self._queue.put(("log", (f"     aviso: {warning}", "aviso")))
                self._queue.put(("done", (1, 1)))
            else:
                self._queue.put(("log", (f"[ERRO] {result.error}", "erro")))
                self._queue.put(("done", (0, 1)))
            return

        items = gltfs if direction == Direction.TO_GC else models
        total = len(items)
        succeeded = 0

        # Le cada .frm uma unica vez, mesmo com centenas de modelos.
        index = AnimationIndex(animations) if direction == Direction.TO_GLTF else None
        if index is not None:
            for path, reason in index.unreadable:
                self._queue.put(
                    (
                        "log",
                        (
                            f"     ignorando {os.path.basename(path)}: {reason}",
                            "aviso",
                        ),
                    )
                )
            if len(index):
                self._queue.put(
                    (
                        "log",
                        (
                            f"     {len(index)} animacao(oes) disponivel(is), "
                            f"com {', '.join(str(c) for c in index.bone_counts)} osso(s)",
                            "muted",
                        ),
                    )
                )

        for position, path in enumerate(items):
            if self._cancel.is_set():
                self._queue.put(("status", "Cancelado."))
                break

            self._queue.put(("progress", (position / total) * 100.0))
            self._queue.put(
                ("status", f"[{position + 1}/{total}] {os.path.basename(path)}")
            )

            extra_warnings: list[str] = []
            if direction == Direction.TO_GC:
                result = convert_to_gc(path, output_dir, options)
            else:
                chosen: list[str] = []
                if index is not None and len(index):
                    chosen, extra_warnings = index.select_for(
                        path, options.match_animations_by_bones
                    )
                stem = os.path.splitext(os.path.basename(path))[0]
                result = convert_model(
                    path, os.path.join(output_dir, stem + ".glb"), chosen, options
                )

            if result.ok:
                succeeded += 1
                produced = ", ".join(
                    os.path.basename(p) for p in result.outputs[:3]
                )
                if len(result.outputs) > 3:
                    produced += f" (+{len(result.outputs) - 3})"
                self._queue.put(
                    ("log", (f"[ok] {os.path.basename(path)} -> {produced}", "ok"))
                )
                self._queue.put(("log", (f"     {result.summary}", "muted")))
                for warning in extra_warnings + result.warnings:
                    self._queue.put(("log", (f"     aviso: {warning}", "aviso")))
            else:
                self._queue.put(
                    (
                        "log",
                        (
                            f"[ERRO] {os.path.basename(path)}: {result.error}",
                            "erro",
                        ),
                    )
                )

        self._queue.put(("progress", 100.0))
        self._queue.put(("done", (succeeded, total)))

    def _drain_queue(self) -> None:
        """Consome as mensagens da thread de trabalho na thread da interface."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    text, tag = payload
                    self._log(text, tag)
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "progress":
                    self.progress_value.set(payload)
                elif kind == "done":
                    succeeded, total = payload
                    self.status.set(f"Concluido: {succeeded}/{total}.")
                    self._log(
                        f"Concluido: {succeeded}/{total} convertido(s).", "ok"
                    )
                    self.convert_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    # A lista e limpa ao terminar: o proximo trabalho comeca
                    # limpo, sem risco de reconverter por engano.
                    self._clear()
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)


def main(preload: list[str] | None = None) -> int:
    """Abre a janela.

    `preload` recebe caminhos para ja entrar carregados na lista, usado quando o
    usuario arrasta arquivos sobre o icone do programa.
    """
    # A raiz precisa ser a do TkinterDnD para o arrastar e soltar funcionar; ela
    # e uma subclasse de tk.Tk que carrega a extensao Tcl. Sem o pacote, cai na
    # raiz normal e a janela funciona igual, so sem o recurso.
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:  # noqa: BLE001 - extensao presente mas sem carregar
            root = tk.Tk()
    else:
        root = tk.Tk()

    apply_dark_theme(root)
    settings = Settings.load()
    app = ConverterApp(root, settings=settings)
    if not DND_AVAILABLE:
        app._log(
            "Arrastar e soltar indisponivel: instale com "
            "'pip install tkinterdnd2'. Os botoes de adicionar funcionam normalmente.",
            "muted",
        )

    # Diz onde as preferencias moram. Importa quando a pasta do executavel e
    # somente leitura e o arquivo foi para a pasta de configuracao do sistema:
    # sem esta linha o usuario procuraria um gc3d.ini que nunca apareceu.
    beside = os.path.join(executable_dir(), CONFIG_NAME)
    if os.path.abspath(settings.path) == os.path.abspath(beside):
        app._log(f"Configuracoes em {settings.path}", "muted")
    else:
        app._log(
            f"A pasta do programa nao aceita gravacao; configuracoes em "
            f"{settings.path}",
            "aviso",
        )

    if preload:
        app._add_paths([os.path.abspath(path) for path in preload])

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
