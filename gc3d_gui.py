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
    ConvertOptions,
    Direction,
    __version__,
    classify_path,
    collect_inputs,
    convert_model,
    convert_to_gc,
)

APP_TITLE = f"Grand Chase 3D Importer {__version__}"


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

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=14)
        self.master.title(APP_TITLE)
        self.master.minsize(820, 620)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        #: Caminhos carregados, em ordem de insercao.
        self.paths: list[str] = []
        self.output_dir = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "gc3d_saida")
        )
        self.direction_text = tk.StringVar()
        self.status = tk.StringVar(value="Pronto.")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.with_texture = tk.BooleanVar(value=True)

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()

        self._build_ui()
        self._refresh_direction()
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
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
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

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
                self.direction_text.set(
                    f"P3M + FRM -> GLB     {models} modelo(s), "
                    f"{animations} animacao(oes)"
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
        self._refresh_list()
        if added:
            self._log(f"{added} arquivo(s) adicionado(s). Total: {len(self.paths)}.")
        if ignored:
            self._log(
                f"{ignored} arquivo(s) ignorado(s): extensao nao suportada.", "muted"
            )

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Escolher arquivos",
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
        directory = filedialog.askdirectory(title="Escolher pasta")
        if not directory:
            return
        models, animations, gltfs = collect_inputs([directory], recursive=True)
        self._add_paths(models + animations + gltfs)

    def _remove_selected(self) -> None:
        for index in reversed(self.file_list.curselection()):
            del self.paths[index]
        self._refresh_list()

    def _clear(self) -> None:
        self.paths.clear()
        self._refresh_list()

    # --------------------------------------------------------------- saida

    def _choose_output(self) -> None:
        directory = filedialog.askdirectory(title="Escolher pasta de saida")
        if directory:
            self.output_dir.set(directory)

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
        self._log(
            f"{Direction.LABELS[direction]}  ->  {output_dir}", "muted"
        )

        self._worker = threading.Thread(
            target=self._run,
            args=(direction, models, animations, gltfs, output_dir, options),
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
    ) -> None:
        """Roda na thread de trabalho. Comunica-se apenas pela fila."""
        if direction == Direction.TO_GC:
            items = gltfs
        else:
            items = models

        total = len(items)
        succeeded = 0

        # Agrupa as animacoes por numero de ossos uma unica vez, para nao
        # reabrir os mesmos FRM a cada modelo.
        by_bone_count: dict[int, list[str]] = {}
        if direction == Direction.TO_GLTF and animations:
            from gc3d.formats import frm as frm_format

            for path in animations:
                try:
                    count = frm_format.load_frm(path).num_bones
                except Exception:  # noqa: BLE001 - arquivo ruim so e ignorado
                    self._queue.put(
                        (
                            "log",
                            (
                                f"     ignorando {os.path.basename(path)}: "
                                f"nao foi possivel ler",
                                "aviso",
                            ),
                        )
                    )
                    continue
                by_bone_count.setdefault(count, []).append(path)

        for index, path in enumerate(items):
            if self._cancel.is_set():
                self._queue.put(("status", "Cancelado."))
                break

            self._queue.put(("progress", (index / total) * 100.0))
            self._queue.put(
                ("status", f"[{index + 1}/{total}] {os.path.basename(path)}")
            )

            if direction == Direction.TO_GC:
                result = convert_to_gc(path, output_dir, options)
            else:
                chosen: list[str] = []
                if animations:
                    try:
                        from gc3d.formats import p3m as p3m_format

                        bones = p3m_format.load_p3m(path).num_angle_bones
                        chosen = by_bone_count.get(bones, [])
                    except Exception:  # noqa: BLE001
                        chosen = []
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
                    (
                        "log",
                        (
                            f"[ok] {os.path.basename(path)} -> {produced}",
                            "ok",
                        ),
                    )
                )
                self._queue.put(("log", (f"     {result.summary}", "muted")))
                for warning in result.warnings:
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


def main() -> int:
    root = tk.Tk()
    apply_dark_theme(root)
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
