#!/usr/bin/env python3
"""Interface grafica do Grand Chase 3D Importer.

Usa apenas tkinter, que vem junto com o Python no Windows e esta disponivel em
qualquer distribuicao Linux. Isso mantem o programa com zero dependencias e faz
o executavel empacotado ficar pequeno.

A conversao roda em uma thread separada para a janela nao congelar; a thread
nunca toca em widgets diretamente, apenas empilha mensagens numa fila que a
thread da interface consome a cada 100 ms. Esse e o unico jeito seguro de
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
    __version__,
    collect_inputs,
    convert_model,
    find_animations_for_model,
)

APP_TITLE = f"Grand Chase 3D Importer {__version__}"


class ConverterApp(ttk.Frame):
    """Janela principal."""

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=10)
        self.master.title(APP_TITLE)
        self.master.minsize(760, 560)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        # Estado
        self.model_paths: list[str] = []
        self.animation_paths: list[str] = []
        self.output_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "gc3d_saida"))
        self.embed_texture = tk.BooleanVar(value=True)
        self.auto_animations = tk.BooleanVar(value=True)
        self.double_sided = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Pronto.")
        self.progress_value = tk.DoubleVar(value=0.0)

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()

        self._build_ui()
        self.after(100, self._drain_queue)

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # --- Modelos
        models_frame = ttk.LabelFrame(self, text="Modelos (.p3m)", padding=8)
        models_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        models_frame.columnconfigure(0, weight=1)

        self.models_list = tk.Listbox(models_frame, height=5, selectmode=tk.EXTENDED)
        self.models_list.grid(row=0, column=0, sticky="ew")
        models_scroll = ttk.Scrollbar(
            models_frame, orient="vertical", command=self.models_list.yview
        )
        models_scroll.grid(row=0, column=1, sticky="ns")
        self.models_list.configure(yscrollcommand=models_scroll.set)

        model_buttons = ttk.Frame(models_frame)
        model_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(model_buttons, text="Adicionar arquivos...", command=self._add_models).pack(
            side="left"
        )
        ttk.Button(model_buttons, text="Adicionar pasta...", command=self._add_model_dir).pack(
            side="left", padx=4
        )
        ttk.Button(model_buttons, text="Remover selecionados", command=self._remove_models).pack(
            side="left", padx=4
        )
        ttk.Button(model_buttons, text="Limpar", command=self._clear_models).pack(side="left")

        # --- Animacoes
        anim_frame = ttk.LabelFrame(self, text="Animacoes (.frm)", padding=8)
        anim_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        anim_frame.columnconfigure(0, weight=1)

        self.anims_list = tk.Listbox(anim_frame, height=4, selectmode=tk.EXTENDED)
        self.anims_list.grid(row=0, column=0, sticky="ew")
        anims_scroll = ttk.Scrollbar(
            anim_frame, orient="vertical", command=self.anims_list.yview
        )
        anims_scroll.grid(row=0, column=1, sticky="ns")
        self.anims_list.configure(yscrollcommand=anims_scroll.set)

        anim_buttons = ttk.Frame(anim_frame)
        anim_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(anim_buttons, text="Adicionar arquivos...", command=self._add_anims).pack(
            side="left"
        )
        ttk.Button(anim_buttons, text="Adicionar pasta...", command=self._add_anim_dir).pack(
            side="left", padx=4
        )
        ttk.Button(anim_buttons, text="Limpar", command=self._clear_anims).pack(side="left")
        ttk.Checkbutton(
            anim_buttons,
            text="Casar automaticamente por numero de ossos",
            variable=self.auto_animations,
        ).pack(side="left", padx=(12, 0))

        # --- Saida e opcoes
        options_frame = ttk.LabelFrame(self, text="Saida e opcoes", padding=8)
        options_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        options_frame.columnconfigure(1, weight=1)

        ttk.Label(options_frame, text="Pasta de saida:").grid(row=0, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.output_dir).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(options_frame, text="Escolher...", command=self._choose_output).grid(
            row=0, column=2
        )

        checks = ttk.Frame(options_frame)
        checks.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            checks, text="Embutir textura (.dds/.png)", variable=self.embed_texture
        ).pack(side="left")
        ttk.Checkbutton(
            checks, text="Faces dos dois lados", variable=self.double_sided
        ).pack(side="left", padx=(12, 0))

        # --- Log
        log_frame = ttk.LabelFrame(self, text="Registro", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.tag_configure("erro", foreground="#b00020")
        self.log.tag_configure("aviso", foreground="#a06000")
        self.log.tag_configure("ok", foreground="#006400")

        # --- Rodape
        footer = ttk.Frame(self)
        footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(1, weight=1)

        self.convert_button = ttk.Button(
            footer, text="Converter", command=self._start_conversion
        )
        self.convert_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(
            footer, text="Cancelar", command=self._cancel_conversion, state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(footer, text="Abrir pasta de saida", command=self._open_output).grid(
            row=0, column=2, padx=6
        )

        self.progress = ttk.Progressbar(
            footer, variable=self.progress_value, maximum=100.0
        )
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(footer, textvariable=self.status).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

    # ------------------------------------------------------- selecao de arquivos

    def _add_models(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Escolher modelos P3M",
            filetypes=[("Modelos Grand Chase", "*.p3m"), ("Todos os arquivos", "*.*")],
        )
        self._append_models(list(paths))

    def _add_model_dir(self) -> None:
        directory = filedialog.askdirectory(title="Escolher pasta com modelos P3M")
        if not directory:
            return
        models, _ = collect_inputs([directory], recursive=True)
        self._append_models(models)

    def _append_models(self, paths: list[str]) -> None:
        added = 0
        for path in paths:
            if path and path not in self.model_paths:
                self.model_paths.append(path)
                self.models_list.insert("end", path)
                added += 1
        if added:
            self._log(f"{added} modelo(s) adicionado(s). Total: {len(self.model_paths)}.")

    def _remove_models(self) -> None:
        for index in reversed(self.models_list.curselection()):
            self.models_list.delete(index)
            del self.model_paths[index]

    def _clear_models(self) -> None:
        self.models_list.delete(0, "end")
        self.model_paths.clear()

    def _add_anims(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Escolher animacoes FRM",
            filetypes=[("Animacoes Grand Chase", "*.frm"), ("Todos os arquivos", "*.*")],
        )
        self._append_anims(list(paths))

    def _add_anim_dir(self) -> None:
        directory = filedialog.askdirectory(title="Escolher pasta com animacoes FRM")
        if not directory:
            return
        _, animations = collect_inputs([directory], recursive=True)
        self._append_anims(animations)

    def _append_anims(self, paths: list[str]) -> None:
        added = 0
        for path in paths:
            if path and path not in self.animation_paths:
                self.animation_paths.append(path)
                self.anims_list.insert("end", path)
                added += 1
        if added:
            self._log(
                f"{added} animacao(oes) adicionada(s). Total: {len(self.animation_paths)}."
            )

    def _clear_anims(self) -> None:
        self.anims_list.delete(0, "end")
        self.animation_paths.clear()

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
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", directory])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", directory])
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Nao foi possivel abrir a pasta:\n{error}")

    # ------------------------------------------------------------------- log

    def _log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or "")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------- conversao

    def _start_conversion(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        if not self.model_paths:
            messagebox.showwarning(APP_TITLE, "Adicione pelo menos um modelo .p3m.")
            return

        output_dir = self.output_dir.get().strip()
        if not output_dir:
            messagebox.showwarning(APP_TITLE, "Escolha a pasta de saida.")
            return
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Nao foi possivel criar a pasta:\n{error}")
            return

        options = ConvertOptions(
            embed_texture=self.embed_texture.get(),
            double_sided=self.double_sided.get(),
            texture_dirs=sorted(
                {os.path.dirname(os.path.abspath(p)) for p in self.model_paths}
            ),
        )

        self._cancel.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress_value.set(0.0)
        self._log("")
        self._log(f"Convertendo {len(self.model_paths)} modelo(s) para {output_dir}")

        self._worker = threading.Thread(
            target=self._run_conversion,
            args=(list(self.model_paths), list(self.animation_paths), output_dir, options),
            daemon=True,
        )
        self._worker.start()

    def _cancel_conversion(self) -> None:
        self._cancel.set()
        self.status.set("Cancelando...")

    def _run_conversion(
        self,
        models: list[str],
        animations: list[str],
        output_dir: str,
        options: ConvertOptions,
    ) -> None:
        """Roda na thread de trabalho. Comunica-se apenas pela fila."""
        auto = self.auto_animations.get()
        # Agrupa as animacoes escolhidas pelo numero de ossos, uma vez, para nao
        # reabrir os mesmos FRM para cada modelo.
        by_bone_count: dict[int, list[str]] = {}
        if animations and auto:
            from gc3d.formats import frm as frm_format

            for path in animations:
                try:
                    count = frm_format.load_frm(path).num_bones
                except Exception:  # noqa: BLE001 - arquivo ruim so e ignorado
                    continue
                by_bone_count.setdefault(count, []).append(path)

        total = len(models)
        succeeded = 0
        for index, model_path in enumerate(models):
            if self._cancel.is_set():
                self._queue.put(("status", "Cancelado pelo usuario."))
                break

            self._queue.put(("progress", (index / total) * 100.0))
            self._queue.put(("status", f"[{index + 1}/{total}] {os.path.basename(model_path)}"))

            chosen = animations
            if animations and auto:
                try:
                    from gc3d.formats import p3m as p3m_format

                    bones = p3m_format.load_p3m(model_path).num_angle_bones
                    chosen = by_bone_count.get(bones, [])
                except Exception:  # noqa: BLE001
                    chosen = []
            elif not animations:
                chosen = []

            stem = os.path.splitext(os.path.basename(model_path))[0]
            output_path = os.path.join(output_dir, stem + ".glb")
            result = convert_model(model_path, output_path, chosen, options)

            if result.ok:
                succeeded += 1
                message = (
                    f"[ok] {os.path.basename(model_path)} -> {stem}.glb  "
                    f"({result.summary})"
                )
                self._queue.put(("log", (message, "ok")))
                if result.texture_used:
                    self._queue.put(
                        (
                            "log",
                            (
                                f"     textura: {os.path.basename(result.texture_used)}",
                                None,
                            ),
                        )
                    )
                for warning in result.warnings:
                    self._queue.put(("log", (f"     aviso: {warning}", "aviso")))
            else:
                self._queue.put(
                    ("log", (f"[ERRO] {os.path.basename(model_path)}: {result.error}", "erro"))
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
                    self.status.set(f"Concluido: {succeeded}/{total} convertido(s).")
                    self._log(f"Concluido: {succeeded}/{total} convertido(s).", "ok")
                    self.convert_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)


def main() -> int:
    root = tk.Tk()
    # O tema "clam" existe em todas as plataformas e evita o visual datado do
    # tema padrao do tkinter no Linux.
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
