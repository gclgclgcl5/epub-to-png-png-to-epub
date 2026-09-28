# 漫画 EPUB / PNG 互转

双向转换工具：

- **EPUB → PNG**：漫画 EPUB 按阅读顺序导出为 `1.png`、`2.png`…
- **PNG → EPUB**：把连续 `1.png`…`N.png` 的文件夹打包成 EPUB

## 环境要求

- Windows
- Python 3.10+

## 安装依赖

```bat
python -m pip install -r requirements.txt
```

## 运行 GUI

```bat
python main.py
```

### EPUB → PNG

1. 打开「EPUB → PNG」页签  
2. 选择一个 EPUB 文件  
3. 选择输出父目录  
4. 点击「开始转换」  
5. 结果：`输出父目录\电子书文件名\1.png …`

### PNG → EPUB

1. 打开「PNG → EPUB」页签  
2. 选择包含页图的文件夹（文件名必须是连续的 `1.png`、`2.png`、`3.png`…）  
3. 选择输出父目录  
4. 点击「开始转换」  
5. 结果：`输出父目录\文件夹名.epub`

**校验规则：**

- 只认恰好为 `1.png`、`2.png`… 的文件（小写 `.png`，无前导零）
- `01.png`、`1.JPG`、其它文件名会被忽略
- 页码必须从 1 连续到 N；缺页（如有 1、2、4 无 3）会直接报错，不生成 EPUB
- 书名与输出文件名使用文件夹名；阅读方向为从左到右

## 打包成 exe

双击运行 `build.bat`，或在项目目录执行：

```bat
python -m PyInstaller -F -w -n EpubToPng main.py
```

生成文件：`dist\EpubToPng.exe`

## 说明

- 仅支持无 DRM 的 EPUB
- EPUB→PNG：按 spine 解析每页图片；JPEG/WebP 等会转为 PNG
- PNG→EPUB：不保留原书 CSS / 复杂封面 / 目录结构（每页一图的简单漫画包）
- 若目标文件夹或 `.epub` 已存在，会提示是否覆盖
