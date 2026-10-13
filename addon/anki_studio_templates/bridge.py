"""本站 → Anki 的桥：在 127.0.0.1 上收下 .apkg 并导入集合。

它解决什么
----------
站上生成完卡片后，原本的路径是「导出 .apkg → 在系统里找到文件 → 在 Anki 里导入」。
这个桥把中间两步去掉：站上点一下「发送到 Anki」，卡片直接进集合。

为什么传的是 .apkg，而不是卡片 JSON
------------------------------------
因为站点已经能生成完全正确的 .apkg（模板、CSS、填空类型、互动题型的内联运行时全都对）。
让插件去理解卡片结构，就得在插件里重新实现一遍类型映射——那份逻辑会和站点漂移，
而漂移的后果是用户导入的卡片长得不一样。所以插件只做两件事：**收包、导入**。
单一数据源留在站点。

🔴 线程模型（这是本文件最容易写错的地方）
------------------------------------------
Anki 的 Collection **不是线程安全的**，而 HTTP 服务跑在后台线程里。
如果直接在 handler 里 `mw.col.import_anki_package(...)`，就是在后台线程动集合，
症状是随机崩溃或数据损坏——而且不报错，最难查。

所以这里分成两半：
  · 后台线程（handler）：收包、校验、入队、等结果
  · 主线程（pump()，由 UI 层的 QTimer 周期调用）：真正执行导入
`pump()` 必须从主线程调用。测试里则直接在主线程调 pump()，所以我们能不启动 GUI
就把整条链路跑通。

安全边界
--------
只绑 127.0.0.1（外部访问不到），并且三道校验缺一不可：
  1. Host 头必须是 127.0.0.1 / localhost —— 挡 DNS rebinding
     （恶意域名解析到 127.0.0.1，浏览器就以为自己在跟「同源」说话）
  2. Origin 必须是本站 —— 挡其它网页往本机端口投递
  3. 配对码必须匹配 —— 挡非浏览器客户端
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional, Tuple

DEFAULT_PORT = 8765
# 端口被占时依次往上试几个。必须有个范围，而且站点要用**同样的范围**去探测——
# 实测：本机 8765 早被另一个本地服务占着，如果只认死这一个端口，
# 插件会静默启动失败，用户看到的只是「发送到 Anki 点了没反应」。
PORT_FALLBACKS = 10
ALLOWED_ORIGIN = "https://www.lanche.website"
# 单个包的上限。带媒体的牌组可能到几 MB，给到 32MB 足够，同时挡住被塞满内存。
MAX_PAYLOAD = 32 * 1024 * 1024
# 等主线程完成导入的上限。导入本身通常 <1s；超过这个时间说明主线程卡住了，
# 宁可回一个错误，也不要让站上的请求挂到超时。
JOB_TIMEOUT = 30.0
API_VERSION = 1


@dataclass
class Job:
    """一次待导入的任务。后台线程负责等，主线程负责做。"""
    path: str
    deck_hint: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    message: str = ""
    notes: int = 0


class Bridge:
    def __init__(
        self,
        *,
        code: str,
        executor: Callable[[Job], None],
        port: int = DEFAULT_PORT,
        allowed_origin: str = ALLOWED_ORIGIN,
        host: str = "127.0.0.1",
    ) -> None:
        self.code = code
        self.executor = executor
        self.port = port
        self.host = host
        self.allowed_origin = allowed_origin
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.stats = {"imported": 0, "failed": 0, "rejected": 0}
        # 启动失败的原因要留住：自动启动时没人看弹窗，用户来问「为什么没反应」时
        # 只能靠这个字段回答。
        self.last_error: str = ""

    # ---------------- 生命周期 ----------------
    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self, fallbacks: int = PORT_FALLBACKS) -> Tuple[bool, str]:
        if self._httpd is not None:
            return True, "已在运行"

        class Handler(_Handler):
            pass

        Handler.bridge = self  # type: ignore[attr-defined]

        last_exc: Optional[BaseException] = None
        for candidate in range(self.port, self.port + fallbacks + 1):
            try:
                httpd = ThreadingHTTPServer((self.host, candidate), Handler)
            except OSError as exc:
                # 端口被占是常态（本机就有一个），继续试下一个，别直接放弃。
                last_exc = exc
                continue
            httpd.daemon_threads = True
            # candidate=0 时由系统挑端口（测试用），要把真实端口读回来，
            # 否则 self.port 会停在 0，站点也就探不到。
            self.port = int(httpd.server_address[1]) if candidate == 0 else candidate
            self.last_error = ""
            self._httpd = httpd
            self._thread = threading.Thread(
                target=httpd.serve_forever, name="anki-studio-bridge", daemon=True)
            self._thread.start()
            return True, f"已在 http://{self.host}:{self.port} 上接收"

        hi = self.port + fallbacks
        self.last_error = f"端口 {self.port}–{hi} 全部被占用（{last_exc}）"
        return False, self.last_error

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # ---------------- 主线程侧 ----------------
    def pump(self, max_jobs: int = 4) -> int:
        """在主线程上清空待办队列。**必须从主线程调用**（见模块 docstring）。"""
        processed = 0
        while processed < max_jobs:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            processed += 1
            try:
                self.executor(job)
                job.ok = True
            except Exception as exc:  # noqa: BLE001
                job.ok = False
                job.message = f"{type(exc).__name__}: {exc}"
            finally:
                # 无论成败都删临时包：里面是用户的卡片内容，不该在临时目录里堆积。
                # 放在 pump（主线程）而不是 handler —— 只有这里能确定导入已经结束。
                cleanup(job.path)
                self.stats["imported" if job.ok else "failed"] += 1
                job.done.set()
        return processed

    def pending(self) -> int:
        return self.jobs.qsize()


class _Handler(BaseHTTPRequestHandler):
    bridge: Bridge  # 由 Bridge.start() 注入

    protocol_version = "HTTP/1.1"

    # 关掉默认的逐请求日志（会刷屏到 Anki 的控制台）
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    # ---------------- 工具 ----------------
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.bridge.allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome 的 Private Network Access：公网页面访问本机地址时，
        # 预检会带 Access-Control-Request-Private-Network，必须显式放行，
        # 否则请求在浏览器侧就被拦掉，表现为「点了没反应」。
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, status: int, message: str) -> None:
        # 拒绝时客户端可能还在写 body。不把数据读掉就回响应，服务端会抛
        # BrokenPipeError 并在 Anki 控制台留下一串堆栈——功能没坏，但很吓人。
        # 所以：小 body 读掉丢弃（≤1MB），并声明本次连接不再复用。
        #
        # 🔴 但如果调用方**已经**读过 body（do_POST 里读过了），这里绝不能重读：
        #    第二次 read 会一直等永远不来的数据 → 客户端超时挂死。
        self.bridge.stats["rejected"] += 1
        self.close_connection = True
        if not getattr(self, "_body_read", False):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= 1024 * 1024:
                try:
                    self.rfile.read(length)
                except OSError:
                    pass
        body = json.dumps({"ok": False, "message": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _host_ok(self) -> bool:
        """Host 头必须是本机。挡 DNS rebinding。"""
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _origin_ok(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        return origin == self.bridge.allowed_origin

    # ---------------- 路由 ----------------
    def do_OPTIONS(self):  # noqa: N802
        # 预检也要过 Host 检查，否则等于给 rebinding 开了条缝
        if not self._host_ok():
            self._reject(403, "Host 不允许")
            return
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            self._reject(403, "Host 不允许")
            return
        if self.path.rstrip("/") == "/ping":
            # 探活：站点用它判断「插件在不在」，不在就退回导出 .apkg。
            # 不校验 Origin —— 任何页面都可以问「本机有没有装」，这不是秘密。
            self._json(200, {
                "ok": True,
                "app": "anki_studio_templates",
                "api": API_VERSION,
                "running": self.bridge.running,
            })
            return
        self._reject(404, "未知路径")

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            self._reject(403, "Host 不允许")
            return
        if not self._origin_ok():
            self._reject(403, "来源不允许")
            return
        if self.path.rstrip("/") != "/import":
            self._reject(404, "未知路径")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._reject(400, "Content-Length 非法")
            return
        if length <= 0 or length > MAX_PAYLOAD:
            self._reject(413, f"包体大小非法（{length} 字节）")
            return

        raw = self.rfile.read(length)
        self._body_read = True  # 告诉 _reject：body 已消费，别再读第二次
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject(400, f"JSON 解析失败：{exc}")
            return

        if str(data.get("code") or "") != self.bridge.code:
            self._reject(403, "配对码不正确")
            return  # 🔴 必须 return：少了这一行，错误配对码会继续走到导入

        b64 = data.get("apkg_b64") or ""
        try:
            blob = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            self._reject(400, f"包内容解码失败：{exc}")
            return
        if not blob.startswith(b"PK"):
            # zip magic：不是 zip 就不必往磁盘写了
            self._reject(400, "内容不是有效的 .apkg（缺少 zip 头）")
            return

        # 落到临时文件，交给主线程导入
        fd, path = tempfile.mkstemp(prefix="anki_studio_", suffix=".apkg")
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)

        job = Job(path=path, deck_hint=str(data.get("deck") or ""))
        self.bridge.jobs.put(job)
        finished = job.done.wait(timeout=JOB_TIMEOUT)
        if not finished:
            self._json(503, {"ok": False, "message": "Anki 主线程忙，导入超时。请稍后重试。"})
            return
        if job.ok:
            self._json(200, {"ok": True, "message": job.message or "已导入", "notes": job.notes})
        else:
            self._json(500, {"ok": False, "message": job.message or "导入失败"})


# ---------------------------------------------------------------------------
# 主线程侧的默认执行器：真正把包导进当前集合。
# 单独拎出来，是为了让测试可以换成临时集合上的实现。
# ---------------------------------------------------------------------------
def make_collection_executor(get_col: Callable[[], object]) -> Callable[[Job], None]:
    def _run(job: Job) -> None:
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        col = get_col()
        if col is None:
            raise RuntimeError("当前没有打开的集合")
        before = col.db.scalar("select count() from notes") or 0
        req = ImportAnkiPackageRequest(
            package_path=job.path,
            options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
        )
        col.import_anki_package(req)
        after = col.db.scalar("select count() from notes") or 0
        job.notes = int(after) - int(before)
        job.message = f"已导入 {job.notes} 张卡"

    return _run


def cleanup(path: str) -> None:
    """删掉临时包。导入完就删，别在临时目录堆积用户内容。"""
    import os

    try:
        os.unlink(path)
    except OSError:
        pass
