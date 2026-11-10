"""工具包：import 即注册。新增仿真器：新建模块，用 @tool 装饰，并在此 import。"""
from .base import REGISTRY, Tool, Session, tool, call_tool  # noqa
from . import sim_tools  # noqa: F401  (算电协同)
from . import multi_sim  # noqa: F401  (MATPOWER / ANDES / OpenDSS / OpenModelica / ParaView)
from . import kb_tools  # noqa: F401  (知识库/技能卡)
from . import phase1_tools  # noqa: F401  (碳感知 Pareto / 任务级作业)
from . import viz_tools  # noqa: F401  (拓扑/能流可视化)
from . import model_viz  # noqa: F401  (通用建模拓扑 + 能流视图)
from . import cfg_tools  # noqa: F401  (散热方式/配置构建/扫描/余热可行性)
from . import opt_tools  # noqa: F401  (全年寻优 / 帕累托 / 边际减排成本)
from . import calib_tools  # noqa: F401  (功率标定 / 年日校核 / 多节点热网)
from . import tier_tools  # noqa: F401  (三级优化：基线/滚动/可行域/实时)
from . import market_tools  # noqa: F401  (运营沙盘 P0)
