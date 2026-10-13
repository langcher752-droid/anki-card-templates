#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 1 步：用 Anki 自己的渲染器把每套模板的卡片渲染成 HTML。

为什么用 Anki 的渲染器而不是自己拼 HTML
----------------------------------------
卡片长什么样由「模板 + CSS + Anki 的渲染管线」共同决定，其中还包括条件渲染、
字段替换、填空处理、以及互动题型的运行时注入。自己拼出来的 HTML 一定与真实
Anki 有偏差——预览图失真的话，用户下载后会觉得上当。

这里直接调用 Anki 后端的 `render_existing_card`，拿到的是**与 Anki 内部完全一致**
的问答 HTML 与 CSS。

前置
----
需要本机安装 Anki（用它的 anki 包，不启动 GUI，也不碰你的真实收藏夹）：
  · macOS 默认路径 /Applications/Anki.app/Contents/Resources/app_packages
  · 其他平台用环境变量 ANKI_APP_PACKAGES 指定
解释器需与 Anki 的 Python 版本一致（Anki 26.9.2 = 3.13）。

输出
----
  tools/_build/<id>.html   可直接交给浏览器截图的双栏（正面 / 背面）页面

用法
    ANKI_APP_PACKAGES=/Applications/Anki.app/Contents/Resources/app_packages \\
    python3 tools/anki_render_cards.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

APP_PACKAGES = os.environ.get(
    "ANKI_APP_PACKAGES",
    "/Applications/Anki.app/Contents/Resources/app_packages",
)
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DECKS = REPO / "decks"
OUT = HERE / "_build"

if not Path(APP_PACKAGES).is_dir():
    print(f"找不到 Anki 的 app_packages：{APP_PACKAGES}")
    print("请安装 Anki，或用 ANKI_APP_PACKAGES 指定路径。")
    sys.exit(1)
sys.path.insert(0, APP_PACKAGES)

from anki.collection import Collection  # noqa: E402

# 双栏预览的外层样式。放在模板 CSS **之后**，让布局规则生效；
# 对 .card 的改动用 .pane .card 提高选择权，避免覆盖模板自身的配色与排版。
WRAPPER_CSS = """
html,body{margin:0;padding:0;background:#eceef2;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",sans-serif;}
.row{display:flex;gap:20px;align-items:stretch;padding:22px;box-sizing:border-box;}
.pane{flex:1 1 0;min-width:0;display:flex;flex-direction:column;}
.pane-h{margin:0 0 8px 3px;font-size:11px;font-weight:700;letter-spacing:.09em;
        text-transform:uppercase;color:#8a919f;}
.pane .card{box-shadow:0 1px 3px rgba(16,24,40,.09);border-radius:12px;flex:1 1 auto;
            box-sizing:border-box;overflow:hidden;}
"""


def build_html(front: str, back: str, css: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{css}</style><style>{WRAPPER_CSS}</style>"
        '</head><body><div class="row">'
        f'<div class="pane"><p class="pane-h">Front</p>{front}</div>'
        f'<div class="pane"><p class="pane-h">Back</p>{back}</div>'
        "</div></body></html>"
    )


def render_deck(apkg: Path, out_dir: Path) -> dict:
    """解开 .apkg（就是个 zip）直接打开里面的 collection，渲染第一张卡。"""
    tmp = tempfile.mkdtemp(prefix="preview_")
    try:
        with zipfile.ZipFile(apkg) as z:
            z.extractall(tmp)
        col_path = os.path.join(tmp, "collection.anki2")
        if not os.path.exists(col_path):
            raise FileNotFoundError("包里没有 collection.anki2")
        col = Collection(col_path)
        try:
            card_id = col.db.scalar("select id from cards order by id limit 1")
            if not card_id:
                raise ValueError("这个牌组里没有卡片")
            r = col._backend.render_existing_card(
                card_id=card_id, browser=False, partial_render=False
            )
            front = "".join(n.text for n in r.question_nodes)
            back = "".join(n.text for n in r.answer_nodes)
            note = col.get_card(card_id).note()
            # Anki 26 起 note.model() 已弃用，改叫 note_type()
            model = note.note_type()
            out = out_dir / f"{apkg.stem}.html"
            out.write_text(build_html(front, back, r.css), encoding="utf-8")
            return {
                "id": apkg.stem,
                "model_name": model["name"],
                "fields": [f["name"] for f in model["flds"]],
                "front_len": len(front),
                "back_len": len(back),
                "css_len": len(r.css),
                "html": str(out),
            }
        finally:
            col.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    if not DECKS.is_dir():
        print(f"找不到牌组目录：{DECKS}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    # 只给**模板**出预览图：decks/ 里还可能有内容牌组（例如
    # spaced-repetition-flashcards.apkg，它是给 /flashcards 页面配套的 12 张卡，
    # 不是模板）。判据就一条——templates/<id>/ 是否存在。这样预览图与模板
    # 严格 1:1，README 的表格也不会被内容牌组打乱。
    decks = [d for d in sorted(DECKS.glob("*.apkg")) if (REPO / "templates" / d.stem).is_dir()]
    skipped = [d.name for d in sorted(DECKS.glob("*.apkg")) if d not in decks]
    if not decks:
        print("decks/ 下没有可出预览图的模板牌组")
        return 1
    if skipped:
        print(f"跳过非模板牌组（不出预览图）：{', '.join(skipped)}")

    print(f"用 Anki 渲染 {len(decks)} 套模板…")
    rows = []
    for apkg in decks:
        try:
            info = render_deck(apkg, OUT)
            rows.append(info)
            print(f"  ✅ {info['id']:20s} 字段={len(info['fields'])} "
                  f"front={info['front_len']}B back={info['back_len']}B css={info['css_len']}B")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {apkg.name}: {type(exc).__name__}: {exc}")
    print(f"\nHTML 输出目录：{OUT}（{len(rows)}/{len(decks)} 成功）")
    return 0 if len(rows) == len(decks) else 1


if __name__ == "__main__":
    sys.exit(main())
