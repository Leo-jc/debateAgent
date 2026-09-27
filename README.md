# DebateAgent · 多模型辩论 Agent

基于 LangGraph 的多角色辩论系统：拆题 agent 把辩题拆成正反命题，两个由**不同模型**扮演的辩手循环攻防，裁判 agent 每轮判定继续或认输，最后由总结 agent 生成战报 Markdown。支持 CLI 终端运行和 Web 实时直播两种形态。

## 架构

```
START → splitter（拆题）→ pro（正方）→ con（反方）→ judge（裁判）──┐
                                                      ↑           │
                                                      └─ continue ┘
                                                            │ concede / 达到最大轮数
                                                            ↓
                                                       summarizer（战报）→ END
```

一轮 = 正方发言 + 反方发言 + 裁判判定。裁判判 `continue` 则进入下一轮；判某方 `concede`（认输）或达到 `MAX_ROUNDS` 则进入总结节点。

## 项目结构

```
├── main.py              # CLI 入口：python main.py "辩题"
├── webapp.py            # FastAPI Web 服务：发起辩论 + SSE 直播
├── graph.py             # StateGraph 组装与条件边（循环/终止路由）
├── state.py             # DebateState 共享状态、MAX_ROUNDS / MAX_SPEECH_CHARS
├── config.py            # 模型角色分配、网关配置
├── llm.py               # 统一 LLM 封装：chat / chat_stream / parse_json，带重试
├── events.py            # 事件发射抽象：CLI 打印 / LangGraph custom stream 双模式
├── nodes/
│   ├── splitter.py      # 拆题：辩题 → 正反两个对立命题（JSON）
│   ├── debater.py       # 辩手节点工厂：正反共用，流式发言
│   ├── judge.py         # 裁判：判定 continue / concede
│   └── summarizer.py    # 总结：生成战报写入 output/
├── static/              # 前端（原生 JS + SSE）
│   ├── index.html       # 「对峙线」直播界面
│   └── app.js           # EventSource 消费 SSE，渲染打字机效果
├── tests/               # pytest 单测（mock LLM，不需要真实 key）
└── output/              # 战报输出目录：日期-辩题.md
```

## 快速开始

### 1. 配置

在项目根目录创建 `.env`：

```ini
LLM_API_KEY=你的key
# 可选，默认为火山网关地址
LLM_BASE_URL=https://.../v1
```

单一 OpenAI 兼容网关，一个 key 覆盖全部角色。`config.py` 中的角色分配可按需调整：

| 角色 | 模型（默认） |
|---|---|
| 正方辩手 | `deepseek-v4-pro` |
| 反方辩手 | `glm-5.3-flash` |
| 拆题 agent | `glm-5.3-flash` |
| 裁判 | `glm-5.3-flash` |
| 总结 agent | `deepseek-v4-pro` |

### 2. 安装依赖

```bash
pip install langgraph openai python-dotenv fastapi uvicorn
```

（开发测试另需 `pytest`，要求 Python 3.12+，项目在 3.14 下开发。）

### 3a. CLI 运行

```bash
python main.py "人性本善还是本恶"
```

终端流式打印双方发言与裁判判定，结束后战报保存至 `output/`。

### 3b. Web 直播

```bash
uvicorn webapp:app
# 浏览器打开 http://127.0.0.1:8000
```

输入辩题点击「开始辩论」，页面以对峙线布局实时直播：正方朱砂色、反方靛青色，发言逐字流式输出，裁判判定卡骑在中线上，认输时盖「负」印章，结束后可下载战报 `.md`。

## 关键设计

### 双模式事件流（events.py）

节点内不直接 `print`，统一调 `emit()`：

- **CLI**（`graph.invoke`）：不在图流式上下文中，事件按类型打印到终端；
- **Web**（`graph.stream(stream_mode="custom")`）：事件经 `get_stream_writer()` 透传给 webapp，再由 SSE 推给浏览器。

同一套节点代码，两种运行形态零改动。

### 容错与降级

| 环节 | 策略 |
|---|---|
| LLM 调用 | 失败自动重试 2 次（指数退避 1s→2s） |
| 拆题 | JSON 解析失败重试 2 次，仍失败退出（唯一无降级的步骤） |
| 辩手 | 流式失败则此轮弃权，记 `[发言失败，此轮弃权]`，辩论继续 |
| 裁判 | 解析失败默认 `continue`（宁可多辩不误停）；`concede` 但缺认输方也视为异常继续 |
| 发言长度 | 超过 `MAX_SPEECH_CHARS`（800 字）截断兜底 |

### GLM 网关适配（llm.py）

GLM 系列默认开启思考模式，`reasoning_content` 会占用 `max_tokens` 把正文挤空，因此 GLM 请求强制使用较大的 `max_tokens`（8192）兜底；流式增量只取 `delta.content`，忽略思考增量。

### Web 并发控制

同时只允许一场辩论运行（避免 API 限流），重复请求返回 409。SSE 支持断线重连：重连时先回放已积压事件再实时跟随。

## 测试

```bash
pytest
```

覆盖：拆题成功/围栏容忍/重试退出、裁判 continue/concede/异常默认三分支、条件边路由走向、发言截断与失败降级、发言规则切换、events 双模式、webapp 状态管理（400/409/404、SSE 重连回放）、全图事件序列。全部 mock LLM，无需真实 key。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/debate` | 发起辩论 `{"topic": "..."}`，返回 `debate_id`；有辩论进行中返回 409 |
| GET | `/api/stream/{id}` | SSE 事件流：`split_done` / `speech_start` / `speech_delta` / `speech_end` / `judge` / `done` / `error` |
| DELETE | `/api/debate/{id}` | 清理已结束的辩论，允许发起下一场 |
