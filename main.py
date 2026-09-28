"""Manga EPUB <-> PNG — tkinter GUI with two modes."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import (
    ConvertResult,
    convert_epub,
    convert_folder_to_epub,
    epub_path_for,
    output_dir_for,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("漫画 EPUB / PNG 互转")
        self.minsize(560, 340)
        self.resizable(True, False)

        # EPUB → PNG
        self.epub_path = tk.StringVar()
        self.epub_parent_dir = tk.StringVar()
        self.epub_preview = tk.StringVar(value="（请先选择 EPUB 与输出目录）")

        # PNG → EPUB
        self.folder_path = tk.StringVar()
        self.folder_parent_dir = tk.StringVar()
        self.folder_preview = tk.StringVar(value="（请先选择图片文件夹与输出目录）")

        self.status_text = tk.StringVar(value="就绪")
        self._busy = False
        self._last_mode = "epub_to_png"

        self._build_ui()
        self.epub_path.trace_add("write", lambda *_: self._refresh_epub_preview())
        self.epub_parent_dir.trace_add("write", lambda *_: self._refresh_epub_preview())
        self.folder_path.trace_add("write", lambda *_: self._refresh_folder_preview())
        self.folder_parent_dir.trace_add(
            "write", lambda *_: self._refresh_folder_preview()
        )

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        tab_epub = ttk.Frame(self.notebook, padding=8)
        tab_folder = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_epub, text="EPUB → PNG")
        self.notebook.add(tab_folder, text="PNG → EPUB")

        # --- EPUB → PNG tab ---
        row1 = ttk.Frame(tab_epub)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="EPUB 文件：", width=12).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.epub_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(row1, text="浏览…", command=self._pick_epub).pack(side=tk.LEFT)

        row2 = ttk.Frame(tab_epub)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="输出目录：", width=12).pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.epub_parent_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(row2, text="浏览…", command=self._pick_epub_parent).pack(
            side=tk.LEFT
        )

        row3 = ttk.Frame(tab_epub)
        row3.pack(fill=tk.X, **pad)
        ttk.Label(row3, text="将保存到：", width=12).pack(side=tk.LEFT)
        ttk.Label(row3, textvariable=self.epub_preview, wraplength=420).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        ttk.Label(
            tab_epub,
            text="说明：按阅读顺序导出为 1.png、2.png…；输出文件夹名与 EPUB 文件名相同。",
            foreground="#555",
        ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        # --- PNG → EPUB tab ---
        f1 = ttk.Frame(tab_folder)
        f1.pack(fill=tk.X, **pad)
        ttk.Label(f1, text="图片文件夹：", width=12).pack(side=tk.LEFT)
        ttk.Entry(f1, textvariable=self.folder_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(f1, text="浏览…", command=self._pick_folder).pack(side=tk.LEFT)

        f2 = ttk.Frame(tab_folder)
        f2.pack(fill=tk.X, **pad)
        ttk.Label(f2, text="输出目录：", width=12).pack(side=tk.LEFT)
        ttk.Entry(f2, textvariable=self.folder_parent_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(f2, text="浏览…", command=self._pick_folder_parent).pack(
            side=tk.LEFT
        )

        f3 = ttk.Frame(tab_folder)
        f3.pack(fill=tk.X, **pad)
        ttk.Label(f3, text="将保存到：", width=12).pack(side=tk.LEFT)
        ttk.Label(f3, textvariable=self.folder_preview, wraplength=420).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        ttk.Label(
            tab_folder,
            text="说明：只认连续的 1.png、2.png…（缺页会报错）；书名与输出文件名取文件夹名。",
            foreground="#555",
        ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        # Shared progress + action
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, **pad)
        ttk.Label(root, textvariable=self.status_text).pack(anchor=tk.W, **pad)

        row4 = ttk.Frame(root)
        row4.pack(fill=tk.X, **pad)
        self.start_btn = ttk.Button(row4, text="开始转换", command=self._start)
        self.start_btn.pack(side=tk.RIGHT)

    def _current_mode(self) -> str:
        idx = self.notebook.index(self.notebook.select())
        return "epub_to_png" if idx == 0 else "png_to_epub"

    def _pick_epub(self) -> None:
        path = filedialog.askopenfilename(
            title="选择漫画 EPUB",
            filetypes=[("EPUB 电子书", "*.epub"), ("所有文件", "*.*")],
        )
        if path:
            self.epub_path.set(path)
            if not self.epub_parent_dir.get():
                self.epub_parent_dir.set(str(Path(path).parent))

    def _pick_epub_parent(self) -> None:
        path = filedialog.askdirectory(title="选择输出父目录")
        if path:
            self.epub_parent_dir.set(path)

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(title="选择包含 1.png、2.png… 的文件夹")
        if path:
            self.folder_path.set(path)
            if not self.folder_parent_dir.get():
                self.folder_parent_dir.set(str(Path(path).parent))

    def _pick_folder_parent(self) -> None:
        path = filedialog.askdirectory(title="选择输出父目录")
        if path:
            self.folder_parent_dir.set(path)

    def _refresh_epub_preview(self) -> None:
        epub = self.epub_path.get().strip()
        parent = self.epub_parent_dir.get().strip()
        if epub and parent:
            try:
                self.epub_preview.set(str(output_dir_for(Path(epub), Path(parent))))
                return
            except Exception:  # noqa: BLE001
                pass
        self.epub_preview.set("（请先选择 EPUB 与输出目录）")

    def _refresh_folder_preview(self) -> None:
        folder = self.folder_path.get().strip()
        parent = self.folder_parent_dir.get().strip()
        if folder and parent:
            try:
                self.folder_preview.set(
                    str(epub_path_for(Path(folder), Path(parent)))
                )
                return
            except Exception:  # noqa: BLE001
                pass
        self.folder_preview.set("（请先选择图片文件夹与输出目录）")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.start_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)

    def _start(self) -> None:
        if self._busy:
            return
        mode = self._current_mode()
        self._last_mode = mode
        if mode == "epub_to_png":
            self._start_epub_to_png()
        else:
            self._start_png_to_epub()

    def _start_epub_to_png(self) -> None:
        epub = self.epub_path.get().strip()
        parent = self.epub_parent_dir.get().strip()
        if not epub:
            messagebox.showwarning("提示", "请先选择 EPUB 文件。")
            return
        if not parent:
            messagebox.showwarning("提示", "请先选择输出目录。")
            return

        epub_path = Path(epub)
        parent_dir = Path(parent)
        if not epub_path.is_file():
            messagebox.showerror("错误", f"找不到文件：\n{epub_path}")
            return
        if not parent_dir.is_dir():
            messagebox.showerror("错误", f"输出目录不存在：\n{parent_dir}")
            return

        out_dir = output_dir_for(epub_path, parent_dir)
        overwrite = False
        if out_dir.exists():
            ok = messagebox.askyesno(
                "确认覆盖",
                f"输出文件夹已存在：\n{out_dir}\n\n是否删除后重新导出？",
            )
            if not ok:
                return
            overwrite = True

        self._set_busy(True)
        self.progress["value"] = 0
        self.status_text.set("开始转换…")
        threading.Thread(
            target=self._run_epub_to_png,
            args=(epub_path, parent_dir, overwrite),
            daemon=True,
        ).start()

    def _start_png_to_epub(self) -> None:
        folder = self.folder_path.get().strip()
        parent = self.folder_parent_dir.get().strip()
        if not folder:
            messagebox.showwarning("提示", "请先选择图片文件夹。")
            return
        if not parent:
            messagebox.showwarning("提示", "请先选择输出目录。")
            return

        folder_path = Path(folder)
        parent_dir = Path(parent)
        if not folder_path.is_dir():
            messagebox.showerror("错误", f"图片文件夹不存在：\n{folder_path}")
            return
        if not parent_dir.is_dir():
            messagebox.showerror("错误", f"输出目录不存在：\n{parent_dir}")
            return

        out_path = epub_path_for(folder_path, parent_dir)
        overwrite = False
        if out_path.exists():
            ok = messagebox.askyesno(
                "确认覆盖",
                f"输出文件已存在：\n{out_path}\n\n是否覆盖？",
            )
            if not ok:
                return
            overwrite = True

        self._set_busy(True)
        self.progress["value"] = 0
        self.status_text.set("开始转换…")
        threading.Thread(
            target=self._run_png_to_epub,
            args=(folder_path, parent_dir, overwrite),
            daemon=True,
        ).start()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        def update() -> None:
            pct = 0 if total <= 0 else min(100, int(current / total * 100))
            self.progress["value"] = pct
            self.status_text.set(message)

        self.after(0, update)

    def _run_epub_to_png(
        self, epub_path: Path, parent_dir: Path, overwrite: bool
    ) -> None:
        try:
            result = convert_epub(
                epub_path,
                parent_dir,
                overwrite=overwrite,
                progress_callback=self._on_progress,
            )
            self.after(0, lambda: self._on_success_epub_to_png(result))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._on_error(exc))

    def _run_png_to_epub(
        self, folder_path: Path, parent_dir: Path, overwrite: bool
    ) -> None:
        try:
            result = convert_folder_to_epub(
                folder_path,
                parent_dir,
                overwrite=overwrite,
                progress_callback=self._on_progress,
            )
            self.after(0, lambda: self._on_success_png_to_epub(result))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._on_error(exc))

    def _on_success_epub_to_png(self, result: ConvertResult) -> None:
        self._set_busy(False)
        self.progress["value"] = 100
        self.status_text.set(f"完成：共 {result.page_count} 张图片")

        extra = ""
        if result.warnings:
            shown = "\n".join(result.warnings[:8])
            more = len(result.warnings) - 8
            extra = f"\n\n警告 {len(result.warnings)} 条：\n{shown}"
            if more > 0:
                extra += f"\n…另有 {more} 条"

        target = result.output_path or result.output_dir
        open_folder = messagebox.askyesno(
            "转换完成",
            f"已导出 {result.page_count} 张 PNG 图片到：\n{target}"
            f"{extra}\n\n是否打开输出文件夹？",
        )
        if open_folder:
            try:
                os.startfile(target)  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showwarning("提示", f"无法打开文件夹：{exc}")

    def _on_success_png_to_epub(self, result: ConvertResult) -> None:
        self._set_busy(False)
        self.progress["value"] = 100
        self.status_text.set(f"完成：共打包 {result.page_count} 页")

        target = result.output_path or result.output_dir
        open_folder = messagebox.askyesno(
            "转换完成",
            f"已生成 EPUB（{result.page_count} 页）：\n{target}\n\n是否打开所在文件夹？",
        )
        if open_folder:
            try:
                os.startfile(str(Path(target).parent))  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showwarning("提示", f"无法打开文件夹：{exc}")

    def _on_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status_text.set("转换失败")
        messagebox.showerror("转换失败", str(exc))


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
