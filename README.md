# Anki 卡片模板集 · Anki Card Templates

11 套原创 Anki 卡片模板，**双击导入即用**，含 4 种互动题型（选择 / 填空输入 / 排序 / 配对）。
每套都有 `.apkg` 成品包与可粘贴的模板源码，不依赖任何插件。

> 由 [Anki 小工坊](https://www.lanche.website/templates)（AI 自动制卡工具）设计并开源。
> 模板展厅可以免登录直接翻看每套模板的真实效果：<https://www.lanche.website/templates>

---

## 快速开始

### 方式一：导入成品包（推荐）

从 [`decks/`](decks/) 里挑一套，下载 `.apkg` 后：

- **电脑**：Anki →「文件 → 导入」→ 选中文件
- **安卓**：在文件管理器里点开 `.apkg` → 选择 AnkiDroid
- **iPhone / iPad**：在「文件」里分享 → AnkiMobile

导入后自带示例卡片，可以直接看到这套模板长什么样。

### 方式二：手动安装模板（想自己改样式）

1. Anki →「工具 → 管理笔记类型 → 添加」，新建一个笔记类型
2. 按 `templates/<id>/README.txt` 里列出的字段添加字段
3. 把 `front.html` / `back.html` 分别粘进「正面模板」「背面模板」
4. 把 `style.css` 粘进「样式」

---

## 模板清单

| 模板 | 说明 | 成品包 | 授权 |
|---|---|---|---|
| 现代简约 Modern QA | 一问一答，正文层级清晰，通用性最好 | [decks/modern_qa.apkg](decks/modern_qa.apkg) | CC BY 4.0 |
| 学术雅致 Elegant Vocab | 带音标、词性、词根与例句的词汇卡 | [decks/elegant_vocab.apkg](decks/elegant_vocab.apkg) | CC BY 4.0 |
| 荧光高亮 Cloze Highlight | 挖空后以荧光色标出，适合背句子与法条 | [decks/cloze_highlight.apkg](decks/cloze_highlight.apkg) | CC BY 4.0 |
| 极简代码 Code Craft | 等宽字体与代码块样式，适合编程类记忆 | [decks/code_craft.apkg](decks/code_craft.apkg) | CC BY 4.0 |
| 医考折叠 Med Foldout | 答案分层折叠，先看大类再展开细节 | [decks/med_foldout.apkg](decks/med_foldout.apkg) | CC BY 4.0 |
| 康奈尔双栏 Cornell Divided | 左线索右笔记的双栏结构 | [decks/cornell_divided.apkg](decks/cornell_divided.apkg) | CC BY 4.0 |
| 纸质荧光 Marker Highlight | 模拟纸质荧光笔的重点标注观感 | [decks/marker_highlight.apkg](decks/marker_highlight.apkg) | CC BY 4.0 |
| 互动 · 选择题 Choice | 在卡片里直接作答并即时判分 | [decks/interactive_choice.apkg](decks/interactive_choice.apkg) | CC BY 4.0 |
| 互动 · 填空题 Type-in | 打字输入答案，自动比对 | [decks/interactive_typein.apkg](decks/interactive_typein.apkg) | CC BY 4.0 |
| 互动 · 排序题 Order | 拖拽排出正确顺序 | [decks/interactive_order.apkg](decks/interactive_order.apkg) | CC BY 4.0 |
| 互动 · 配对题 Match | 左右两列配对 | [decks/interactive_match.apkg](decks/interactive_match.apkg) | CC BY 4.0 |

完整字段与授权信息见 [`decks/MANIFEST.json`](decks/MANIFEST.json)。

---

## 一键安装插件（可选）

不想手动建笔记类型的话，用配套插件一次装完 11 套：

```
工具 → Anki 小工坊 → 安装卡片模板…
```

插件源码在 [`addon/`](addon/)。**只新增、不覆盖**（已有同名笔记类型会跳过），
不联网、不需要账号，装完就是普通笔记类型，卸载插件后模板照常存在。
已在 Anki 26.9.2 的临时收藏夹里跑通 95 项断言（字段 / 模板 / CSS / cloze 类型 / 幂等 / 建卡）。

---

## 互动题型怎么用

四种互动模板共用一套运行时（已内联进卡片，**不需要装插件**）。出题时按下面的约定写字段：

| 题型 | 字段 | 书写约定 |
|---|---|---|
| 选择题 | `Options` | 每行一个选项，**正确项行首加 `*`** |
| 填空题 | `Front` | 把要输入的部分写成 `[[答案]]` |
| 排序题 | `Items` | 每行一项，**按正确顺序**书写（卡片会打乱） |
| 配对题 | `Pairs` | 每行一组，左右用 ` :: ` 分隔 |

其中只有选择题是「点选即判分」，其余三种都以「先作答 → 再翻面核对」的方式工作，
这样复习时仍然是主动回忆，而不是识别。

---

## 设计原则

这些模板不是单纯的皮肤，它们对「卡片应该多小」有明确立场：

- **一张卡只考一个点。** 答错时你能立刻知道错在哪一处。
- **答案要短。** 超过三行，复习就变成阅读理解。
- **不给多余提示。** 正面提示越多，复习越接近「认出来」而不是「想起来」。
- **样式跨端一致。** 所有样式内联在卡片里，手机端不会因为缺插件而显示异常。

---

## 授权与署名

本仓库的模板设计与源码由 **LC Learning（Anki 小工坊）** 创作，以
**[Creative Commons Attribution 4.0 International（CC BY 4.0）](LICENSE)** 发布。

你可以自由使用、修改、再分发（包括商用），**唯一的要求是署名**：

> 模板设计：LC Learning · Anki 小工坊 — <https://www.lanche.website>

导出的卡片页脚已内置这行署名，属于授权要求的一部分，**请勿移除**。
详见 [NOTICE.md](NOTICE.md)。

### 第三方作品

本仓库**不包含** [Prettify](https://github.com/pranavdeshai/anki-prettify)（作者
[@pranavdeshai](https://github.com/pranavdeshai)，MIT 许可）。本站也支持 Prettify 系列模板，
但那是第三方创作，仅在站内提供并按 MIT 保留其署名。

---

## 关于 Anki

本项目与 Anki 官方（Ankitects）无隶属关系。Anki 是 Ankitects 的商标。
本仓库提供的模板是**独立的笔记类型定义**，导入后即是普通的本地卡片，可脱离本站长期使用。

---

## English summary

Eleven original Anki card templates (plus four interactive card types: multiple choice,
type-in, ordering, matching), ready to import. Each ships as an `.apkg` in [`decks/`](decks/)
and as raw front/back/CSS source in [`templates/`](templates/).

No add-ons required — all styles and interactive runtimes are inlined into the cards.

Licensed **CC BY 4.0** by LC Learning (Anki 小工坊). Attribution is required:
please credit "LC Learning · Anki 小工坊" and link to <https://www.lanche.website>.

Built with the AI card generator at <https://www.lanche.website/AI-Anki>.
