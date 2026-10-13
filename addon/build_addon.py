#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把插件打包成 AnkiWeb 可上传的 .zip。

为什么需要脚本而不是手点右键压缩
--------------------------------
AnkiWeb 要求 zip 的**根目录**就是插件文件（`__init__.py`、`manifest.json`），
不是「一个包含插件的文件夹」。用访达压缩会多套一层目录，上传后被判为无效包。
另外打包时要把开发用文件排除掉（测试脚本里写着 macOS 的绝对路径）。

用法
    python3 addon/build_addon.py
输出
    dist/anki-studio-templates-<版本>.zip
"""
import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "anki_studio_templates"
DIST = HERE.parent / "dist"

# 只打插件运行必需的文件。测试脚本、构建脚本都不进包。
INCLUDE = ("__init__.py", "installer.py", "manifest.json", "templates.json")


def main() -> int:
    if not (SRC / "__init__.py").exists():
        print(f"找不到插件目录：{SRC}")
        return 1
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("human_version", "0.0.0")

    missing = [f for f in INCLUDE if not (SRC / f).exists()]
    if missing:
        print(f"缺少必需文件：{missing}")
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"anki-studio-templates-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in INCLUDE:
            z.write(SRC / name, arcname=name)  # arcname 不带目录 → 根目录布局

    # 打包后自检：解出文件清单确认结构正确，避免上传一个无效包。
    with zipfile.ZipFile(out) as z:
        names = sorted(z.namelist())
        bad = z.testzip()
    print(f"输出：{out}  ({out.stat().st_size} B)")
    print(f"根目录文件：{names}")
    if bad:
        print(f"❌ zip 校验失败：{bad}")
        return 1
    if "__init__.py" not in names or "manifest.json" not in names:
        print("❌ 根目录缺少 __init__.py 或 manifest.json —— AnkiWeb 会判为无效")
        return 1
    if manifest.get("package") in (None, "", "000000000"):
        print("⚠️ manifest.json 的 package 还是占位值。AnkiWeb 上传后会分配编号，")
        print("   必须把它填回 manifest.json 再重新打包，否则插件更新会失效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
