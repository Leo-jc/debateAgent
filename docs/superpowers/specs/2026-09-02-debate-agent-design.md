# 辩论 Agent 设计文档

日期：2026-09-02

## 目标

输入任意辩题，主 agent 拆成正反命题后交给两个子 agent（不同模型）多轮辩论；一方认输或达到最大轮数（默认 12）时结束，主 agent 输出完整战报 Markdown。全程 CLI 使用，不使用 git。

## 技术选型

| 项 | 决定 |
|---|---|
| 框架 | LangGraph（`StateGraph` + 条件边实现循环） |
| 模型接入 | 单一网关：`https://st8tp3ajl0df3n8b8l8qu.apigateway-cn-beijing.volceapi.com/v1`（OpenAI 兼容），一个 api-key 覆盖全部角色 |
| 正方 / 总结 | `deepseek-v4-pro` |
| 反方 / 拆题 / 裁判 | `glm-3-flash` |
| API key | 写入 `.env`（`LLM_API_KEY`），网关地址写入 `config.py` 或 `.env`（`LLM_BASE_URL`） |
| 依赖 | `langgraph`、`openai`、`pydantic`（已装 openai/pydantic；不引 langchain 全家桶） |
| 入口 | `python main.py "辩题"`，辩手发言**流式输出**到终端（打字机效果），裁判/拆题等内部步骤不流式 |

## 架构与数据流

```
输入辩题 (CLI)
   │
   ▼
主 Agent (glm-3-flash) ── 拆题：一次 LLM 调用 → {"pro": "...", "con": "..."}
   │
   ▼
LangGraph 状态机循环：
   正方 Agent (deepseek-v4-pro) 发言 → 反方 Agent (glm-3-flash) 发言 → 裁判 (glm-3-flash) 判定
   │                                          │
   │◄──── 裁判说 continue 且轮数 < 20 ◄───────┤
   ▼
裁判判 concede 或 轮数 = 20
   │
   ▼
主 Agent (deepseek-v4-pro) 生成战报 → output/日期-辩题.md
```

- 双方发言时都能看到全部历史发言（自己的 + 对方的），反方/正方均须回应对方上一轮。
- 轮数与认输都是 judge 之后条件边的判断条件。

## 角色 Prompt 设计

### 正方 Agent（deepseek-v4-pro）system prompt 要点
- 角色：辩论正方辩手，立场 = 拆出的正方命题
- 规则：每次发言聚焦 1-2 个核心论点；必须直接回应反方上一轮反驳（第一轮除外）；不得修改立场；不许放弃性表述
- 输出：纯辩论正文 300-500 字，无元信息

### 反方 Agent（glm-3-flash）
- 与正方镜像，立场 = 反方命题，其余规则相同

### 裁判（glm-3-flash，每轮一次调用）
- 输入：辩题、双方命题、全部发言
- 输出（JSON）：`{"status": "continue"|"concede", "conceded_side": "pro"|"con"|null, "reason": "一句话"}`
- 判定标准：仅当一方论点被系统性质疑且无法自洽回应、或明确自相矛盾时判 concede；正常攻防一律 continue
- JSON 解析失败 → 重试 1 次；仍失败 → 视为 continue

### 主 Agent（两次调用）
1. **拆题**（glm-3-flash）：输入原始辩题 → 输出 JSON `{"pro": "...", "con": "..."}`，两命题为同一辩题的对立两面、各一句话
2. **总结**（deepseek-v4-pro）：输入辩题、双方命题、全部发言、裁判记录、结束原因 → 战报 Markdown，固定结构：辩题信息 / 双方立场 / 每轮核心交锋点 / 结束原因 / 双方核心论点与漏洞 / 最终胜方与理由

胜方推导：谁被裁判判定认输则对方胜；轮满则由总结模型依据表现判定并说明理由。

## 代码结构

```
DebateAgent/
├── main.py              # 入口：读命令行辩题，构建图，跑完打印结果
├── config.py            # 模型配置：4 个角色的 model + 统一网关 base_url/api_key（读 .env）
├── state.py             # DebateState 定义 + 轮数常量
├── llm.py               # 统一 LLM 调用封装 chat(...) 与流式 chat_stream(...)（单网关单 key）
├── nodes/
│   ├── splitter.py      # 主 agent 拆题节点
│   ├── debater.py       # 正/反方共用发言节点（参数区分立场+模型）
│   ├── judge.py         # 裁判节点
│   └── summarizer.py    # 主 agent 总结节点
├── graph.py             # StateGraph 组装：splitter → (pro → con → judge) 循环 → summarizer
├── output/              # 战报输出目录（自动创建）
├── tests/               # pytest 单元测试
└── .env                 # LLM_API_KEY（+ 可选 LLM_BASE_URL 覆盖默认网关）
```

### 共享状态 DebateState（TypedDict）

| 字段 | 类型 | 含义 |
|---|---|---|
| `topic` | `str` | 原始辩题 |
| `pro_position` / `con_position` | `str` | 拆出的正反命题 |
| `transcripts` | `list[dict]` | 全部发言，每条 `{"side": "pro"\|"con", "round": n, "text": str}` |
| `round` | `int` | 当前轮数 |
| `judge_records` | `list[dict]` | 每轮裁判判定 `{"round", "status", "conceded_side", "reason"}` |
| `end_reason` | `str` | 最终结束原因 |
| `report_path` | `str` | 战报文件路径 |

### 条件边逻辑（judge 之后）

`concede` 或 `round >= 20` → `summarizer`；否则 `round += 1` 回到 pro 节点。

### 复用点

- 正反方 = 同一个 `debater.py` 函数的两个实例（不同参数），不写两份代码
- 所有 LLM 调用走 `llm.py` 的统一封装；辩手节点用 `chat_stream` 流式产出，每收到一个片段立即打印到终端，完整文本同时进入 state

## 流式展示

- 辩手（正方/反方）发言用 OpenAI 兼容接口的 `stream=True`：节点内逐片段 `print(..., end="")`，终端呈打字机效果；发言前打印一行角色标头（如 `【第 3 轮 · 正方】`），发言结束换行
- 裁判、拆题、总结不流式：裁判要解析 JSON，总结直接整段写入文件，流式无收益
- 流式与重试兼容：重试时先打印一行「重试中…」，从头发起流式请求，已打印的半截内容用换行分隔标记

## 错误处理

- **API 调用失败**（网络/限流/超时）：每步自动重试 2 次（指数退避 1s → 2s）；仍失败则该方本轮发言记为 `"[发言失败，此轮弃权]"`，辩论继续；同一角色**连续 3 个轮次**发言失败才中止整个流程并报错退出
- **裁判调用失败**：直接视为 continue
- **拆题 JSON 解析失败**：重试 2 次后退出并提示重新输入（唯一无降级的步骤）
- **API key 缺失**：启动时检查，报错并指明缺哪个，不进入辩论
- **辩题为空参数**：打印用法提示后退出
- **发言超长**：prompt 限 300-500 字，代码层截断到 800 字兜底

## 测试

1. **冒烟**：`python main.py "人类应不应该追求长生不老"` 完整跑通，`output/` 生成战报，终端逐轮可见
2. **轮满路径**：`MAX_ROUNDS=2` 跑通确认进入总结
3. **单元测试**（pytest，mock LLM）：拆分 JSON 解析、裁判三分支（continue/concede-pro/concede-con）、条件边走向、发言截断
4. **缺 key**：清空 `.env` 确认报错指明缺失项
5. **网关连通性**：先单独调一次 `glm-3-flash` 确认网关、模型名、key 均可用，再跑完整流程

## 明确不做

- Web UI（如后续需要另起项目）
- 辩手自报认输（由独立裁判判定）
- 多辩题并行、记忆持久化
