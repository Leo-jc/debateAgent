# 辩论 Agent Web UI 设计文档

日期：2026-09-02
前置：CLI 版已完成（见 `2026-09-02-debate-agent-design.md`）。本设计在其基础上加可视化界面，前端流式输出。

## 目标

浏览器里发起辩论、实时观看正反方流式发言与裁判判定、结束后阅读并下载战报。CLI 入口保持不变。

## 技术选型

| 项 | 决定 |
|---|---|
| 后端 | FastAPI + uvicorn（唯一新依赖），复用现有 LangGraph 图 |
| 前端 | 原生 HTML/JS/CSS 单页，零构建，FastAPI 静态托管 |
| 流式 | SSE（`EventSource`，浏览器原生自动重连） |
| 事件传递 | 节点内 emit → LangGraph `stream_mode="custom"` → invoke 线程 → 队列 → SSE |

## 架构与事件流

```
浏览器 (static/index.html + app.js)
   │  POST /api/debate {topic}        → 返回 debate_id
   │  GET  /api/stream/{debate_id}    → SSE 事件流
   ▼
FastAPI (webapp.py)
   │  后台线程 graph.stream(topic, stream_mode="custom")，事件进内存队列
   ▼
LangGraph 图（编排零改动；节点内 print 改为 emit）
```

事件类型（SSE `event:` + JSON `data:`）：
- `speech_start` `{"side","round"}` / `speech_delta` `{"side","round","text"}` / `speech_end` `{"side","round"}`
- `judge` `{"round","status","conceded_side","reason"}`
- `split_done` `{"pro","con"}`
- `done` `{"end_reason","report_path"}`
- `error` `{"message"}`

## 代码结构与改动点

```
DebateAgent/
├── main.py              # 不变
├── webapp.py            # 新增：FastAPI 应用 + SSE + 线程/状态管理
├── events.py            # 新增：emit() 双模式（CLI 打印 / LangGraph writer）
├── nodes/debater.py     # 改造：print → emit
├── nodes/judge.py       # 改造：print → emit
├── nodes/summarizer.py  # 微改：完成后 emit done
├── graph.py / llm.py / config.py / state.py   # 不变
└── static/
    ├── index.html
    └── app.js
```

**events.py**：`emit(event: dict)` —— CLI 模式按事件类型打印（行为与现在一致），图流式模式经 `langgraph.config.get_stream_writer()` 发自定义事件。六类事件如上。

**webapp.py**：
- `POST /api/debate`：辩题非空校验 → 生成 debate_id → daemon 线程跑图 → 事件写入 `dict[id]` 的队列
- `GET /api/stream/{id}`：`StreamingResponse` 逐事件推 SSE；done/error 后关闭
- 状态字典管理生命周期；刷新重连时回放队列中已积压事件再续流
- 同时只允许一个辩论（串行，避免限流），重复请求返回 409

## 前端交互

- 单页上下两区：输入区（辩题 + 开始按钮）/ 直播区（拆题横条 + 发言卡片 + 裁判判定条 + 战报区）
- 开始后按钮禁用；辩论中显示状态点
- 自动滚动到底部；用户上滚则暂停，回底恢复
- `speech_delta` 用 `requestAnimationFrame` 批量追加
- 战报：`<pre>` 原始 md 展示 + 下载按钮
- error 事件 → 顶部红条，输入恢复

## 视觉设计：「对峙线」— 华语辩论赛场

页面唯一任务：看一场辩论实时发生。母题取自华语辩论赛：正红反蓝传统、判词用宋体、认输盖印。字体分工编码「谁在说话」——功能性而非装饰。

### 色板

| 名 | 值 | 用途 |
|---|---|---|
| 云白 | `#F6F5F1` | 底色 |
| 玄墨 | `#21201C` | 正文/判词 |
| 朱砂 | `#C3272B` | 正方（deepseek-v4-pro） |
| 靛青 | `#2F5A8F` | 反方（glm-5.3-flash） |
| 判官灰 | `#8A867C` | 裁判/脚手架 |
| 纸影 | `#E3DFD6` | 边线/阴影 |

### 字体三角色

- **Noto Serif SC（宋体）**：裁判判词 + 战报（书面、权威）
- **Noto Sans SC（黑体）**：辩手流式发言（口语、实时）
- **JetBrains Mono（等宽）**：轮次编号、状态、▊光标

### 布局：中央对峙线

一条垂直中线贯穿直播区；正方发言靠左、反方靠右、裁判判定卡骑在中线上。

```
│ 辩题 [____________]  [开始辩论]        │
│        正方命题 ┃ 反方命题  ← 拆题横条   │
│ 朱砂卡片         ┃                     │
│ 【第1轮·正方】   ┃                     │
│ 流式文本▊        ┃                     │
│                 ┃ ⚖ 第1轮·继续         │
│                 ┃      靛青卡片        │
│                 ┃ 【第1轮·反方】流式▊   │
│  ═══════════════ ┗━━ 战报（宋体判词区）  │
```

### 签名元素：认输印章

裁判判 concede 时，判定卡盖一枚旋转 8° 的方形朱印「负」，1.6→1 缩放落下（全页唯一编排动效）。认输方为正方盖朱砂印、反方盖靛青印。其余动效仅流式光标与中线向下生长。

### 与原第 3 节的两处修订

1. 气泡颜色蓝橙 → 朱砂/靛青（跟随华语辩论正红反蓝传统）
2. 圆形聊天气泡 → 带色边条的卡片（赛场发言席而非聊天软件）

## 错误处理

- 辩题空：前端 + 后端双重校验，400
- 已有辩论运行中：409，前端提示
- 图中途异常：线程 catch → `error` 事件 → SSE 关闭，页面显示错误
- SSE 断开（刷新/关页）：辩论线程继续跑完；重连后回放积压事件续流
- 浏览器兼容：`EventSource` 现代浏览器原生支持

## 明确不做

- 历史辩论列表页
- 战报 Markdown 精渲染（`<pre>` 即可）
- WebSocket、多辩论并行、用户系统

## 测试

1. 单测：`events.py` 双模式、`webapp.py` 状态管理（409/回放）、节点 emit 事件序列（mock）
2. SSE 冒烟：`uvicorn webapp:app` → 浏览器完整跑一场：流式卡片 → 裁判 → 战报 + 下载
3. 断线重连：辩论中刷新页面恢复显示
4. CLI 回归：`py main.py "辩题"` 输出与改造前一致
5. pytest 全量回归
