#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api.py（与主站通信）的单元测试：**注入假 transport，不联网、不花算力**。

为什么必须这样测
----------------
真实生成会消耗用户账号的算力，所以绝不能拿真接口当测试。而这段代码要处理的是
「4xx/5xx 的 body 里写了什么」「拿回来的到底是不是 zip」这类细节——
恰恰是错一次就要用户自己撞墙的地方：
  · 把 JSON 错误体当成 .apkg 交给 Anki，报的是「文件损坏」，没人能追回原因
  · 把 401 说成「网络错误」，用户会一直重试而不是重新登录
  · card_type 与 template 不匹配，导出后卡片是空的

用法
    python3 addon/test_api.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "anki_studio_templates"))

from api import SiteClient, SiteError, card_type_for  # noqa: E402

PASS = 0
FAIL = 0
failures = []


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        failures.append(label)
        print(f"  FAIL  {label}  {detail}")


class FakeTransport:
    """记录每次请求，按预设返回。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body=None, headers=None, timeout=None):
        self.calls.append({
            "method": method, "url": url, "headers": headers or {},
            "json": json.loads(body.decode()) if body else None, "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError("多余的请求：测试没准备好这个响应")
        return self.responses.pop(0)


def ok_json(payload):
    return (200, "application/json", json.dumps(payload, ensure_ascii=False).encode())


def err_json(status, detail):
    return (status, "application/json",
            json.dumps({"detail": detail}, ensure_ascii=False).encode())


def main() -> int:
    print("== 1. card_type ↔ 模板 的对应 ==")
    cases = [
        ({"id": "cloze_highlight", "cloze": True}, "cloze"),
        ({"id": "interactive_choice", "interactive": "choice"}, "choice"),
        ({"id": "interactive_match", "interactive": "match"}, "match"),
        ({"id": "elegant_vocab"}, "vocab"),
        ({"id": "modern_qa"}, "qa"),
        ({"id": "med_foldout"}, "qa"),
    ]
    for tpl, want in cases:
        got = card_type_for(tpl)
        check(f'{tpl["id"]} → {want}', got == want, f"got={got}")

    print("== 2. 登录 ==")
    tr = FakeTransport([ok_json({"token": "tk_1", "email": "a@b.c", "quota": 97})])
    c = SiteClient(transport=tr)
    data = c.login("a@b.c", "pw123")
    call = tr.calls[0]
    check("打到 /api/auth/login-password", call["url"].endswith("/api/auth/login-password"), call["url"])
    check("用 POST", call["method"] == "POST")
    check("带上邮箱与密码", call["json"] == {"email": "a@b.c", "password": "pw123"}, str(call["json"]))
    check("声明 JSON", call["headers"].get("Content-Type") == "application/json")
    check("返回 token", data.get("token") == "tk_1")

    tr = FakeTransport([err_json(400, "密码不正确")])
    try:
        SiteClient(transport=tr).login("a@b.c", "bad")
        check("密码错误应抛错", False)
    except SiteError as exc:
        check("密码错误 → 直接给出后端文案", "密码不正确" in str(exc), str(exc))

    tr = FakeTransport([ok_json({"email": "a@b.c"})])   # 没有 token
    try:
        SiteClient(transport=tr).login("a@b.c", "pw")
        check("缺 token 应抛错", False)
    except SiteError as exc:
        check("返回里没 token → 明确报错而不是当成成功", "凭证" in str(exc), str(exc))

    print("== 3. 生成 ==")
    tr = FakeTransport([ok_json({"cards": [{"front": "a", "back": "b"}] * 3,
                                 "deck_title": "测试包", "quota": 94, "cost": 3})])
    c = SiteClient(transport=tr)
    gen = c.generate("tk_1", "材料", {"id": "elegant_vocab"}, count_mode="more", detail_mode="detailed")
    call = tr.calls[0]
    check("打到 /api/generate", call["url"].endswith("/api/generate"), call["url"])
    check("带 X-Auth-Token", call["headers"].get("X-Auth-Token") == "tk_1")
    check("card_type 由模板推导为 vocab", call["json"].get("card_type") == "vocab", str(call["json"]))
    check("template_id 原样传出", call["json"].get("template_id") == "elegant_vocab")
    check("模式参数传出", call["json"].get("count_mode") == "more"
          and call["json"].get("detail_mode") == "detailed", str(call["json"]))
    check("生成超时给足（>60s）", (call["timeout"] or 0) > 60, str(call["timeout"]))
    check("返回卡片", len(gen.get("cards") or []) == 3)

    tr = FakeTransport([err_json(401, "未登录")])
    try:
        SiteClient(transport=tr).generate("tk_bad", "x", {"id": "modern_qa"})
        check("401 应抛错", False)
    except SiteError as exc:
        check("401 → 提示重新登录（而不是「网络错误」）", "登录已过期" in str(exc), str(exc))

    tr = FakeTransport([ok_json({"cards": []})])
    try:
        SiteClient(transport=tr).generate("tk_1", "太短", {"id": "modern_qa"})
        check("空卡片应抛错", False)
    except SiteError as exc:
        check("没生成出卡片 → 给出可操作的原因", "材料" in str(exc), str(exc))

    print("== 4. 打包（最容易埋坑的一步）==")
    zip_bytes = b"PK\x03\x04" + b"\x00" * 40
    tr = FakeTransport([(200, "application/octet-stream", zip_bytes)])
    blob = SiteClient(transport=tr).export_apkg("tk_1", [{"front": "a"}], "包名", "modern_qa")
    check("返回字节流", blob == zip_bytes)
    check("打到 /api/export", tr.calls[0]["url"].endswith("/api/export"))
    check("导出也带 token", tr.calls[0]["headers"].get("X-Auth-Token") == "tk_1")

    tr = FakeTransport([(200, "application/json", b'{"detail":"token expired"}')])
    try:
        SiteClient(transport=tr).export_apkg("tk_1", [], "包", "modern_qa")
        check("非 zip 响应应抛错", False)
    except SiteError as exc:
        check("拿到的不是 zip → 当场报错（否则 Anki 只会说「文件损坏」）",
              ".apkg" in str(exc) or "有效" in str(exc), str(exc))

    print("== 5. 网络层 ==")
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("nodename nor servname provided")

    c = SiteClient(transport=boom)
    try:
        c.login("a@b.c", "pw")
        check("网络失败应抛 SiteError", False)
    except SiteError as exc:
        check("连不上 → 人话提示（带原因）", "连不上主站" in str(exc), str(exc))

    def timeout(*a, **k):
        raise TimeoutError()

    try:
        SiteClient(transport=timeout).generate("tk", "x", {"id": "modern_qa"})
        check("超时应抛 SiteError", False)
    except SiteError as exc:
        check("超时 → 提示材料太长/稍后再试", "超时" in str(exc), str(exc))

    print("\n" + (f"全部 {PASS} 项通过" if not failures else f"{PASS} 通过 / {FAIL} 失败"))
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
