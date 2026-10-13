"""Anki 小工坊 · 模板一键安装器

作用
----
把 11 套原创卡片模板一次性装进你的 Anki 集合，省掉「新建笔记类型 → 逐个加字段 →
粘贴正反面模板 → 粘贴 CSS」这一串手工步骤。

装完就是普通的笔记类型：本地数据、可自由修改、不依赖本插件、不依赖网络。
卸载插件后模板照常存在。

菜单
----
工具 → Anki 小工坊 → 安装卡片模板…   选择要装哪几套
工具 → Anki 小工坊 → 打开模板展厅     在浏览器里看每套模板的真实效果

设计取舍
--------
* 只新增，不覆盖。同名笔记类型已存在就跳过，绝不改动你已有的笔记类型——
  改错别人的笔记类型是这类插件最容易造成的破坏。
* 模板数据放在同目录的 templates.json 里，不写死在代码中：模板改了只要换 json，
  不用重新审代码。生成脚本见上游项目 scripts/build_addon_templates.py。
* 不联网。安装过程完全本地，不需要账号，不上报任何东西。

Anki 版本
---------
按 Anki 26.9.2 的 API 写并核对过（ModelManager 的 new / new_field / add_field /
new_template / add_template / add / by_name 均在）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from aqt import mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import show_info, show_warning, tooltip

# 纯逻辑在 installer.py，不含 Qt。两种加载方式都兜住：
# Anki 正常是按包导入（相对导入可用）；万一目录不是包，退回顶层导入。
try:
    from .installer import install_templates, load_templates
except ImportError:  # pragma: no cover
    from installer import install_templates, load_templates  # type: ignore

SITE_TEMPLATES = "https://www.lanche.website/templates"
SITE_HOME = "https://www.lanche.website/"

_ADDON_DIR = Path(__file__).parent


class PickDialog(QDialog):
    """勾选要安装哪些模板。默认全选。"""

    def __init__(self, templates: List[Dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("安装 Anki 小工坊卡片模板")
        self.setMinimumWidth(460)
        self._boxes: List[Tuple[QCheckBox, str]] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选要安装的模板（已存在同名笔记类型的会自动跳过）："))

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for tpl in templates:
            box = QCheckBox(f'{tpl["name"]} — {tpl.get("description", "")}')
            box.setChecked(True)
            inner_layout.addWidget(box)
            self._boxes.append((box, tpl["id"]))
        inner_layout.addStretch(1)
        area.setWidget(inner)
        layout.addWidget(area)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("安装")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        qconnect(buttons.accepted, self.accept)
        qconnect(buttons.rejected, self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> List[str]:
        return [tid for box, tid in self._boxes if box.isChecked()]


def on_install() -> None:
    if mw is None or not mw.col:
        show_warning("请先打开一个用户配置（集合）再安装模板。")
        return
    try:
        data = load_templates()
    except Exception as exc:  # noqa: BLE001
        show_warning(f"模板数据读取失败：{exc}\n请重新安装本插件。")
        return

    dlg = PickDialog(data["templates"], parent=mw)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    chosen = dlg.chosen()
    if not chosen:
        tooltip("没有选择任何模板")
        return

    try:
        added, skipped = install_templates(mw.col, chosen)
    except Exception as exc:  # noqa: BLE001
        show_warning(f"安装失败：{type(exc).__name__}: {exc}")
        return

    lines = []
    if added:
        lines.append("已安装：" + "、".join(added))
    if skipped:
        lines.append("已存在同名笔记类型，跳过（未改动原有设置）：" + "、".join(skipped))
    lines.append("")
    lines.append("新笔记类型会出现在「添加」窗口的类型列表里。")
    lines.append("模板展厅（可看每套模板的真实效果）：" + SITE_TEMPLATES)
    show_info("\n".join(lines))


def on_open_site() -> None:
    from aqt.utils import openLink

    openLink(SITE_TEMPLATES)


def setup_menu() -> None:
    if mw is None:
        return
    parent_menu = getattr(mw.form, "menuTools", None)
    if parent_menu is None:
        # 极少见：菜单结构不同就直接挂到菜单栏，避免插件静默失效。
        parent_menu = mw.form.menubar

    menu = parent_menu.addMenu("Anki 小工坊")
    act_install = QAction("安装卡片模板…", mw)
    qconnect(act_install.triggered, on_install)
    menu.addAction(act_install)

    act_site = QAction("打开模板展厅", mw)
    qconnect(act_site.triggered, on_open_site)
    menu.addAction(act_site)


setup_menu()
