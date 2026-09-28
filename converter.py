"""Convert manga EPUB files to sequential PNG page images."""

from __future__ import annotations

import io
import posixpath
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image

ProgressCallback = Callable[[int, int, str], None]

_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*]')


@dataclass
class ConvertResult:
    output_dir: Path
    page_count: int
    skipped_pages: int
    warnings: list[str]
    output_path: Path | None = None  # folder (epub→png) or .epub file (png→epub)


_PAGE_PNG_RE = re.compile(r"^(\d+)\.png$")


def sanitize_folder_name(name: str) -> str:
    """Make a string safe as a Windows folder name."""
    cleaned = _INVALID_WIN_CHARS.sub("_", name).strip().rstrip(".")
    return cleaned or "epub_output"


def output_dir_for(epub_path: Path, parent_dir: Path) -> Path:
    return parent_dir / sanitize_folder_name(epub_path.stem)


def epub_path_for(folder: Path, parent_dir: Path) -> Path:
    return parent_dir / f"{sanitize_folder_name(folder.name)}.epub"


def list_ordered_png_pages(folder: str | Path) -> list[Path]:
    """
    Return paths to 1.png .. N.png in order.

    Only exact names like '1.png', '2.png' count (no leading zeros, lowercase .png).
    Other files are ignored. Raises ValueError if none found or numbering has gaps.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"图片文件夹不存在：{folder}")

    numbered: dict[int, Path] = {}
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        match = _PAGE_PNG_RE.fullmatch(entry.name)
        if not match:
            continue
        # Reject leading zeros: '01.png' matches \d+ but str(int) would be '1'
        num_str = match.group(1)
        num = int(num_str)
        if num_str != str(num) or num < 1:
            continue
        numbered[num] = entry

    if not numbered:
        raise ValueError(
            "文件夹中没有找到合法页图（需要连续的 1.png、2.png、3.png…）。"
        )

    expected = list(range(1, max(numbered) + 1))
    missing = [n for n in expected if n not in numbered]
    if missing:
        preview = "、".join(f"{n}.png" for n in missing[:20])
        more = f" 等共 {len(missing)} 个" if len(missing) > 20 else ""
        raise ValueError(f"页码不连续，缺少：{preview}{more}")

    return [numbered[n] for n in expected]


def _normalize_href(href: str) -> str:
    href = unquote(href.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    while href.startswith("./"):
        href = href[2:]
    return href.lstrip("/")


def _resolve_href(base_name: str, src: str) -> str:
    """Resolve an image src relative to the HTML item path inside the EPUB.

    Uses posixpath (not urllib.urljoin): custom schemes like epub:/// break
    resolution of '../' on some Python builds.
    """
    src = _normalize_href(src)
    if not src:
        return ""
    # Absolute-within-package paths (leading / already stripped by normalize)
    if src.startswith("/"):
        return _normalize_href(src)

    base = _normalize_href(base_name)
    base_dir = posixpath.dirname(base)
    if base_dir:
        combined = posixpath.join(base_dir, src)
    else:
        combined = src
    return _normalize_href(posixpath.normpath(combined))


def _collect_image_srcs(html: bytes | str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    srcs: list[str] = []

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if isinstance(src, list):
            src = src[0] if src else None
        if src:
            srcs.append(str(src))

    for image in soup.find_all("image"):
        src = (
            image.get("xlink:href")
            or image.get("href")
            or image.get("{http://www.w3.org/1999/xlink}href")
        )
        if isinstance(src, list):
            src = src[0] if src else None
        if src:
            srcs.append(str(src))

    return srcs


def _build_zip_index(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map normalized path -> actual zip member name."""
    index: dict[str, str] = {}
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        norm = _normalize_href(name)
        index[norm] = name
        index[norm.lower()] = name
        base = posixpath.basename(norm)
        index.setdefault(base, name)
        index.setdefault(base.lower(), name)
    return index


def _build_item_index(book: epub.EpubBook) -> dict[str, epub.EpubItem]:
    index: dict[str, epub.EpubItem] = {}
    for item in book.get_items():
        name = _normalize_href(item.get_name())
        index[name] = item
        index[name.lower()] = item
        base = posixpath.basename(name)
        index.setdefault(base, item)
        index.setdefault(base.lower(), item)
    return index


def _find_image_bytes(
    resolved: str,
    item_index: dict[str, epub.EpubItem],
    zip_index: dict[str, str],
    zf: zipfile.ZipFile,
) -> bytes | None:
    """Locate image bytes via ebooklib item index or directly from the zip."""
    candidates = [
        resolved,
        resolved.lower(),
        posixpath.basename(resolved),
        posixpath.basename(resolved).lower(),
    ]
    # Also try without a leading folder (OPF-relative vs zip-root-relative)
    parts = resolved.split("/")
    if len(parts) > 1:
        candidates.append("/".join(parts[1:]))
        candidates.append("/".join(parts[1:]).lower())

    for key in candidates:
        item = item_index.get(key)
        if item is not None:
            return item.get_content()

    for key in candidates:
        member = zip_index.get(key)
        if member is not None:
            return zf.read(member)

    # Suffix match: resolved path ends with known member path or vice versa
    for norm, member in zip_index.items():
        if "/" not in norm:
            continue
        if resolved.endswith("/" + norm) or norm.endswith("/" + resolved):
            return zf.read(member)

    return None


def _save_png(image_bytes: bytes, dest: Path) -> None:
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(dest, format="PNG", optimize=True)


def convert_epub(
    epub_path: str | Path,
    parent_dir: str | Path,
    *,
    overwrite: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ConvertResult:
    """
    Extract manga pages from an EPUB into parent_dir/<book_name>/1.png, 2.png, ...

    Source images may be JPEG/WebP/etc. inside the EPUB; output files are always PNG.
    progress_callback(current, total, message) is invoked during conversion.
    """
    epub_path = Path(epub_path)
    parent_dir = Path(parent_dir)

    if not epub_path.is_file():
        raise FileNotFoundError(f"找不到 EPUB 文件：{epub_path}")
    if not parent_dir.is_dir():
        raise NotADirectoryError(f"输出父目录不存在：{parent_dir}")

    out_dir = output_dir_for(epub_path, parent_dir)
    if out_dir.exists():
        if not overwrite:
            raise FileExistsError(f"输出文件夹已存在：{out_dir}")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def report(current: int, total: int, message: str) -> None:
        if progress_callback:
            progress_callback(current, total, message)

    report(0, 1, "正在打开 EPUB…")
    book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
    item_index = _build_item_index(book)

    spine_docs: list[epub.EpubItem] = []
    for entry in book.spine:
        item_id = entry[0] if isinstance(entry, (list, tuple)) else entry
        if not item_id or item_id == "nav":
            continue
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        spine_docs.append(item)

    total = max(len(spine_docs), 1)
    page_index = 0
    skipped_pages = 0
    warnings: list[str] = []

    with zipfile.ZipFile(epub_path, "r") as zf:
        zip_index = _build_zip_index(zf)

        for i, doc in enumerate(spine_docs, start=1):
            report(i - 1, total, f"正在解析第 {i}/{len(spine_docs)} 页…")
            try:
                content = doc.get_content()
            except Exception as exc:  # noqa: BLE001
                skipped_pages += 1
                warnings.append(f"无法读取页面 {doc.get_name()}: {exc}")
                continue

            srcs = _collect_image_srcs(content)
            if not srcs:
                skipped_pages += 1
                continue

            saved_any = False
            for src in srcs:
                resolved = _resolve_href(doc.get_name(), src)
                image_bytes = _find_image_bytes(resolved, item_index, zip_index, zf)
                if image_bytes is None:
                    warnings.append(
                        f"找不到图片：{src} → {resolved}（来自 {doc.get_name()}）"
                    )
                    continue
                try:
                    page_index += 1
                    dest = out_dir / f"{page_index}.png"
                    _save_png(image_bytes, dest)
                    saved_any = True
                    report(
                        i,
                        total,
                        f"正在导出第 {page_index} 张图（页面 {i}/{len(spine_docs)}）…",
                    )
                except Exception as exc:  # noqa: BLE001
                    page_index = max(page_index - 1, 0)
                    warnings.append(f"保存失败 {resolved}: {exc}")

            if not saved_any:
                skipped_pages += 1

    if page_index == 0:
        if out_dir.exists() and not any(out_dir.iterdir()):
            out_dir.rmdir()
        raise RuntimeError("未从该 EPUB 中提取到任何图片，请确认是否为漫画/图集格式。")

    report(total, total, f"完成，共导出 {page_index} 张 PNG 图片")
    return ConvertResult(
        output_dir=out_dir,
        page_count=page_index,
        skipped_pages=skipped_pages,
        warnings=warnings,
        output_path=out_dir,
    )


def convert_folder_to_epub(
    folder: str | Path,
    parent_dir: str | Path,
    *,
    overwrite: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ConvertResult:
    """
    Pack a folder of 1.png..N.png into parent_dir/<folder_name>.epub (LTR manga).
    """
    folder = Path(folder)
    parent_dir = Path(parent_dir)

    if not folder.is_dir():
        raise NotADirectoryError(f"图片文件夹不存在：{folder}")
    if not parent_dir.is_dir():
        raise NotADirectoryError(f"输出父目录不存在：{parent_dir}")

    pages = list_ordered_png_pages(folder)
    out_path = epub_path_for(folder, parent_dir)

    if out_path.exists():
        if not overwrite:
            raise FileExistsError(f"输出文件已存在：{out_path}")
        out_path.unlink()

    def report(current: int, total: int, message: str) -> None:
        if progress_callback:
            progress_callback(current, total, message)

    title = folder.name
    total = len(pages)
    report(0, total, "正在创建 EPUB…")

    book = epub.EpubBook()
    book.set_identifier(f"epub-to-png-{sanitize_folder_name(title)}")
    book.set_title(title)
    book.set_language("zh")

    spine_pages: list[epub.EpubHtml] = []
    for i, png_path in enumerate(pages, start=1):
        report(i - 1, total, f"正在打包第 {i}/{total} 页…")
        image_bytes = png_path.read_bytes()
        # Ensure content is valid PNG (re-encode if needed)
        with Image.open(io.BytesIO(image_bytes)) as img:
            buf = io.BytesIO()
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

        img_item = epub.EpubImage(
            uid=f"img_{i}",
            file_name=f"images/{i}.png",
            media_type="image/png",
            content=image_bytes,
        )
        book.add_item(img_item)

        page = epub.EpubHtml(
            title=f"第 {i} 页",
            file_name=f"xhtml/page_{i}.xhtml",
            lang="zh",
        )
        page.content = (
            f"<div style=\"margin:0;padding:0;text-align:center;\">"
            f"<img src=\"../images/{i}.png\" alt=\"page {i}\" "
            f"style=\"max-width:100%;height:auto;\"/>"
            f"</div>"
        )
        book.add_item(page)
        spine_pages.append(page)

    book.toc = tuple(spine_pages)
    book.spine = ["nav"] + spine_pages
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    report(total, total, "正在写入 EPUB 文件…")
    epub.write_epub(str(out_path), book)

    report(total, total, f"完成，共打包 {total} 页")
    return ConvertResult(
        output_dir=out_path.parent,
        page_count=total,
        skipped_pages=0,
        warnings=[],
        output_path=out_path,
    )
