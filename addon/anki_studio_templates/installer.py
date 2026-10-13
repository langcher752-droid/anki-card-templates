"""模板安装逻辑（不依赖 aqt / Qt，可脱离 Anki GUI 单独测试）。

为什么单独一个文件
------------------
把「往集合里写笔记类型」这件事和「弹窗、菜单、提示」分开：

  · 写集合的代码是有破坏性的（可能新增几十个笔记类型），必须能被单独测；
    混在含 Qt 导入的模块里就只能靠手点，测不了。
  · 本文件只依赖传入的 col 对象（anki.collection.Collection），
    所以可以用 Anki 自带后端在一个**临时收藏夹**里真跑一遍，
    不需要启动 GUI，也不会碰到用户的真实数据。

数据来源
--------
同目录的 templates.json，由上游项目 scripts/build_addon_templates.py 从模板源生成。
单一数据源：站上、仓库、插件三处永远一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).parent


def load_templates(path: Path | None = None) -> Dict:
    """读模板清单。文件缺失或损坏时抛错，不返回空 dict——空 dict 会让
    「安装成功但什么都没装」这种失败看起来像正常。"""
    p = Path(path) if path else _HERE / "templates.json"
    return json.loads(p.read_text(encoding="utf-8"))


def install_templates(col, wanted_ids: List[str], path: Path | None = None) -> Tuple[List[str], List[str]]:
    """把选中的模板装进集合。

    返回 (已安装的名称列表, 因同名而跳过的名称列表)。

    🔴 只新增、不覆盖：`by_name` 命中就跳过。
       用户可能已经在用同名笔记类型并改过样式，覆盖等于无声清掉他的改动——
       这是这类「一键安装」插件最容易造成的破坏。
    """
    data = load_templates(path)
    wanted = set(wanted_ids)
    added: List[str] = []
    skipped: List[str] = []

    for tpl in data["templates"]:
        if tpl["id"] not in wanted:
            continue
        name = tpl["name"]
        if col.models.by_name(name):
            skipped.append(name)
            continue

        model = col.models.new(name)
        # 填空模板必须声明成 cloze 类型，否则 {{c1::…}} 不会被当成挖空。
        if tpl.get("cloze"):
            model["type"] = 1  # MODEL_CLOZE

        for field_name in tpl["fields"]:
            col.models.add_field(model, col.models.new_field(field_name))

        tmpl = col.models.new_template("卡片")
        tmpl["qfmt"] = tpl["qf"]
        tmpl["afmt"] = tpl["af"]
        col.models.add_template(model, tmpl)

        # CSS 要在 add() 之前赋值：add() 落库，之后再改就得额外 save 一次。
        model["css"] = tpl["css"]

        col.models.add(model)
        added.append(name)

    return added, skipped
