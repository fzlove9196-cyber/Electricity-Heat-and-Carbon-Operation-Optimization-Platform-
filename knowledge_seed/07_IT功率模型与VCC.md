# IT 硬件功率模型与 VCC 虚拟容量（实现说明）

> 对应调研 Page「算力任务到电热负荷映射」近端 ①②。实现日：2026-11-05（Asia/Shanghai）。

## 1. Idle+动态 / PDU 分段线性（①）

**缺省 `power_model=identity`**：`P_IT(t) =` 交互 + 批处理工作功率（与改动前完全一致）。

**`idle_dynamic`**（Fan / Google 同族仿射）：

\[
P_{IT}(t)=P_{idle}+(P_{peak}-P_{idle})\cdot u(t),\quad u(t)=\frac{P^{work}(t)}{Cap^{IT}}
\]

参数：`p_idle_mw` + `p_peak_mw`，或 `p_idle_kw`/`p_peak_kw` + `n_servers`。

**`pdu_pwl`**：利用率→功率断点列表 `pdu_breakpoints=[{util, power_mw}, ...]`，凸组合 + SOS2（启用后该场景为 **MILP**）。

**热 / PUE**：

- `coupled`：机房发热输入用实际 `P_IT`（非仅 work）。
- `constant_pue`：电网侧 = `PUE × P_IT`（文档与公式页已注明）。

**Trace**：`app/traces.py` 提供 `hourly_util_from_alibaba` / `load_borg_util` / `util_to_power_mw` / `apply_util_curve_to_dc`。

**标定诚实性**：案例若无本站 PDU 实测，应在 `sources` 标注【假设】（如 idle=0.4×Cap）。勿把 GPU TDP 总和当 IT 功率。

## 2. VCC 碳智能日前整形（②）

**缺省 `vcc_mode=off`**：无额外约束/目标。

- `vcc_mode`: `carbon` | `price` | `weighted`
- `vcc_stage`: `joint`（与 DC-OPF 同层，Cap≥批处理，目标含整形项）| `day_ahead`（先解小 LP 得 Cap_vcc，再硬约束批处理）
- 日能量：`Σ Cap ≥ B`（`vcc_preserve_daily`）；`Cap ≤ Cap_IT − interactive`

对话关键词：虚拟容量 / VCC / 碳智能 / 日前整形；电价→price；加权→weighted。

**验证注意**：日前 VCC 仅按碳强度/电价信号整形灵活容量，**不保证**相对无 VCC 基线一定降碳——若信号与场内可再生出力/电价结构不对齐，排放可能持平或上升。应并列报告成本与排放 deltas，并标明碳口径（平均/边际）。

## 3. 代码路径

| 模块 | 路径 |
|------|------|
| 功率模型 | `app/power_model.py` |
| VCC | `app/vcc.py` |
| 引擎接入 | `app/tools/sdco_engine.py` |
| Schema | `app/scenario.py`（DataCenter / Scenario 新字段，均有缺省） |
| Trace | `app/traces.py` |
| 透明化公式 | `app/transparency.py` |
| 测试 | `tests/test_power_vcc.py` |

## 4. 参考文献

- Fan et al., Power provisioning, ISCA 2007
- Radovanović et al., Power modeling, arXiv:2103.13308
- Radovanović et al., Carbon-Aware Computing / VCC, arXiv:2106.11750
