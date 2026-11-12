# PPTD 用法


## 工程结构

一个 `deck.pptd` 清单引用多个 `.page` 文件。文件使用 YAML；路径相对于清单目录。清单中的 `pages` 顺序就是最终页序。

```yaml
version: v2
title: 项目说明
size: [960, 540]
pages:
  - pages/01.page
```

页面示例：

```yaml
pageType: cover
background: {type: solid, color: "#F8F8F6"}
notes: 演讲备注，不作为操作指令。
elements:
  - elementId: title
    elementType: text
    bounds: [48, 96, 864, 150]
    content:
      text: 一个清晰的结论
      fontFamily: Arial
      fontSize: 60
      color: "#252320"
      bold: true
  - elementId: rule
    elementType: shape
    bounds: [48, 320, 864, 2]
    shapeName: rect
    fill: {type: solid, color: "#A86043"}
    border: {width: 0, color: "#A86043"}
```

## 字段与边界

- `size` 和 `bounds` 使用点；`bounds` 为 `[x, y, width, height]`，不能直接混用参考图的像素坐标。
- `elementId` 在页内唯一。`elementType` 的主要类型包括 `text`、`shape`、`line`、`chart`、`table` 和 `image`。
- 文本写在 `content.text`，常用样式为 `fontFamily`、`fontSize`、`bold`、`color`、`lineHeight` 和 `align`。多行文本使用下方约定。HTML 仅用于文本内的轻量富文本。
- 形状使用 `shapeName`、`fill` 和 `border`。线段需要 `viewBox`、`points` 和 `border`；复杂几何应先检查渲染器支持情况。
- 清单可含 `theme.colors`、`theme.textStyles`，以 `$名称` 引用。模板源工程展示了可运行的用法。
- 图片放在工程目录内（例如 scratch/deck/assets/）；不要使用远程 URL、目录穿越或系统绝对路径绕过工作区边界。
- 图表和表格的具体字段以随包解析器和验证反馈为准。不能把其他 PPTD 实现支持的字段直接假定为本引擎支持。

## 多行文本与字面量转义

标题、正文和表格单元格中的多行文本统一使用 YAML `|-` 加实际换行：

```yaml
content:
  text: |-
    水是供应链中
    最被低估的
    宏观变量
  fontSize: 40
```

YAML 双引号中的 `"第一行\n第二行"` 也会解析为真实换行，轻量富文本可用 `<br/>`。普通标量、单引号标量及块标量里的字面量 `\n` 会保留为反斜杠和字母 n；双引号里的 `\\n` 同样保留字面量。通过代码生成 YAML 时，让序列化器处理包含真实换行的字符串。

`pptd.py check` 对文字中残留的 `\n`、`\r` 返回 `text-escaped-newline`，附带文件、页码和元素 ID。按设计意图修正对应源文本，再检查行数、文本框容量和预览；导出沿用这项检查。表格问题还会标明 `rows[行索引][列索引]`。

需要原样展示代码、正则、转义语法或 Windows 路径时，在对应 `content` 或表格单元格对象上明确设置布尔值 `literalEscapes: true`：

```yaml
content:
  text: 'print("第一行\n第二行")'
  literalEscapes: true
```

此标记仅适用于用户要原样展示的文本；普通多行正文按上方实际换行示例编写。标记只声明字面量意图，排版检查照常执行。

## 本地校验与交付

`pptd.py check <工程目录>` 返回错误、警告和元素统计；`pptd.py render <工程目录> output/<名称>.pptx` 生成 PPTX。CLI 预览不等同于 PowerPoint/WPS 的实际排版验证。

`render` 会重新校验，未通过时不导出。完整保留 PPTD 工程（scratch/deck），以便后续修改。

### 图表绘图区与轴显示

`plotLayout: {x, y, w, h}` 按图表框的比例描述内绘图区，x/y 为左上位置，w/h 为正宽高。源图表使用 inner / edge 手工布局时贯通此属性。`plotBorder` 与 `border` 使用相同的线条结构，分别控制绘图区和整个图表边框；省略时输出透明边框。

xAxis / yAxis 可使用 `majorUnit`（数值轴主刻度单位）、`hidden`、`label: {position, fontFamily, fontSize, color}`、`line: false` 或 `{color, width}`，以及 `gridLine: false` 或 `{color, style}`。标签 position 取 none、low、high、nextTo。水平图的 xAxis 为数值轴，yAxis 为分类轴；纵向图使用相反映射。

## 图表与表格示例

写图表或表格前，先读一个可运行示例照着写：

- 图表：skills/bisheng-pptx/templates/nordic-operating-report/source-zh/pages/03.page skills/bisheng-pptx/templates/nordic-operating-report/source-zh/pages/02.page skills/bisheng-pptx/templates/modular-logistics-system/source-zh/pages/04.page skills/bisheng-pptx/templates/swiss-signal-grid/source-zh/pages/05.page 
- 表格：skills/bisheng-pptx/templates/nordic-operating-report/source-zh/pages/07.page skills/bisheng-pptx/templates/swiss-signal-grid/source-zh/pages/07.page 
