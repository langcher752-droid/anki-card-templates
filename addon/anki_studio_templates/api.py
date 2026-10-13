"""与主站通信（纯逻辑，不含 Qt，可单独测）。

为什么单独一个文件
------------------
网络请求是这一步里唯一会失败、会超时、会返回各种错误码的部分。把它和 Qt 混在一起，
就只能靠手点验证；拆开之后可以注入一个假的 transport，把「请求长什么样、
错误怎么映射成用户能看懂的话」全部测掉，不需要真联网、也不会花掉用户的算力。

只用标准库：插件里不该额外背依赖，而且 Anki 自带的 requests 版本随版本变动。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple

BASE = "https://www.lanche.website"
# 生成本身就要几十秒（LLM 逐张出卡），超时给足，否则用户会看到「网络错误」但其实是没等够。
DEFAULT_TIMEOUT = 180
LOGIN_TIMEOUT = 30

# transport(method, url, body_bytes, headers, timeout) -> (status, content_type, body_bytes)
Transport = Callable[..., Tuple[int, str, bytes]]


class SiteError(Exception):
    """消息可直接展示给用户的错误。"""


def default_transport(method: str, url: str, body: Optional[bytes] = None,
                      headers: Optional[Dict[str, str]] = None,
                      timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, str, bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.headers.get("Content-Type", ""), res.read()
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 也要把 body 读出来：后端的错误说明写在 JSON 里，丢掉就只剩一个数字。
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", exc.read()
    except urllib.error.URLError as exc:
        raise SiteError(f"连不上主站（{exc.reason}）。检查网络后重试。")
    except TimeoutError:
        raise SiteError("请求超时。材料很长时会慢一些，可以少贴一点再试。")


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _detail(content_type: str, body: bytes, fallback: str) -> str:
    """从错误响应里挖出人能看懂的一句话。"""
    if "json" in (content_type or ""):
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            if isinstance(data, dict):
                for key in ("detail", "message", "error"):
                    v = data.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        except json.JSONDecodeError:
            pass
    text = body.decode("utf-8", "replace").strip()
    return text[:200] if text and not text.startswith("<") else fallback


# --------------------------------------------------------------------------
# 卡片类型 ↔ 模板 的对应关系
#
# 站点要求 card_type 与 template_id 一致，否则会「用问答卡的数据套互动模板」，
# 导出后卡片是空的。映射规则与站点端一致：填空优先，其次互动题型，再是词汇，
# 其余按问答卡。这个判断必须和站点用同一套依据（模板自己声明的 cloze / interactive），
# 不能再写 `template_id == "xxx"` 那种硬编码。
# --------------------------------------------------------------------------
def card_type_for(template: Dict) -> str:
    if template.get("cloze"):
        return "cloze"
    interactive = (template.get("interactive") or "").strip()
    if interactive:
        return interactive
    if template.get("id") == "elegant_vocab":
        return "vocab"
    return "qa"


class SiteClient:
    def __init__(self, transport: Transport = default_transport, base: str = BASE):
        self.transport = transport
        self.base = base.rstrip("/")

    def _call(self, method: str, path: str, body: Optional[bytes],
              headers: Optional[Dict[str, str]], timeout: int) -> Tuple[int, str, bytes]:
        """统一的网络入口。

        🔴 网络异常在这里兜住，而不是只写在 default_transport 里：
        一旦有人换成别的 transport（测试、代理、将来换 requests），
        异常就会直接冒到用户面前变成 traceback。兜在这一层，任何实现都跑不掉。
        """
        try:
            return self.transport(method, f"{self.base}{path}", body, headers, timeout)
        except SiteError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(exc, TimeoutError):
                raise SiteError("请求超时。材料很长时会慢一些，可以少贴一点再试。")
            raise SiteError(f"连不上主站（{reason}）。检查网络后重试。")

    # ---------------- 登录 ----------------
    def login(self, email: str, password: str) -> dict:
        """邮箱 + 密码登录。**不保存密码**，只用它换 token。"""
        status, ctype, body = self._call(
            "POST", "/api/auth/login-password",
            _json_body({"email": email, "password": password}),
            {"Content-Type": "application/json"}, LOGIN_TIMEOUT)
        if status != 200:
            raise SiteError(_detail(ctype, body, f"登录失败（HTTP {status}）"))
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            raise SiteError("登录返回内容异常，请稍后重试。")
        token = data.get("token") or ""
        if not token:
            raise SiteError("登录成功但没拿到凭证，请改用网站登录后重试。")
        return data

    def quota(self, token: str) -> dict:
        status, ctype, body = self._call(
            "GET", "/api/quota", None,
            {"X-Auth-Token": token}, LOGIN_TIMEOUT)
        if status != 200:
            raise SiteError(_detail(ctype, body, f"读取算力失败（HTTP {status}）"))
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------------- 生成 ----------------
    def generate(self, token: str, text: str, template: Dict,
                 count_mode: str = "ai", detail_mode: str = "brief") -> dict:
        """把材料交给主站生成卡片，返回 {cards, deck_title, quota, cost}。

        🔴 生成在**主站**上跑，用你账号的算力。这不是技术选择，是产品选择：
        模型、提示词、质检都在站上，插件里重做一遍必然与站上不一致。
        """
        payload = {
            "text": text,
            "card_type": card_type_for(template),
            "template_id": template.get("id") or "modern_qa",
            "count_mode": count_mode,
            "detail_mode": detail_mode,
        }
        status, ctype, body = self._call(
            "POST", "/api/generate", _json_body(payload),
            {"Content-Type": "application/json", "X-Auth-Token": token}, DEFAULT_TIMEOUT)
        if status == 401:
            raise SiteError("登录已过期，请重新登录。")
        if status == 429:
            raise SiteError(_detail(ctype, body, "请求过于频繁，稍后再试。"))
        if status != 200:
            raise SiteError(_detail(ctype, body, f"生成失败（HTTP {status}）"))
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            raise SiteError("生成返回内容异常，请稍后重试。")
        cards = data.get("cards") or []
        if not cards:
            raise SiteError("这次没有生成出卡片。材料可能太短，或与所选类型不匹配。")
        return data

    # ---------------- 打包 ----------------
    def export_apkg(self, token: str, cards: list, deck_name: str, template_id: str) -> bytes:
        """拿到标准 .apkg。🔴 复用站点自己的打包逻辑，而不是在插件里拼卡片结构——
        模板、CSS、填空类型、互动题型的运行时全都由站点保证，插件只负责导入。"""
        status, ctype, body = self._call(
            "POST", "/api/export",
            _json_body({"cards": cards, "deck_name": deck_name, "template_id": template_id}),
            {"Content-Type": "application/json", "X-Auth-Token": token}, DEFAULT_TIMEOUT)
        if status == 401:
            raise SiteError("登录已过期，请重新登录。")
        if status != 200:
            raise SiteError(_detail(ctype, body, f"打包失败（HTTP {status}）"))
        if not body.startswith(b"PK"):
            # 必须是 zip。否则说明拿到的其实是 JSON 错误体，
            # 直接交给 Anki 导入只会报「文件损坏」——那种错最难往回追。
            raise SiteError("打包返回的不是有效的 .apkg，请稍后重试。")
        return body
