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
from typing import Dict, List, Optional, Tuple

from aqt import gui_hooks, mw
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

try:  # QTimer 在 QtCore 里，aqt.qt 会把它一并导出；万一版本不同就直连 PyQt6
    from aqt.qt import QTimer
except ImportError:  # pragma: no cover
    from PyQt6.QtCore import QTimer  # type: ignore

# 纯逻辑在 installer.py / bridge.py，都不含 Qt。两种加载方式都兜住：
# Anki 正常是按包导入（相对导入可用）；万一目录不是包，退回顶层导入。
try:
    from .bridge import (
        ALLOWED_ORIGIN,
        DEFAULT_PORT,
        Bridge,
        make_collection_executor,
    )
    from .installer import install_templates, load_templates
    from .panel import Panel
except ImportError:  # pragma: no cover
    from bridge import ALLOWED_ORIGIN, DEFAULT_PORT, Bridge, make_collection_executor  # type: ignore
    from installer import install_templates, load_templates  # type: ignore
    from panel import Panel  # type: ignore

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


# ==========================================================================
# 本站 → Anki 的接收桥（「发送到 Anki」）
#
# 站点生成完卡片后，把 .apkg 直接发到本机，由这里导入——省掉「下载文件 →
# 在 Anki 里找文件 → 导入」两步。实现与安全边界见 bridge.py。
#
# 🔴 线程模型：HTTP 服务在后台线程，但 Anki 的集合不是线程安全的。
#    导入必须回到主线程，靠下面的 QTimer 周期调 bridge.pump() 完成。
#    千万不要图省事在 handler 里直接 import_anki_package。
# ==========================================================================

_BRIDGE: Optional["Bridge"] = None
_PUMP_TIMER = None


def _cfg() -> dict:
    cfg = mw.addonManager.getConfig(__name__) or {}
    if not cfg.get("code"):
        # 配对码：6 位数字。它唯一的用途是「让本机端口只接受你本人的浏览器投递」，
        # 不是密码，所以不需要长、也不需要用户记。
        import secrets

        cfg["code"] = f"{secrets.randbelow(900000) + 100000}"
        mw.addonManager.writeConfig(__name__, cfg)
    return cfg


def _save_cfg(cfg: dict) -> None:
    mw.addonManager.writeConfig(__name__, cfg)


def _get_bridge() -> Optional["Bridge"]:
    return _BRIDGE


def start_bridge(quiet: bool = False) -> bool:
    global _BRIDGE, _PUMP_TIMER
    if not mw or not mw.col:
        if not quiet:
            show_warning("请先打开一个用户配置（集合）。")
        return False
    cfg = _cfg()
    if _BRIDGE is None:
        _BRIDGE = Bridge(
            code=str(cfg["code"]),
            executor=make_collection_executor(lambda: mw.col if mw else None),
            port=int(cfg.get("port") or DEFAULT_PORT),
        )
    ok, msg = _BRIDGE.start()
    if not ok:
        if not quiet:
            show_warning(f"接收服务启动失败：{msg}")
        return False
    if _PUMP_TIMER is None:
        _PUMP_TIMER = QTimer(mw)
        _PUMP_TIMER.setInterval(300)
        qconnect(_PUMP_TIMER.timeout, lambda: _BRIDGE and _BRIDGE.pump())
        _PUMP_TIMER.start()
    if not quiet:
        tooltip(msg)
    return True


def stop_bridge(quiet: bool = False) -> None:
    global _BRIDGE, _PUMP_TIMER
    if _PUMP_TIMER is not None:
        _PUMP_TIMER.stop()
        _PUMP_TIMER = None
    if _BRIDGE is not None:
        _BRIDGE.stop()
        if not quiet:
            tooltip("接收服务已停止")
    return None


def on_toggle_bridge() -> None:
    b = _get_bridge()
    if b is not None and b.running:
        stop_bridge()
    else:
        start_bridge()


def on_show_pairing() -> None:
    cfg = _cfg()
    b = _get_bridge()
    running = bool(b and b.running)
    # 端口以「实际绑定到的」为准：基端口被占时会自动往上让。
    port = b.port if running else int(cfg.get("port") or DEFAULT_PORT)
    lines = [
        f"配对码：{cfg['code']}",
        "",
        "用法：",
        "1. 在浏览器里登录主站并生成卡片（" + SITE_HOME + "AI-Anki）",
        "2. 点结果区上方的「发送到 Anki」",
        "3. 第一次会让你输入上面这个配对码；之后记住，不用再输",
        "",
        f"接收状态：{'运行中（127.0.0.1:' + str(port) + '）' if running else '未启动'}",
    ]
    if not running:
        lines += ["", "接收服务当前没在跑：工具 → Anki 小工坊 → 启动接收服务"]
        if b is not None and b.last_error:
            lines.append(f"上次失败原因：{b.last_error}")
    show_info("\n".join(lines))


def on_bridge_status() -> None:
    b = _get_bridge()
    if b is None or not b.running:
        detail = f"\n\n上次失败原因：{b.last_error}" if b is not None and b.last_error else ""
        show_info("接收服务未启动。\n\n点「启动接收服务」后，站上的「发送到 Anki」才可用。" + detail)
        return
    s = b.stats
    show_info(
        f"接收服务运行中：127.0.0.1:{b.port}\n"
        f"已导入 {s['imported']} 次，失败 {s['failed']} 次，拒绝 {s['rejected']} 次。\n\n"
        f"配对码：{_cfg()['code']}"
    )


def _on_profile_did_open() -> None:
    cfg = _cfg()
    if not cfg.get("auto_start", True):
        return
    ok = start_bridge(quiet=True)
    if not ok and _BRIDGE is not None and _BRIDGE.last_error:
        # 🔴 自动启动失败**不能静默**：用户只会发现「发送到 Anki 点了没反应」，
        #    然后来问为什么。所以这里明确说一句，并指向状态菜单。
        tooltip(f"「发送到 Anki」不可用：{_BRIDGE.last_error}\n"
                f"（工具 → Anki 小工坊 → 接收服务状态）", period=8000)


def _on_profile_will_close() -> None:
    stop_bridge(quiet=True)


# ==========================================================================
# 生成面板：在 Anki 主窗口右侧制卡（不用去网站）
#
# 界面是插件自带的本地 HTML，断网也能正常显示；只有登录与生成需要联网。
# 线程模型与 bridge.py 同一条铁律：网络在后台，写集合回主线程。
# ==========================================================================

_PANEL: Optional["Panel"] = None


def _import_apkg_for_panel(path: str) -> int:
    """把 .apkg 导进当前集合，返回新增的卡片数。**只能在主线程调用。**"""
    from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

    col = mw.col if mw else None
    if col is None:
        raise RuntimeError("当前没有打开的集合")
    before = col.db.scalar("select count() from notes") or 0
    col.import_anki_package(ImportAnkiPackageRequest(
        package_path=path,
        options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
    ))
    after = col.db.scalar("select count() from notes") or 0
    return int(after) - int(before)


def _get_panel() -> Optional["Panel"]:
    global _PANEL
    if not mw or not mw.col:
        return None
    if _PANEL is None:
        _PANEL = Panel(
            get_config=_cfg,
            save_config=_save_cfg,
            load_templates=lambda: load_templates(),
            import_apkg=_import_apkg_for_panel,
        )
    return _PANEL


def on_toggle_panel() -> None:
    panel = _get_panel()
    if panel is None:
        show_warning("请先打开一个用户配置（集合），再用生成面板。")
        return
    panel.toggle()


def setup_menu() -> None:
    if mw is None:
        return
    parent_menu = getattr(mw.form, "menuTools", None)
    if parent_menu is None:
        # 极少见：菜单结构不同就直接挂到菜单栏，避免插件静默失效。
        parent_menu = mw.form.menubar

    menu = parent_menu.addMenu("Anki 小工坊")

    # 生成面板放最前：这是日常最常用的入口（在 Anki 里直接制卡）。
    act_panel = QAction("生成面板（在这里制卡）", mw)
    qconnect(act_panel.triggered, on_toggle_panel)
    menu.addAction(act_panel)

    menu.addSeparator()

    act_install = QAction("安装卡片模板…", mw)
    qconnect(act_install.triggered, on_install)
    menu.addAction(act_install)

    act_site = QAction("打开模板展厅", mw)
    qconnect(act_site.triggered, on_open_site)
    menu.addAction(act_site)

    menu.addSeparator()

    act_toggle = QAction("启动 / 停止接收服务（本站 → Anki）", mw)
    qconnect(act_toggle.triggered, on_toggle_bridge)
    menu.addAction(act_toggle)

    act_pair = QAction("显示配对码…", mw)
    qconnect(act_pair.triggered, on_show_pairing)
    menu.addAction(act_pair)

    act_status = QAction("接收服务状态…", mw)
    qconnect(act_status.triggered, on_bridge_status)
    menu.addAction(act_status)


setup_menu()

# 集合打开/关闭时才碰集合：启动接收服务、并把定时泵挂上。
# profile_did_open 也是唯一能安全访问 mw.col 的时机。
gui_hooks.profile_did_open.append(_on_profile_did_open)
gui_hooks.profile_will_close.append(_on_profile_will_close)
