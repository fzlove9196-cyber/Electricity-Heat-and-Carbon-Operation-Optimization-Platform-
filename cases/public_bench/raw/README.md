# public_bench 原始数据

本目录包含公开基准脚本所需的大部分原始文件（AEMO 电价、Open-Meteo 气象、SPECpower 结果、BDG2 气象等）。完整来源 URL 与文件哈希见 `../results/manifest.json`。

## 未纳入 Git 的文件

`bdg2_electricity_cleaned.csv`（Building Data Genome Project 2 用电时序，约 167 MB）超过 GitHub 单文件 100 MB 限制，因此没有放进本仓库。

- SHA-256：`b6ffc9b4dfcefe5c753594730a08ae822b0d50fec6815abb8f185591e6c630a3`
- 许可证：CC BY 4.0
- 上游：<https://github.com/buds-lab/building-data-genome-project-2>
- 清单中记录的文件哈希与上面一致（见 `../results/manifest.json` 的 B4 条目）

将该文件放到本目录并核对哈希后，即可运行：

```bash
# 在仓库根目录
./cases/public_bench/run_all.sh
```

**主 pytest 套件不读取此 CSV**，缺少它不会导致 `tests/test_public_bench.py` 失败。只有公开基准脚本 `bench_dr_bdg2*.py` / `bench_dr_methods.py` 需要它。

若仓库托管方日后启用 Git LFS，也可以把该文件作为 LFS 对象或 Release 附件发布；本导出未擅自配置 LFS，也未重新打包该文件。
