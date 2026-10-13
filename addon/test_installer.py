#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**临时收藏夹**里真实验证模板安装器（不启动 GUI，不碰用户数据）。

为什么这么测
------------
「一键安装笔记类型」是往用户集合里写东西的操作。靠肉眼点一遍不算验证：
字段顺序、cloze 类型标记、CSS 是否落库，任何一项错了用户都会在很久以后才发现。
这里直接借用 **Anki 自带的 anki 包**（/Applications/Anki.app 里的 app_packages）
开一个临时集合，把安装逻辑跑完并逐项断言。

临时集合用完即删，与 ~/Library/Application Support/Anki2 下的真实收藏夹无关。

用法
    python3 addon/test_installer.py
（用系统 python3 即可：Anki 26 与 3.13 的字节码 magic 一致。）
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP_PACKAGES = "/Applications/Anki.app/Contents/Resources/app_packages"
HERE = Path(__file__).resolve().parent

if APP_PACKAGES not in sys.path:
    sys.path.insert(0, APP_PACKAGES)

from anki.collection import Collection  # noqa: E402

sys.path.insert(0, str(HERE / "anki_studio_templates"))
from installer import install_templates, load_templates  # noqa: E402

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


def main() -> int:
    data = load_templates()
    tpl_list = data["templates"]
    ids = [t["id"] for t in tpl_list]
    print(f"== 模板清单：{len(ids)} 套 ==")

    tmp = tempfile.mkdtemp(prefix="anki_installer_test_")
    col = Collection(os.path.join(tmp, "collection.anki2"))
    try:
        before = len(col.models.all())
        added, skipped = install_templates(col, ids)
        after = len(col.models.all())

        print("== 安装 ==")
        check(f"全部安装成功（{len(added)} 套）", len(added) == len(ids), f"added={added} skipped={skipped}")
        check("无跳过", skipped == [], f"skipped={skipped}")
        check(f"笔记类型数量 +{len(ids)}", after - before == len(ids), f"{before} -> {after}")

        print("== 逐套核对字段 / 模板 / CSS / cloze ==")
        for t in tpl_list:
            m = col.models.by_name(t["name"])
            check(f'{t["id"]} 存在', m is not None)
            if m is None:
                continue
            names = [f["name"] for f in m["flds"]]
            check(f'{t["id"]} 字段一致', names == t["fields"], f'{names} != {t["fields"]}')
            check(f'{t["id"]} 模板数=1', len(m["tmpls"]) == 1)
            if m["tmpls"]:
                tmpl = m["tmpls"][0]
                check(f'{t["id"]} 正面模板落库', tmpl["qfmt"] == t["qf"], f'len {len(tmpl["qfmt"])} vs {len(t["qf"])}')
                check(f'{t["id"]} 背面模板落库', tmpl["afmt"] == t["af"])
            check(f'{t["id"]} CSS 落库', m["css"] == t["css"], f'len {len(m.get("css",""))} vs {len(t["css"])}')
            want_cloze = bool(t.get("cloze"))
            check(f'{t["id"]} cloze 类型标记={want_cloze}', bool(m["type"] == 1) == want_cloze, f'type={m["type"]}')

        print("== 幂等：再装一次应全部跳过、不新增 ==")
        added2, skipped2 = install_templates(col, ids)
        check("第二次不再新增", added2 == [], f"added={added2}")
        check("第二次全部跳过", len(skipped2) == len(ids), f"skipped={len(skipped2)}/{len(ids)}")
        check("笔记类型总数不变", len(col.models.all()) == after)

        print("== 可用性：每套模板真加一张卡，确认能生成卡片 ==")
        sample = {
            "modern_qa": ("Front", "Back"),
            "elegant_vocab": ("Front", "Back"),
            "cloze_highlight": ("Text", "Back Extra"),
            "code_craft": ("Front", "Back"),
            "med_foldout": ("Front", "Back"),
            "cornell_divided": ("Front", "Back"),
            "marker_highlight": ("Front", "Back"),
            "interactive_choice": ("Front", "Back"),
            "interactive_typein": ("Front", "Back"),
            "interactive_order": ("Front", "Back"),
            "interactive_match": ("Front", "Back"),
        }
        for t in tpl_list:
            m = col.models.by_name(t["name"])
            note = col.new_note(m)
            f1, f2 = sample.get(t["id"], ("Front", "Back"))
            note[f1] = "测试正面" if not t.get("cloze") else "这是一个 {{c1::测试}} 填空"
            note[f2] = "测试背面"
            try:
                col.add_note(note, 1)
                ok = note.id != 0
            except Exception as exc:  # noqa: BLE001
                ok = False
                check(f'{t["id"]} 加卡失败', False, f"{type(exc).__name__}: {exc}")
                continue
            if ok:
                check(f'{t["id"]} 能加卡', True)
        check("卡片已生成", col.db.scalar("select count() from cards") >= len(tpl_list),
              f'cards={col.db.scalar("select count() from cards")}')
    finally:
        col.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败（临时收藏夹已删除，未触碰真实数据）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
