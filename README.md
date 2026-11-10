# 算电热碳耦合仿真平台（sim-agent）

用中文对话驱动的算力–电力–热力–碳排耦合仿真与研究 Web 应用（FastAPI + 单页前端）。默认 **Mock 模式**，监听 **8080** 端口。默认场景数据为**合成示例**，不能当作现场计量数据。

目标仓库（尚未在本副本中配置远程或执行推送）：
<https://github.com/fzlove9196-cyber/Electricity-Heat-and-Carbon-Operation-Optimization-Platform-.git>

## English summary

This repository packages a local research/decision web app for coupled electricity, heat, and carbon operation of data-center loads. It ships application code, tests, case templates, online help, environment files, and product documents. Runtime databases, session history, secrets, virtualenvs, logs, large generated artifacts, and one public CSV that exceeds GitHub’s 100 MB file limit are excluded (see `data/README.md` and `docs/ENVIRONMENT.md`). Start in Mock mode on port 8080 with `./scripts/setup_env.sh` and `./start.sh`. There is **no real market trading**. Paper reproduction is **incomplete**. The license is **TBD** (none has been chosen). Test status on the packaging host (staging copy, 2026-11-10, Asia/Shanghai): **409 collected, 400 passed, 6 failed** (missing `octave-cli` / `omc` / `pvpython`), **3 skipped** (missing historical oracles). Not all green. The earlier 401/392 figure was from 2026-11-07, before eight online-help tests were added.

## 快速开始

```bash
# 1. 安装 Python 依赖（创建 .venv）
./scripts/setup_env.sh
source .venv/bin/activate

# 2. 配置（可选）。默认 LLM_MOCK=1，无需 API Key
#    cp .env.example .env   # setup 脚本在缺少 .env 时会自动复制
#    若要使用 OpenAI 兼容模型，在 .env 或网页「设置」中填写
#    LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，并将 LLM_MOCK 设为 0

# 3. 启动（默认 0.0.0.0:8080）
./start.sh
# 浏览器打开 http://127.0.0.1:8080
# 在线帮助  http://127.0.0.1:8080/help
# 停止      ./stop.sh
```

帮助入口：页面「❓帮助」、侧栏「⑥ 使用帮助」、上下文 `?`、F1、Ctrl+K。详细操作见 [USAGE.md](USAGE.md) 与应用内帮助（约 42 篇，含参数配置说明）。

依赖、求解器与可选外部软件见 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)。产品功能设计说明（2026-11-10）见 [docs/product-design/](docs/product-design/)。

空的 `data/` 即可启动：首次启动（或 `python scripts/seed_runtime.py`）会创建基础库、写入模板/示例资源，并在 `KNOWLEDGE_SEED=1`（默认）时导入 `knowledge_seed/`。被排除的历史 SQLite 与 BDG2 用电 CSV 不是启动所必需，详见 `docs/ENVIRONMENT.md` 第 8 节。

## 功能成熟度（请按标签阅读，勿把部分实现当作已验收）

标签含义：**已实现** = 代码路径可用并有测试或可演示；**部分实现** = 有可用核心，但范围/精度/界面未闭环；**未实现** = 明确不在当前范围或尚未开工；**已知缺陷** = 已观察到、尚未关闭。

### 已实现

- Mock 模式 Web 应用：对话、场景/模板、配置构建、模型与结果展示、知识库与技能卡
- 产品基础层：项目、场景版本、冻结输入、任务重跑与审计导出（SQLite 运行库在首次使用时创建）
- 模板库与通用气象 / 设备参数库（合成或公开来源，需结合现场数据校准）
- 直流最优潮流（Pyomo + HiGHS）与峰值交流校核（pandapower）
- RC 热模型、蓄热（TES）、热量分账（日窗口已做 1h/15min 守恒核对）
- 全年 8760 与帕累托扫描（仍主要挂在原工作台）
- 碳感知目标、任务级迁移 LP、研究编排（形式化→计划→求解→诊断→结论）
- 运营沙盘（示范规则，sandbox；真实下单返回 403）
- 应用内在线帮助中心（`/help` 及 `/api/help/*`）

### 部分实现

- 论文复现工作台（`/paper-reproduction`）：有若干对照与修复，**A 级整篇通过为 0**，不能声称 8 篇全部复现
- 清洁能源匹配 / 年度 CFE LP：已有冻结重跑与独立对照，完整背景四配置未完成
- 电网再出清闭环：已有短时域变体与独立 LP，完整年度与作者表格对齐未完成
- GPU 容量帽 / SLA：已有固定离散帽与策略对照，完整 hybrid/resize 现场权重与跨模块耦合未完成
- 15 分钟时间轴：日窗口已统一部分路径，跨年度 / 三级运行尚未全部打通
- 外部仿真器接口（MATPOWER / OpenModelica / ParaView）：代码已接，本机缺工具时不可用

### 未实现

- 真实电力或碳市场交易、实盘报单
- 用户认证与多租户；请勿直接暴露公网
- PDF / 文档自动生成工程级模型
- 形式化产品验收与完整浏览器视觉验收
- 开源许可证（见文末，**TBD**，本仓库未选定许可证）

### 已知缺陷

- 测试不是全绿：本导出在暂存副本上复跑为 409 项中 400 通过，6 项因缺少 `octave-cli` / `omc` / `pvpython` 失败，3 项因旧预言缺失跳过（2026-11-10，Asia/Shanghai）。2026-11-07 的 401/392 是在线帮助 8 项测试加入之前的记录
- 浏览器验收（B10）：曾出现 Chrome 访问本机 8080 报 `ERR_CONNECTION_REFUSED`，同时 `curl` 返回 200；帮助界面尚未做视觉验收，部分帮助配图偏旧
- 外部工具恢复（B09）未完成
- DC-OPF 为线性化；交流校核仅峰值时刻；默认电网额定值含假设
- 任务模型默认可连续切分；整数 / 不可中断 GPU 分配未覆盖全部路径
- 无认证、流式粒度为步骤级而非逐 token；服务重启后内存中的仿真中间态需重跑

## 架构（简图）

```
浏览器 (app/static 原生 JS 单页，无需打包)
   │  SSE /api/chat/stream ，REST /api/* ，帮助 /help
FastAPI (app/main.py)
   │  会话 data/sessions/ ；产物 artifacts/ ；项目库 data/foundation.sqlite3
Agent / 研究编排 (app/agent.py, app/research/)
   │  OpenAI 兼容 function calling；LLM_MOCK=1 时为确定性中文关键词路由
工具：DC-OPF、交流校核、KPI、绘图、报告、碳/任务、ANDES、OpenDSS、
      可选 MATPOWER / OpenModelica / ParaView，以及 CFE / 再出清 / GPU 模块
知识层：BM25 + 可选本地 bge-m3 / 重排 （app/knowledge.py）
```

## 目录结构

```
app/                  FastAPI 应用、求解模块、静态前端、在线帮助 (app/help)
tests/                pytest 与截图脚本
cases/                场景模板、公开基准脚本、论文复现输入与部分结果
knowledge_seed/       知识库种子文档
screens/              既有界面截图（部分配图日期较早）
docs/                 环境说明、分阶段记录、产品设计说明
scripts/setup_env.sh  创建虚拟环境并安装依赖
start.sh / stop.sh    启动 / 停止（默认 8080）
requirements.txt      直接依赖
requirements-lock.txt 打包环境的完整钉死列表
environment.yml       可选 Conda 描述
USAGE.md              较细的使用说明
```

## 配置方式

1. 复制 `.env.example` 为 `.env`（仅含变量名；不要提交 `.env`）。
2. 或在页面「设置」中填写，保存于 `data/settings.json`（已忽略，勿提交）。
3. Mock 模式：`LLM_MOCK=1`。真实 LLM：填写 OpenAI 兼容的 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`，并设 `LLM_MOCK=0`。
4. 参数与场景：见在线帮助中的参数专题，以及 `USAGE.md`。

## 测试

```bash
source .venv/bin/activate   # 或使用已有环境
python -m pytest -q tests/
```

本导出在暂存副本上使用打包环境 `/workspace/sdco-env` 于 2026-11-10（Asia/Shanghai）复跑：`409 collected, 400 passed, 6 failed, 3 skipped`，用时约 6 分 6 秒。6 项失败全部在 `tests/test_multi_sim.py`，原因是本机未安装 `octave-cli`、`omc`、`pvpython`。3 项跳过因旧预言缺失。不是全绿。部署后的 HTTP 流程脚本：`tests/http_e2e.sh`（需服务已启动）。

## 许可证

**TBD（待定）。本仓库尚未选定开源或专有许可证，导出时故意不添加 LICENSE 文件。** 使用、分发或再许可前请由仓库所有者决定并补上许可声明。文档与案例中引用的第三方数据（如 AEMO、Building Data Genome 2、SPECpower 公开结果）保留各自原许可。

## 安全与边界

- 不要提交 `.env`、密钥、证书或 `data/settings.json`。
- 不要对公网裸露本服务。
- 禁止真实交易。
- 大文件与运行时数据的排除清单见 `docs/ENVIRONMENT.md` 与 `data/README.md`。
