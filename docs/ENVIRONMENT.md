# 运行环境与依赖 / Environment and dependencies

本文说明如何在一台新机器上安装「算电热碳耦合仿真」平台（sim-agent）所需的软件。
打包主机（Debian GNU/Linux 13, Python 3.13.5）上的版本如下；其他发行版请对照安装。

This document lists OS assumptions, the Python stack, solvers, and optional external tools.

## 1. 操作系统

- 已在 **Debian GNU/Linux 13 (trixie), x86_64** 上验证。
- 其他 Linux 发行版通常可用；macOS 未在本仓库打包时验证。Windows 建议 WSL2。
- 需要：`bash`、`curl`（`start.sh` 探活）、可编译部分 Python 轮子的基本构建工具（多数依赖有预编译 wheel）。

## 2. Python

- **已验证版本：Python 3.13.5**（CPython, GCC 14.2.0）。
- 建议 3.11 及以上。更早版本未在本导出中验证。
- 推荐使用仓库内虚拟环境，不要把依赖装进系统 Python：

```bash
./scripts/setup_env.sh          # 创建 .venv 并安装 requirements.txt
# 或完全钉死版本（较慢，更接近打包环境）：
LOCK=1 ./scripts/setup_env.sh
source .venv/bin/activate
```

打包环境中的解释器路径曾为 `/workspace/sdco-env`。仓库副本中的 `start.sh`、`stop.sh`、`cases/public_bench/run_all.sh` 与 `tests/test_paper_bench.py` 会按以下顺序解析 Python：

1. 环境变量 `PY` 或 `SDCO_PYTHON`（若已设置）
2. 仓库内 `.venv/bin/python`
3. 若仍存在，则回退到 `/workspace/sdco-env/bin/python`（保持原机行为）
4. 否则 `python3` / 当前解释器

### 2.1 依赖文件

| 文件 | 说明 |
|---|---|
| `requirements.txt` | 项目直接依赖（未钉死全部传递依赖） |
| `requirements-lock.txt` | 打包环境 146 个已安装发行版的完整钉死列表（含传递依赖及环境中存在、应用未直接导入的包，如 IPython） |
| `environment.yml` | 可选的 Conda 描述，内部仍走 pip |

`pip freeze` 在打包用的 `/workspace/sdco-env` 中因 pip 内部模块缺失而失败，锁定列表改由 `importlib.metadata` 导出。这是环境状态的忠实记录，不是重新生成的约束求解结果。

CPU 环境安装 PyTorch 时请使用官方 CPU 源，避免拉到体积很大的 CUDA 轮子：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
# 或
pip install -r requirements-lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

打包环境记录的版本（节选）：

| 包 | 版本 |
|---|---|
| fastapi | 0.162.0 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.2 |
| pandas | 2.3.3 |
| numpy | 2.4.6 |
| scipy | 1.18.1 |
| matplotlib | 3.11.2 |
| pyomo | 6.10.1 |
| highspy | 1.15.1 |
| pandapower | 3.5.6 |
| openai | 3.42.0 |
| httpx | 0.28.1 |
| python-dotenv | 1.2.4 |
| sentence-transformers | 6.2.0 |
| torch | 2.15.0+cpu |
| jieba | 0.42.1 |
| lancedb | 0.41.0 |
| pyarrow | 26.0.0 |
| plotly | 7.1.0 |
| pytest | 9.2.0 |
| andes | 2.0.0 |
| opendssdirect.py | 0.9.4 |
| playwright | 1.64.1 |
| openpyxl | 3.1.5 |
| python-docx | 1.2.0 |
| pypdf | 6.21.4 |

本地 RAG 默认使用 `BAAI/bge-m3` 与 `BAAI/bge-reranker-v2-m3`，权重在首次使用时下载到 `~/.cache/huggingface`。若 huggingface.co 不可达，可设置 `HF_ENDPOINT=https://hf-mirror.com`。`RAG_EMBED_BACKEND=none` 时仅用 BM25，无需这些模型。

`playwright` 仅用于 `tests/screens_*.py` 截图脚本，不是 pytest 主套件的必需项。若要跑截图，还需另行安装浏览器：`python -m playwright install chromium`。

## 3. 求解器与仿真库（随 pip 安装）

| 组件 | 用途 | 打包环境版本 | 安装 |
|---|---|---|---|
| HiGHS（`highspy`） | 直流最优潮流 / 各类 LP、MILP | 1.15.1 | `pip`（见 `requirements.txt`） |
| Pyomo | 代数建模，调用 HiGHS | 6.10.1 | `pip` |
| pandapower | 交流校核、标准算例 | 3.5.6 | `pip`（已钉死此版本） |
| ANDES | 暂态稳定（`run_andes_tds`） | 2.0.0 | `pip` |
| OpenDSS（`opendssdirect`） | 配网电压 / 储能 | 0.9.4 | `pip` |

无需单独安装系统级 `highs` / `cbc` / `ipopt` 可运行默认 DC-OPF 路径。打包主机上未发现独立的 `highs`、`cbc`、`glpsol` 或 `ipopt` 可执行文件。

## 4. 可选外部工具（未随 pip 安装）

以下工具在打包主机上 **均未安装**，因此无法在此记录本机实测版本号。缺少它们时，主 Web 应用的 Mock 演示与多数测试仍可运行；与外部仿真器相关的测试会失败。

当前测试现状（本导出于 2026-11-10，Asia/Shanghai，在暂存副本上用 `/workspace/sdco-env` 复跑）：**409 项中 400 通过，6 项因缺少 `octave-cli` / `omc` / `pvpython` 失败，3 项因旧预言（oracle）缺失而跳过。不是全绿。** 2026-11-07 的 401/392 是在线帮助 8 项测试加入之前的记录。

对应测试主要在 `tests/test_multi_sim.py`：

| 工具 | 测试 | 用途 |
|---|---|---|
| Octave + MATPOWER 8.1（`octave-cli`） | `test_matpower`，以及会实际调用 MATPOWER 的路由用例 | `run_matpower` |
| OpenModelica（`omc`，可选 `OMEdit`） | `test_openmodelica_default`、`test_openmodelica_powersystems`，以及会实际调用 OM 的路由用例 | `run_openmodelica`（含 PowerSystems/MSL 模型） |
| ParaView（`pvpython`） | `test_paraview` | `run_paraview_render` |

Debian / Ubuntu 上可参考的安装命令（版本因发行版而异，安装后请用 `--version` 自行确认）：

```bash
# Octave（再按 MATPOWER 官方说明安装 8.1）
sudo apt-get update
sudo apt-get install -y octave

# ParaView（提供 pvpython）
sudo apt-get install -y paraview

# OpenModelica：通常不在默认 Debian 仓库中，请按官方文档添加源后安装 omc
# https://openmodelica.org/download/download-linux/
```

**B09（外部工具恢复）仍为已知未完成项**，本导出不会声称上述工具已在目标机器就绪。

## 5. 环境变量

变量名见仓库根目录 `.env.example`（仅有名称与注释，不含真实密钥）。复制为 `.env` 后在本地填写。也可以在 Web 界面「设置」页保存，写入 `data/settings.json`（该文件已列入 `.gitignore`，请勿提交）。

常用项：

- `LLM_MOCK=1`（默认演示）：无需 API Key。
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`：任意 OpenAI 兼容端点；使用真实模型时将 `LLM_MOCK` 设为 `0`。
- `ARTIFACT_DIR`、`DATA_DIR`：产物与运行时数据目录，默认仓库下 `artifacts/`、`data/`。
- `RAG_EMBED_BACKEND`、`EMBED_*`、`LOCAL_EMBED_MODEL`、`RAG_RERANK`：检索后端。
- `CARBON_*`、`WATTTIME_*`：碳强度适配器（WattTime 为存根）。
- `PORT`（默认 8080）、`HOST`（默认 `0.0.0.0`）、`PY` / `SDCO_PYTHON`。

## 6. 端口与运行模式

- 默认 **Mock 模式**，监听 **8080**。
- 启动：`./start.sh`；停止：`./stop.sh`。
- 前台调试：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`
- 在线帮助：启动后打开 <http://127.0.0.1:8080/help>
- **不要对公网暴露**：当前无用户认证。
- **禁止真实交易**：运营沙盘为 sandbox；真实外部下单接口返回 403。

## 7. 本仓库未包含的运行时数据与大文件

详见 `data/README.md` 与 `cases/public_bench/raw/README.md`。概要：

- `artifacts/`、会话、SQLite、向量库、`data/settings.json` 为运行时/业务数据，未纳入版本库。
- `cases/public_bench/raw/bdg2_electricity_cleaned.csv` 约 167 MB，超过 GitHub 单文件 100 MB 限制，未纳入。可按该目录说明自行下载，SHA-256 已记录。
- 历史论文复现证据包、本机备份（`/workspace/sim-agent-*-evidence` 等）不在本仓库中。部分验收脚本仍硬编码这些本机路径，需用命令行参数或本地目录改写后才能在其他机器上重放。
