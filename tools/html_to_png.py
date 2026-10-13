#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 2 步：把第 1 步产出的 HTML 截成 PNG，写进 `previews/`。

为什么要分成两步、两个解释器
----------------------------
第 1 步需要 Anki 自带的 anki 包（在 Anki.app 里），第 2 步需要 Playwright。
两者的依赖树（尤其 protobuf）容易打架，混在一个进程里会以难查的导入错误收场。
分成两步最省事：中间产物就是 HTML 文件，也能单独打开肉眼核对。

前置
----
需要一个装了 Playwright 的 Python（本项目用的是 claude-seo 的隔离 venv）：
    pip install playwright && playwright install chromium
用环境变量指定解释器与浏览器目录，避免污染系统环境：
    PW_PYTHON=/path/to/.venv/bin/python
    PLAYWRIGHT_BROWSERS_PATH=/path/to/ms-playwright

用法
    PW_PYTHON=... PLAYWRIGHT_BROWSERS_PATH=... python3 tools/html_to_png.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = HERE / "_build"
OUT = REPO / "previews"

# 视口宽度 1000 + 2 倍像素密度：README 里缩放后仍然清晰，单图约 100–200KB。
VIEWPORT = {"width": 1000, "height": 640}
SCALE = 2


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("当前解释器没有 playwright。请用 PW_PYTHON 指定装了 Playwright 的 Python。")
        return 1

    htmls = sorted(SRC.glob("*.html"))
    if not htmls:
        print(f"{SRC} 下没有 HTML，请先跑 tools/anki_render_cards.py")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for html in htmls:
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)[:160]))
            page.goto(html.as_uri(), wait_until="load")
            # 互动题型的内联运行时要跑一帧才把选项渲染出来，给一点时间。
            page.wait_for_timeout(600)
            target = page.query_selector(".row") or page.query_selector("body")
            out = OUT / f"{html.stem}.png"
            target.screenshot(path=str(out))
            size = out.stat().st_size
            status = "✅" if not errors else "⚠️"
            print(f"  {status} {html.stem:20s} {size//1024:>4d} KB"
                  + (f"  页面错误: {errors[0]}" if errors else ""))
            if errors:
                problems.append((html.stem, errors[0]))
            page.close()
        browser.close()

    total = sum(f.stat().st_size for f in OUT.glob("*.png"))
    print(f"\n输出目录：{OUT}（{len(htmls)} 张，合计 {total//1024} KB）")
    if problems:
        print("\n以下页面有 JS 错误（截图可能不完整，需要人工看一眼）：")
        for name, err in problems:
            print(f"  · {name}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
