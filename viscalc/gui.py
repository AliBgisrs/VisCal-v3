"""Two-panel Tkinter GUI:
 - LEFT panel: live log + status + progress bar
 - RIGHT panel: configuration controls (folders, files, VI selection, Run)
"""
from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from tkinter import (
    Tk, StringVar, BooleanVar, DoubleVar, Listbox, EXTENDED,
    filedialog, messagebox, END,
)
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .indices import ALL_VI_NAMES
from .pipeline import PipelineConfig, run_pipeline


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("VI Calculator - Developed by Ali Bazrafkan")
        root.geometry("1180x720")
        root.minsize(900, 560)

        self.raster_var = StringVar()
        self.shp_var = StringVar()
        self.excel_var = StringVar()
        self.out_var = StringVar()
        self.save_vi_var = BooleanVar(value=False)
        self.pct_var = DoubleVar(value=0.0)
        self.status_var = StringVar(value="Idle")

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._pct_q: "queue.Queue[float]" = queue.Queue()
        self._status_q: "queue.Queue[str]" = queue.Queue()

        self._build_layout()
        self._poll_queues()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=4)

        self._build_left(left)
        self._build_right(right)

    # ------------------------------------------------------------------
    def _build_left(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Log")
        box.pack(fill="both", expand=True, padx=4, pady=4)

        self.log_box = ScrolledText(box, wrap="word", height=20)
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        prog_frame = ttk.Frame(parent)
        prog_frame.pack(fill="x", padx=4, pady=(0, 4))

        ttk.Label(prog_frame, textvariable=self.status_var, foreground="#222").pack(
            anchor="w", padx=2, pady=(2, 2)
        )
        self.progress = ttk.Progressbar(
            prog_frame,
            mode="determinate",
            variable=self.pct_var,
            maximum=100.0,
        )
        self.progress.pack(fill="x", padx=2, pady=2)

        self.pct_label_var = StringVar(value="0%")
        ttk.Label(prog_frame, textvariable=self.pct_label_var, foreground="#444").pack(
            anchor="e", padx=2, pady=(0, 2)
        )

    # ------------------------------------------------------------------
    def _build_right(self, parent: ttk.Frame) -> None:
        cfg = ttk.LabelFrame(parent, text="Inputs")
        cfg.pack(fill="x", expand=False, padx=4, pady=4)

        self._row(cfg, 0, "Raster folder:", self.raster_var, self._pick_raster)
        self._row(cfg, 1, "Shapefile (.shp):", self.shp_var, self._pick_shp)
        self._row(cfg, 2, "Field data (.xlsx):", self.excel_var, self._pick_excel)
        self._row(cfg, 3, "Output folder:", self.out_var, self._pick_out)
        cfg.columnconfigure(1, weight=1)

        vi_box = ttk.LabelFrame(parent, text="Export VI rasters")
        vi_box.pack(fill="both", expand=True, padx=4, pady=4)

        ttk.Checkbutton(
            vi_box,
            text="Save selected VIs as GeoTIFFs",
            variable=self.save_vi_var,
            command=self._toggle_vi_list,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(vi_box, text="(Ctrl/Shift-click to multi-select)").grid(
            row=0, column=1, sticky="e", padx=6
        )

        self.vi_list = Listbox(vi_box, selectmode=EXTENDED, height=10, exportselection=False)
        for name in ALL_VI_NAMES:
            self.vi_list.insert(END, name)
        self.vi_list.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)

        sb = ttk.Scrollbar(vi_box, orient="vertical", command=self.vi_list.yview)
        sb.grid(row=1, column=2, sticky="ns", pady=4)
        self.vi_list.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(vi_box)
        btns.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        ttk.Button(btns, text="Select all", command=self._select_all_vis).pack(side="left", padx=4)
        ttk.Button(btns, text="Clear", command=self._clear_vis).pack(side="left", padx=4)

        vi_box.columnconfigure(0, weight=1)
        vi_box.rowconfigure(1, weight=1)
        self._toggle_vi_list()

        action = ttk.Frame(parent)
        action.pack(fill="x", padx=4, pady=4)
        self.run_btn = ttk.Button(action, text="Run", command=self._run_clicked)
        self.run_btn.pack(fill="x", padx=2, pady=4)

        credit = ttk.Label(parent, text="Developed by Ali Bazrafkan", foreground="#666")
        credit.pack(anchor="e", padx=6, pady=(0, 4))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _row(self, parent, row, label, var, cmd):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(parent, text="Browse...", command=cmd).grid(row=row, column=2, padx=6, pady=6)

    def _toggle_vi_list(self) -> None:
        state = "normal" if self.save_vi_var.get() else "disabled"
        self.vi_list.configure(state=state)

    def _select_all_vis(self) -> None:
        self.vi_list.select_set(0, END)

    def _clear_vis(self) -> None:
        self.vi_list.select_clear(0, END)

    def _selected_vis(self) -> set[str]:
        return {self.vi_list.get(i) for i in self.vi_list.curselection()}

    def _pick_raster(self) -> None:
        p = filedialog.askdirectory(title="Select folder of multispectral rasters")
        if p:
            self.raster_var.set(p)

    def _pick_shp(self) -> None:
        p = filedialog.askopenfilename(
            title="Select shapefile",
            filetypes=[("Shapefile", "*.shp"), ("All files", "*.*")],
        )
        if p:
            self.shp_var.set(p)

    def _pick_excel(self) -> None:
        p = filedialog.askopenfilename(
            title="Select field-data Excel file",
            filetypes=[("Excel", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if p:
            self.excel_var.set(p)

    def _pick_out(self) -> None:
        p = filedialog.askdirectory(title="Select output folder")
        if p:
            self.out_var.set(p)

    def _append_log(self, msg: str) -> None:
        self.log_box.insert(END, msg + "\n")
        self.log_box.see(END)

    def _poll_queues(self) -> None:
        while not self._log_q.empty():
            self._append_log(self._log_q.get_nowait())
        while not self._pct_q.empty():
            v = self._pct_q.get_nowait()
            self.pct_var.set(v)
            self.pct_label_var.set(f"{v:.1f}%")
        while not self._status_q.empty():
            self.status_var.set(self._status_q.get_nowait())
        self.root.after(100, self._poll_queues)

    def _validate(self) -> bool:
        missing = []
        if not self.raster_var.get():
            missing.append("raster folder")
        if not self.shp_var.get():
            missing.append("shapefile")
        if not self.excel_var.get():
            missing.append("field-data Excel")
        if not self.out_var.get():
            missing.append("output folder")
        if missing:
            messagebox.showerror("Missing input", "Please pick: " + ", ".join(missing))
            return False
        return True

    def _run_clicked(self) -> None:
        if not self._validate():
            return
        self.run_btn.state(["disabled"])
        self.log_box.delete("1.0", END)
        self.pct_var.set(0.0)
        self.pct_label_var.set("0%")
        self.status_var.set("Starting...")

        save_flag = self.save_vi_var.get()
        selected = self._selected_vis() if save_flag else set()
        if save_flag and not selected:
            messagebox.showwarning(
                "No VIs selected",
                "You enabled VI raster export but didn't select any VIs. "
                "No rasters will be saved.",
            )

        cfg = PipelineConfig(
            raster_folder=Path(self.raster_var.get()),
            shapefile=Path(self.shp_var.get()),
            field_excel=Path(self.excel_var.get()),
            output_folder=Path(self.out_var.get()),
            save_vi_rasters=save_flag,
            vis_to_save=selected if save_flag else None,
            progress=lambda m: self._log_q.put(m),
            progress_pct=lambda v: self._pct_q.put(v),
            status=lambda s: self._status_q.put(s),
        )

        def worker():
            try:
                out = run_pipeline(cfg)
                self._log_q.put(f"\nFinished. Output: {out}")
                self.root.after(0, lambda: messagebox.showinfo("Done", f"Wrote: {out}"))
            except Exception as e:
                tb = traceback.format_exc()
                self._log_q.put("\nERROR:\n" + tb)
                self._status_q.put("Error")
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.root.after(0, lambda: self.run_btn.state(["!disabled"]))

        threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
