"""Anki 里的生成面板（主窗口右侧停靠）。

它做什么
--------
不用离开 Anki：粘贴材料 → 生成 → 卡片直接进当前集合。省掉「打开网站 → 生成 →
下载 .apkg → 回 Anki 导入」这一整圈。

界面是插件自带的本地 HTML（`panel.html`），所以**断网也能正常显示**；
只有「登录」和「生成」需要联网，那两步本来就依赖主站。

🔴 为什么挂在主窗口
-------------------
`mw`（AnkiQt）的基类就是 `QMainWindow`，所以 `addDockWidget` 直接可用。
（Anki 自己只在「浏览」窗口用了 dock，一开始我据此误判过「主窗口没有停靠 API」——
 那是从字面量找不到 `addDockWidget` 得出的错误结论。主窗口是可以加面板的。）

🔴 线程模型（和 bridge.py 同一条铁律）
--------------------------------------
Anki 的 Collection **不是线程安全的**。
  · 网络请求慢（生成要几十秒）→ 必须放后台线程，否则整个 Anki 卡死
  · 写集合（导入 .apkg）→ 必须回主线程
所以这里同样是「后台线程干活 → 结果入队 → 主线程的 QTimer 调 pump() 执行」。
**不要图省事在后台线程里 import_anki_package。**

🔴 密码不落地
-------------
登录用的密码只用于换 token，不写进配置、不写日志。配置里只存 token。
"""
from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from aqt import mw
from aqt.qt import QDockWidget, QTimer, Qt, qconnect
from aqt.utils import openLink
from aqt.webview import AnkiWebView

try:
    from .api import SiteClient, SiteError
except ImportError:  # pragma: no cover - 兼容非包加载
    from api import SiteClient, SiteError  # type: ignore

SITE = "https://www.lanche.website"
PANEL_HTML = Path(__file__).parent / "panel.html"


class Panel:
    """主窗口右侧的生成面板。生命周期由菜单控制（显示 / 隐藏）。"""

    def __init__(
        self,
        *,
        get_config: Callable[[], dict],
        save_config: Callable[[dict], None],
        load_templates: Callable[[], dict],
        import_apkg: Callable[[str], int],
        client: Optional[SiteClient] = None,
    ) -> None:
        self.get_config = get_config
        self.save_config = save_config
        self.load_templates = load_templates
        self.import_apkg = import_apkg
        self.client = client or SiteClient()

        self.dock: Optional[QDockWidget] = None
        self.web: Optional[AnkiWebView] = None
        self._jobs: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._timer: Optional[QTimer] = None

    # ---------------- 生命周期 ----------------
    @property
    def visible(self) -> bool:
        return bool(self.dock and self.dock.isVisible())

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def show(self) -> None:
        if mw is None:
            return
        if self.dock is None:
            self._build()
        if self.dock is None:
            return
        # 每次打开都重新问一次状态：可能上次是未登录，或算力已经变了。
        self.dock.show()
        self._push_state()

    def hide(self) -> None:
        if self.dock is not None:
            self.dock.hide()

    def _build(self) -> None:
        dock = QDockWidget("Anki 小工坊 · 生成", mw)
        dock.setObjectName("anki_studio_panel")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        web = AnkiWebView(parent=dock, title="Anki 小工坊")
        web.set_bridge_command(self._on_bridge, None)
        try:
            body = PANEL_HTML.read_text(encoding="utf-8")
        except OSError as exc:
            body = f"<p>面板资源读取失败：{exc}</p>"
        # stdHtml 会套上 Anki 自己的默认样式（配色、字体跟随 Anki 主题），
        # 这样面板看起来就是 Anki 的一部分，而不是一块外来的网页。
        web.stdHtml(body, context=self)

        dock.setWidget(web)
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.dock = dock
        self.web = web

        # 主线程泵：后台线程只入队，真正的集合写入在这里发生。
        self._timer = QTimer(mw)
        self._timer.setInterval(200)
        qconnect(self._timer.timeout, self.pump)
        self._timer.start()

    def pump(self) -> int:
        """在主线程上执行排队的收尾工作。**只能从主线程调用。**"""
        done = 0
        while done < 8:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            done += 1
            try:
                job()
            except Exception as exc:  # noqa: BLE001
                # 主线程里的异常绝不能冒出去：那会把 Anki 的定时器打断，
                # 后续所有回调都失效，症状是「面板再也不更新了」。
                try:
                    self._js("__panel.afterGenerate", {"ok": False,
                                                       "message": f"{type(exc).__name__}: {exc}"})
                except Exception:  # noqa: BLE001
                    pass
        return done

    # ---------------- 与页面通信 ----------------
    def _js(self, func: str, payload) -> None:
        if self.web is None:
            return
        data = json.dumps(payload, ensure_ascii=False)
        self.web.eval(f"{func}({data});")

    def _push_state(self) -> None:
        cfg = self.get_config()
        token = str(cfg.get("token") or "")
        email = str(cfg.get("email") or "") if token else ""
        quota = cfg.get("quota") if token else None
        self._js("__panel.setUser", {"email": email, "quota": quota})
        self._js("__panel.setTemplates", self._template_list())

    def _template_list(self) -> List[Dict[str, str]]:
        try:
            data = self.load_templates()
        except Exception:  # noqa: BLE001
            return []
        out = []
        for t in data.get("templates", []):
            out.append({"id": t.get("id", ""), "name": t.get("name") or t.get("id", "")})
        return out

    def _template_by_id(self, tid: str) -> Dict:
        try:
            data = self.load_templates()
        except Exception:  # noqa: BLE001
            data = {"templates": []}
        for t in data.get("templates", []):
            if t.get("id") == tid:
                return t
        return (data.get("templates") or [{}])[0]

    def _on_bridge(self, message: str) -> None:
        """页面发来的命令。**运行在主线程**（Anki 的桥就是这么调的）。"""
        try:
            msg = json.loads(message) if isinstance(message, str) else (message or {})
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        cmd = msg.get("cmd")
        if cmd == "hello":
            self._push_state()
        elif cmd == "login":
            self._do_login(str(msg.get("email") or "").strip(), str(msg.get("password") or ""))
        elif cmd == "logout":
            self._do_logout()
        elif cmd == "generate":
            self._do_generate(msg)
        elif cmd == "open_site":
            openLink(SITE)

    # ---------------- 后台任务 ----------------
    def _bg(self, work: Callable[[], object], done: Callable[[object], None]) -> None:
        """后台跑 work，结果回主线程交给 done。

        work 只能做网络/IO，**不许碰 mw.col**；done 在主线程，可以碰集合。
        """
        def runner() -> None:
            try:
                result = work()
            except SiteError as exc:
                result = {"_error": str(exc)}          # 已是对用户友好的文案
            except Exception as exc:  # noqa: BLE001
                result = {"_error": f"意外错误：{type(exc).__name__}: {exc}"}
            self._jobs.put(lambda: done(result))

        threading.Thread(target=runner, name="anki-studio-panel", daemon=True).start()

    # ---------------- 具体动作 ----------------
    def _do_login(self, email: str, password: str) -> None:
        if not email or not password:
            self._js("__panel.afterLogin", {"ok": False, "message": "邮箱和密码都要填。"})
            return

        def work() -> dict:
            data = self.client.login(email, password)
            token = data["token"]
            q = {}
            try:
                q = self.client.quota(token)
            except SiteError:
                pass  # 算力读不到不影响登录
            return {"token": token, "email": data.get("email") or email,
                    "quota": q.get("quota", data.get("quota")), "raw": data}

        def done(result: object) -> None:
            if isinstance(result, dict) and result.get("_error"):
                self._js("__panel.afterLogin", {"ok": False, "message": result["_error"]})
                return
            data = result if isinstance(result, dict) else {}
            cfg = self.get_config()
            cfg["token"] = data.get("token") or ""
            cfg["email"] = data.get("email") or email
            cfg["quota"] = data.get("quota")
            # 🔴 密码不写进配置。
            self.save_config(cfg)
            self._push_state()
            self._js("__panel.afterLogin", {"ok": True})

        self._bg(work, done)

    def _do_logout(self) -> None:
        cfg = self.get_config()
        for key in ("token", "email", "quota"):
            cfg.pop(key, None)
        self.save_config(cfg)
        self._push_state()

    def _do_generate(self, msg: dict) -> None:
        cfg = self.get_config()
        token = str(cfg.get("token") or "")
        if not token:
            self._js("__panel.afterGenerate", {"ok": False, "message": "请先登录。"})
            return
        text = str(msg.get("text") or "").strip()
        if not text:
            self._js("__panel.afterGenerate", {"ok": False, "message": "先粘贴一些材料。"})
            return

        tpl = self._template_by_id(str(msg.get("template") or ""))
        count_mode = str(msg.get("count_mode") or "ai")
        detail_mode = str(msg.get("detail_mode") or "brief")
        deck_hint = tpl.get("id") or "cards"

        def work() -> dict:
            gen = self.client.generate(token, text, tpl,
                                      count_mode=count_mode, detail_mode=detail_mode)
            cards = gen.get("cards") or []
            deck_name = gen.get("deck_title") or "AI 生成卡片"
            blob = self.client.export_apkg(token, cards, deck_name, tpl.get("id") or "modern_qa")
            return {"blob": blob, "cards": len(cards), "deck": deck_name,
                    "quota": gen.get("quota"), "cost": gen.get("cost"),
                    "id": deck_hint}

        def done(result: object) -> None:
            if isinstance(result, dict) and result.get("_error"):
                self._js("__panel.afterGenerate", {"ok": False, "message": result["_error"]})
                return
            data = result if isinstance(result, dict) else {}
            blob = data.get("blob") or b""
            # 到这里已经在主线程了：写集合是安全的。
            path = ""
            try:
                fd, path = tempfile.mkstemp(prefix="anki_studio_panel_", suffix=".apkg")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(blob)
                imported = self.import_apkg(path)
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            # 算力变了，顺手更新页面上的显示
            c = self.get_config()
            if data.get("quota") is not None:
                c["quota"] = data.get("quota")
                self.save_config(c)
            self._push_state()
            self._js("__panel.afterGenerate", {
                "ok": True,
                "message": f'「{data.get("deck") or "卡包"}」已导入 {imported} 张卡',
            })

        self._bg(work, done)
