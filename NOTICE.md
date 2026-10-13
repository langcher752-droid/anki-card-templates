# 授权说明 / Notice

## 一、本仓库的内容

| 内容 | 位置 | 作者 | 授权 |
|---|---|---|---|
| 模板设计（正面/背面模板 + CSS） | `templates/`、`decks/*.apkg` | LC Learning（Anki 小工坊） | CC BY 4.0 |
| 生成脚本 | 上游项目 `scripts/build_share_decks.py` | LC Learning | CC BY 4.0 |
| 示例卡片内容 | `decks/*.apkg` 内置 | LC Learning | CC BY 4.0 |

## 二、你必须做的事：署名

CC BY 4.0 允许你自由使用、修改、再分发（含商业用途），条件是**给出适当署名**。

推荐写法：

```
模板设计：LC Learning · Anki 小工坊 — https://www.lanche.website
```

### 为什么导出的卡片里有一行页脚

每张卡的样式里内置了一行：

```html
<div class="license-foot">Design: CC-BY-4.0 | LC Learning</div>
```

这不是装饰，是**许可条款的履行方式**——模板的使用者可能早已不知道卡片来自哪里，
页脚是唯一能随卡片一起传播的署名。请保留它。

## 三、明确不在本仓库内的第三方作品

### Prettify（MIT）

- 项目：<https://github.com/pranavdeshai/anki-prettify>
- 作者：Deshai Pranav（[@pranavdeshai](https://github.com/pranavdeshai)）
- 许可：MIT License, Copyright (c) 2022 Deshai Pranav

[Anki 小工坊](https://www.lanche.website/templates) 站内也提供 Prettify 系列（极简 / 北欧 /
暗夜 / 填空），但**那些是第三方作品，不属于本仓库**，因此这里不打包、不提供源码副本。
站内使用时按其 MIT 许可保留了原始署名。

顺带说明：MIT 与 CC BY 4.0 都允许商用，区别在于 MIT 不强制署名、CC BY 4.0 强制署名。
本仓库选择 CC BY 4.0 是有意的——模板会被复制到各种地方，署名是唯一能让来源跟着走的方式。

## 四、模板的边界

- 这些模板是**独立创作**的笔记类型定义，不是从任何现成模板改的。
- 与 Anki 官方（Ankitects）无隶属关系；Anki 是 Ankitects 的商标。
- 示例卡片里的学科内容（医学、编程、英语词汇等）仅作模板演示，不构成任何专业建议。
