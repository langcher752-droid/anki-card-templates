#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把插件**真的加载一遍**（用假的 aqt 模块），验证 Qt 胶水层没有错的引用。

为什么需要这个测试
------------------
bridge.py 和 installer.py 是纯逻辑，能单独测；但 `__init__.py` 里全是 Qt 胶水——
菜单、弹窗、定时器。这一层最常见的 bug 是**引用了一个没导入或拼错的名字**，
比如菜单里用了 `QTimer` 却没 import。这种错在 Anki 里的表现是「插件整块不加载」，
而错误信息埋在 Anki 启动日志里，用户根本看不到。

真跑 Anki GUI 做验证不现实（会碰用户真实收藏夹、也没法自动化），
所以这里**伪造 aqt / aqt.qt / aqt.utils / aqt.gui_hooks**，把插件当普通包导入，
然后：检查菜单项建出来了、钩子注册了、菜单回调能跑通、
接收服务能真的起来并响应 /ping。

它测不出的东西（要诚实）
  · 真实 Qt 的行为（信号连接、窗口生命周期）
  · Anki 真实的 addonManager / mw.form 结构是否与伪造的一致
所以它是「防止低级错误」的网，不是「证明在 Anki 里一定正常」的证明。

用法
    python3 addon/test_addon_glue.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import urllib.request
from pathlib import Path

APP_PACKAGES = os.environ.get(
    "ANKI_APP_PACKAGES", "/Applications/Anki.app/Contents/Resources/app_packages")
HERE = Path(__file__).resolve().parent
ADDON_DIR = HERE / "anki_studio_templates"

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


# --------------------------------------------------------------------------
# 伪造 aqt
# --------------------------------------------------------------------------
class FakeSignal:
    """只记下槽函数，测试里手动触发。"""
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def fire(self, *a):
        for s in self.slots:
            s(*a)


class FakeAction:
    def __init__(self, text, parent=None):
        self.text = text
        self.triggered = FakeSignal()


class FakeMenu:
    def __init__(self):
        self.actions = []
        self.separators = 0

    def addAction(self, a):
        self.actions.append(a)

    def addSeparator(self):
        self.separators += 1


class FakeMenuBar:
    def __init__(self):
        self.menus = []

    def addMenu(self, name):
        m = FakeMenu()
        m.name = name
        self.menus.append(m)
        return m


class FakeForm:
    def __init__(self):
        self.menuTools = FakeMenuBar()
        self.menubar = FakeMenuBar()


class FakeTimer:
    def __init__(self, parent=None):
        self.timeout = FakeSignal()
        self.interval = 0
        self.running = False

    def setInterval(self, ms):
        self.interval = ms

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class FakeAddonManager:
    def __init__(self):
        self.store = {}

    def getConfig(self, name):
        return json.loads(json.dumps(self.store.get(name, {"code": "", "port": 8765,
                                                           "auto_start": True})))

    def writeConfig(self, name, cfg):
        self.store[name] = cfg


class FakeMW:
    def __init__(self, col=None):
        self.form = FakeForm()
        self.addonManager = FakeAddonManager()
        self.col = col


def install_fake_aqt(mw_obj):
    aqt = types.ModuleType("aqt")
    aqt.mw = mw_obj
    hooks = types.ModuleType("aqt.gui_hooks")
    hooks.profile_did_open = []
    hooks.profile_will_close = []
    aqt.gui_hooks = hooks

    qt = types.ModuleType("aqt.qt")
    for name in ("QAction", "QCheckBox", "QDialog", "QDialogButtonBox", "QLabel",
                 "QScrollArea", "QVBoxLayout", "QWidget", "QTimer"):
        setattr(qt, name, FakeAction if name == "QAction" else FakeTimer if name == "QTimer"
                else type(name, (), {}))
    qt.qconnect = lambda sig, slot: sig.connect(slot)

    utils = types.ModuleType("aqt.utils")
    utils.calls = []
    utils.show_info = lambda m, **k: utils.calls.append(("info", m))
    utils.show_warning = lambda m, **k: utils.calls.append(("warn", m))
    utils.tooltip = lambda m, **k: utils.calls.append(("tip", m))
    utils.openLink = lambda u: utils.calls.append(("open", u))

    sys.modules.update({"aqt": aqt, "aqt.gui_hooks": hooks, "aqt.qt": qt, "aqt.utils": utils})
    return hooks, utils


def load_addon_package():
    """按包导入（submodule_search_locations 让相对导入生效），模拟 Anki 的加载方式。"""
    for mod in [m for m in list(sys.modules) if m.startswith("anki_studio_templates")]:
        del sys.modules[mod]
    spec = importlib.util.spec_from_file_location(
        "anki_studio_templates", ADDON_DIR / "__init__.py",
        submodule_search_locations=[str(ADDON_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["anki_studio_templates"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if APP_PACKAGES not in sys.path:
        sys.path.insert(0, APP_PACKAGES)

    tmp = tempfile.mkdtemp(prefix="glue_")
    mw_obj = FakeMW()
    hooks, utils = install_fake_aqt(mw_obj)

    print("== 1. 导入插件包（会执行 setup_menu + 注册钩子）==")
    try:
        addon = load_addon_package()
    except Exception as exc:  # noqa: BLE001
        check("插件可被导入", False, f"{type(exc).__name__}: {exc}")
        print(f"\n结果：{PASS} 通过，{FAIL} 失败")
        return 1
    check("插件可被导入", True)

    print("== 2. 菜单 ==")
    check("挂上了「Anki 小工坊」菜单", len(mw_obj.form.menuTools.menus) == 1,
          str([m.name for m in mw_obj.form.menuTools.menus]))
    menu = mw_obj.form.menuTools.menus[0]
    labels = [a.text for a in menu.actions]
    check("菜单项 ≥5 个", len(labels) >= 5, str(labels))
    for want in ("安装卡片模板…", "打开模板展厅", "显示配对码…", "接收服务状态…"):
        check(f"含菜单项「{want}」", any(want in x for x in labels), str(labels))
    check("有分隔线", menu.separators >= 1)

    print("== 3. 钩子 ==")
    check("注册了 profile_did_open", len(hooks.profile_did_open) == 1)
    check("注册了 profile_will_close", len(hooks.profile_will_close) == 1)

    print("== 4. 没打开集合时不应崩 ==")
    try:
        addon.on_show_pairing()
        addon.on_bridge_status()
        ok = addon.start_bridge(quiet=True)
        check("无集合时 start_bridge 返回 False 而不是抛错", ok is False)
    except Exception as exc:  # noqa: BLE001
        check("无集合时调用不抛异常", False, f"{type(exc).__name__}: {exc}")

    print("== 5. 有集合时：配对码生成 + 服务启动 + 探活 ==")
    from anki.collection import Collection
    col = Collection(os.path.join(tmp, "collection.anki2"))
    mw_obj.col = col
    try:
        hooks.profile_did_open[0]()  # 模拟打开配置
        cfg = mw_obj.addonManager.store.get("anki_studio_templates", {})
        check("配对码已自动生成（6 位数字）",
              str(cfg.get("code", "")).isdigit() and len(str(cfg.get("code"))) == 6,
              str(cfg))
        check("服务在运行", addon._BRIDGE is not None and addon._BRIDGE.running)
        check("定时泵已启动", addon._PUMP_TIMER is not None and addon._PUMP_TIMER.running)

        port = addon._BRIDGE.port
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=5) as res:
            payload = json.loads(res.read())
        check("GET /ping 通", payload.get("ok") is True, str(payload))

        addon.on_show_pairing()
        shown = [m for k, m in utils.calls if k == "info"]
        check("配对码弹窗里带上了配对码", any(str(cfg["code"]) in m for m in shown),
              str(shown[-1:])[:160])

        # 定时泵的槽能被触发（真实 Anki 里由 QTimer 触发）
        addon._PUMP_TIMER.timeout.fire()
        check("泵回调可执行", True)

        addon.stop_bridge(quiet=True)
        check("服务已停止", addon._BRIDGE is None or not addon._BRIDGE.running)

        hooks.profile_will_close[0]()
        check("关闭配置钩子可执行", True)
    finally:
        col.close()
        try:
            addon.stop_bridge(quiet=True)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
