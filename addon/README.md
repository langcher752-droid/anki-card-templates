# Anki 小工坊 · 模板一键安装（Anki 插件）

把本仓库的 11 套模板一次性装进你的 Anki 集合，省掉「新建笔记类型 → 逐个加字段 →
粘贴正反面模板 → 粘贴 CSS」这一串手工步骤。

```
工具 → Anki 小工坊 → 安装卡片模板…   勾选要装的模板
工具 → Anki 小工坊 → 打开模板展厅     到浏览器里看每套模板的真实效果
```

## 行为约定

- **只新增，不覆盖。** 已存在同名笔记类型时直接跳过，绝不改动你已有的笔记类型。
  改错别人的笔记类型是这类「一键安装」插件最容易造成的破坏。
- **不联网、不需要账号、不上报任何东西。** 安装过程完全本地。
- **装完就是普通笔记类型。** 卸载插件后模板照常存在，可自由修改。

## 安装

### 从 AnkiWeb 安装（发布后）

在 Anki 里点「工具 → 插件 → 获取插件」，填入插件的编号。

### 从文件安装（现在就能用）

1. 取 `dist/anki-studio-templates-<版本>.zip`（用 `python3 addon/build_addon.py` 生成）
2. Anki →「工具 → 插件 → 从文件安装…」→ 选这个 zip
3. 重启 Anki

## 开发

```bash
# 1. 重新生成模板数据（模板改了之后必须跑）
#    在模板源项目里执行：
python3 scripts/build_addon_templates.py

# 2. 在临时收藏夹里跑真实验证（95 项断言，不碰你的真实收藏夹）
python3 addon/test_installer.py

# 3. 打包成 AnkiWeb 可上传的 zip
python3 addon/build_addon.py
```

### 目录

| 文件 | 作用 |
|---|---|
| `anki_studio_templates/__init__.py` | 菜单、弹窗、提示（Qt 部分） |
| `anki_studio_templates/installer.py` | 写集合的纯逻辑，不依赖 Qt，可单独测 |
| `anki_studio_templates/templates.json` | 模板数据（**生成物**，不要手改） |
| `anki_studio_templates/manifest.json` | 插件清单，`package` 编号由 AnkiWeb 分配 |
| `test_installer.py` | 借 Anki 自带后端在临时集合里验证安装结果 |
| `build_addon.py` | 打包成根目录布局的 zip |

### 为什么逻辑要拆成两个文件

写集合的代码是有破坏性的，必须能被单独测；混在含 Qt 导入的模块里就只能靠手点。
拆开之后 `test_installer.py` 能直接用 Anki 自带的 `anki` 包开一个**临时集合**跑完整流程，
不需要启动 GUI，也不会碰到用户的真实数据。

### 已验证

按 **Anki 26.9.2** 的 API 编写并核对（`ModelManager` 的 `new` / `new_field` /
`add_field` / `new_template` / `add_template` / `add` / `by_name` 均已确认存在），
并在该版本的临时收藏夹里跑通 95 项断言（字段、模板、CSS、cloze 类型标记、幂等性、真实建卡）。

## 授权

模板设计与插件代码由 LC Learning（[Anki 小工坊](https://www.lanche.website)）创作，
以 **CC BY 4.0** 发布。转载或再分发请署名并链接回
<https://www.lanche.website>。详见仓库根的 [NOTICE.md](../NOTICE.md)。

与 Anki 官方（Ankitects）无隶属关系。
