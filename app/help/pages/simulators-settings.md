# 仿真器状态与 LLM 设置

> **目的**：查看外部仿真工具可用性；配置大模型与检索后端。
> **前置条件**：无。
> **界面入口**：⑥ 知识 · 工具 · 设置 → 高级与配置 → 🛠 仿真器 / 工具、⚙️ 设置。状态：【已实现】（部分外部仿真器在当前环境缺失）。

[▶ 打开此功能：仿真器 / 工具](/?view=sims)

## 仿真器 / 工具

列出工具注册表（MCP 兼容）与外部仿真器可用性。当前环境中 pandapower、ANDES、OpenDSS 可用；MATPOWER（需 `octave-cli`）、OpenModelica（需 `omc`）、ParaView（需 `pvpython`）缺失，相关功能不可用。

## LLM 设置

[▶ 打开此功能：设置](/?view=settings)

| 字段 | 说明 |
|---|---|
| LLM Base URL | OpenAI 兼容接口地址 |
| LLM API Key | 以掩码显示；**不要把真实 Key 写进任何文档或截图** |
| 模型名 | 所用模型 |
| Mock 模式 | 1 = 开启（无需 Key，规则化对话，用于演示与测试）；0 = 使用真实 LLM |
| Embedding 模型 / Base URL / Key | 空表示用 BM25 或沿用 LLM 设置 |
| RAG 嵌入后端 | `local` / `openai` / `none` |
| 本地嵌入模型、重排开关、重排模型、向量库 | 检索相关 |
| 碳强度来源 | `synthetic` 等；WattTime 为存根 |

设置保存在服务端 `data/settings.json`。保存后左下角模式徽章随之更新。

> Mock 模式下的回复由规则生成，不代表真实大模型效果。
