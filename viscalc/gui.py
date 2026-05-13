"""Tkinter GUI: pick the three inputs + output folder, run the pipeline."""
from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from tkinter import Tk, StringVar, BooleanVar, filedialog, messagebox, END
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .pipeline import PipelineConfig, run_pipeline


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("VI Calculator")
        root.geometry("760x540")

        self.raster_var = StringVar()
        self.shp_var = StringVar()
        self.excel_var = StringVar()
        self.out_var = StringVar()
        self.save_vi_var = BooleanVar(value=False)

        self._log_q: "queue.Queue[str]" = queue.Queue()

        self._build_form()
        self._poll_log()

    def _build_form(self) -> None:
        pad = {"padx": 8, "pady": 6}
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True, **pad)

        self._row(frm, 0, "Raster folder:", self.raster_var, self._pick_raster, browse_dir=True)
        self._row(frm, 1, "Shapefile (.shp):", self.shp_var, self._pick_shp)
        self._row(frm, 2, "Field data (.xlsx):", self.excel_var, self._pick_excel)
        self._row(frm, 3, "Output folder:", self.out_var, self._pick_out, browse_dir=True)

        opts = ttk.Frame(frm)
        opts.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(
            opts, text="Also save per-VI GeoTIFFs", variable=self.save_vi_var
        ).pack(side="left")

        self.run_btn = ttk.Button(frm, text="Run", command=self._run_clicked)
        self.run_btn.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(frm, text="Log:").grid(row=6, column=0, sticky="w", **pad)
        self.log_box = ScrolledText(frm, height=18, wrap="word")
        self.log_box.grid(row=7, column=0, columnspan=3, sticky="nsew", **pad)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(7, weight=1)

    def _row(self, parent, row, label, var, cmd, browse_dir=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(parent, text="Browse...", command=cmd).grid(row=row, column=2, padx=8, pady=6)

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

    def _poll_log(self) -> None:
        while not self._log_q.empty():
            self._append_log(self._log_q.get_nowait())
        self.root.after(150, self._poll_log)

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

        cfg = PipelineConfig(
            raster_folder=Path(self.raster_var.get()),
            shapefile=Path(self.shp_var.get()),
            field_excel=Path(self.excel_var.get()),
            output_folder=Path(self.out_var.get()),
            save_vi_rasters=self.save_vi_var.get(),
            progress=lambda m: self._log_q.put(m),
        )

        def worker():
            try:
                out = run_pipeline(cfg)
                self._log_q.put(f"\nFinished. Output: {out}")
                self.root.after(0, lambda: messagebox.showinfo("Done", f"Wrote: {out}"))
            except Exception as e:
                tb = traceback.format_exc()
                self._log_q.put("\nERROR:\n" + tb)
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
