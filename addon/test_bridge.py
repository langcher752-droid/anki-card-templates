#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桥（本站 → Anki）的端到端验证：不启动 GUI，不碰真实收藏夹。

覆盖什么
--------
1. 正常链路：把真实 .apkg 用 base64 发过去 → 主线程导入 → 集合里真的多了卡片
2. 三道安全校验各自生效：Host / Origin / 配对码，任一不对都必须拒绝且不入库
3. 预检（OPTIONS）返回 Private Network Access 放行头 —— 少了它浏览器会直接拦掉请求
4. 坏内容被拒（不是 zip 的内容不会写盘）
5. 拒绝请求不产生副作用（集合卡片数不变）

线程模型是照实复现的
--------------------
集合归本进程的主线程所有；HTTP 请求在另一个线程里等结果。
所以测试里 POST 跑在子线程、pump() 跑在主线程——和插件里 QTimer 的做法一致。
**如果哪天有人把导入直接写进 handler，这个测试不会发现**（它只验证行为），
所以 bridge.py 的模块 docstring 里单独写了这条禁令。

用法
    python3 addon/test_bridge.py
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

APP_PACKAGES = os.environ.get(
    "ANKI_APP_PACKAGES", "/Applications/Anki.app/Contents/Resources/app_packages")
HERE = Path(__file__).resolve().parent

if not Path(APP_PACKAGES).is_dir():
    print(f"找不到 Anki 的 app_packages：{APP_PACKAGES}")
    sys.exit(1)
sys.path.insert(0, APP_PACKAGES)
sys.path.insert(0, str(HERE / "anki_studio_templates"))

from anki.collection import Collection  # noqa: E402
from bridge import ALLOWED_ORIGIN, Bridge, cleanup, make_collection_executor  # noqa: E402

PASS = 0
FAIL = 0
CODE = "482913"
SAMPLE_APKG = Path.home() / "WorkBuddy" / "anki-card-templates" / "decks" / "med_foldout.apkg"


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def http_json(method, url, *, body=None, origin=ALLOWED_ORIGIN, timeout=40):
    """返回 (status, dict)。urllib 不允许伪造 Host，Host 另用 http.client 测。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if origin is not None:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


def post_in_thread(url, payload, holder):
    """在子线程里发 POST —— 模拟浏览器，主线程才有权动集合。"""
    try:
        holder["res"] = http_json("POST", url, body=payload)
    except Exception as exc:  # noqa: BLE001
        holder["err"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    if not SAMPLE_APKG.exists():
        print(f"缺少测试用的 .apkg：{SAMPLE_APKG}")
        return 1
    blob_b64 = base64.b64encode(SAMPLE_APKG.read_bytes()).decode("ascii")

    tmp = tempfile.mkdtemp(prefix="bridge_test_")
    col = Collection(os.path.join(tmp, "collection.anki2"))
    bridge = Bridge(code=CODE, executor=make_collection_executor(lambda: col), port=0)
    ok, msg = bridge.start()
    if not ok:
        print("桥启动失败：", msg)
        col.close()
        return 1
    base = f"http://127.0.0.1:{bridge.port}"
    print(f"== 桥已启动：{base}（配对码 {CODE}）==\n")
    paths_seen = []

    # 包一层 executor，顺便记录临时文件路径以便检查清理
    inner = bridge.executor

    def traced(job):
        paths_seen.append(job.path)
        inner(job)

    bridge.executor = traced

    try:
        # ---------- 1. 探活 ----------
        print("== 1. 探活 ==")
        st, body = http_json("GET", f"{base}/ping")
        check("GET /ping 返回 200", st == 200, f"status={st}")
        check("探活带 app 标识", body.get("app") == "anki_studio_templates", str(body))

        # ---------- 2. 预检 ----------
        print("== 2. 预检（浏览器必过的一关）==")
        conn = HTTPConnection("127.0.0.1", bridge.port, timeout=10)
        conn.request("OPTIONS", "/import", headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        })
        res = conn.getresponse()
        hdrs = {k.lower(): v for k, v in res.getheaders()}
        conn.close()
        check("OPTIONS 返回 204", res.status == 204, f"status={res.status}")
        check("放行本站 Origin", hdrs.get("access-control-allow-origin") == ALLOWED_ORIGIN,
              str(hdrs.get("access-control-allow-origin")))
        check("放行 Private Network（缺它浏览器直接拦）",
              hdrs.get("access-control-allow-private-network") == "true",
              str(hdrs.get("access-control-allow-private-network")))

        # ---------- 3. 安全校验 ----------
        print("== 3. 安全校验（三条都拒绝、且都不入库）==")
        before = col.db.scalar("select count() from notes") or 0

        st, _ = http_json("POST", f"{base}/import",
                          body={"code": "000000", "apkg_b64": blob_b64})
        check("配对码错误 → 403", st == 403, f"status={st}")

        st, _ = http_json("POST", f"{base}/import",
                          body={"code": CODE, "apkg_b64": blob_b64},
                          origin="https://evil.example.com")
        check("Origin 非本站 → 403", st == 403, f"status={st}")

        st, _ = http_json("POST", f"{base}/import",
                          body={"code": CODE, "apkg_b64": blob_b64}, origin=None)
        check("缺 Origin → 403", st == 403, f"status={st}")

        # 伪造 Host（DNS rebinding 场景）
        conn = HTTPConnection("127.0.0.1", bridge.port, timeout=10)
        payload = json.dumps({"code": CODE, "apkg_b64": blob_b64}).encode()
        conn.request("POST", "/import", body=payload, headers={
            "Host": "evil.example.com", "Origin": ALLOWED_ORIGIN,
            "Content-Type": "application/json", "Content-Length": str(len(payload)),
        })
        rebind_st = conn.getresponse().status
        conn.close()
        check("Host 非本机 → 403（挡 DNS rebinding）", rebind_st == 403, f"status={rebind_st}")

        st, _ = http_json("POST", f"{base}/import",
                          body={"code": CODE, "apkg_b64": base64.b64encode(b"not a zip").decode()})
        check("非 zip 内容 → 400", st == 400, f"status={st}")

        mid = col.db.scalar("select count() from notes") or 0
        check("以上拒绝均未入库", mid == before, f"{before} -> {mid}")
        check("拒绝计数已记录", bridge.stats["rejected"] >= 5, str(bridge.stats))

        # ---------- 4. 正常链路 ----------
        print("== 4. 正常链路（子线程发请求 / 主线程导入）==")
        holder: dict = {}
        t = threading.Thread(target=post_in_thread, args=(
            f"{base}/import", {"code": CODE, "apkg_b64": blob_b64, "deck": "医考折叠"}, holder))
        t.start()
        deadline = time.time() + 40
        pumped = 0
        while t.is_alive() and time.time() < deadline:
            pumped += bridge.pump()
            time.sleep(0.02)
        t.join(timeout=5)

        check("请求已返回", "res" in holder or "err" in holder, str(holder))
        if "err" in holder:
            check("正常导入成功", False, holder["err"])
        else:
            st, body = holder["res"]
            after = col.db.scalar("select count() from notes") or 0
            check("HTTP 200", st == 200, f"status={st} body={body}")
            check("返回导入张数", (body.get("notes") or 0) > 0, str(body))
            check(f"集合真的多了卡片（{before} -> {after}）", after > before, f"{after}")
            check("主线程执行了导入（pump>0）", pumped > 0, f"pumped={pumped}")
            check("笔记类型已建出", any("医考折叠" in m["name"] for m in col.models.all()),
                  str([m["name"] for m in col.models.all()]))

        # ---------- 5. 临时文件 ----------
        print("== 5. 临时包清理 ==")
        leaked = [p for p in paths_seen if os.path.exists(p)]
        for p in paths_seen:
            cleanup(p)
        check("导入后临时包已删除", not leaked, f"残留={leaked}")
    finally:
        bridge.stop()
        col.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败（临时收藏夹已删除，未触碰真实数据）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
