---
name: ascend-msprof
description: 昇腾 msprof 性能采集实战——用最小采集量定位问题，不要全量验证。每当要在 NPU 上做性能分析、profile 一个推理/算子程序、解析 msprof 产物（op_statistic/task_time/op_summary）、或发现 msprof 采集特别慢时，使用本 skill。
---

# msprof（昇腾 profiling）实战知识库

基于 CANN 9.0.1 + Ascend 310P3 实测（2026-09 GE 静态 OM 性能攻坚）。所有结论有实验数据支撑。

## 第一原则：最小采集量

**msprof 的采集与分析成本 ∝ 任务数 × 迭代数，全量 bench 采集是最常见的浪费。**

实测（300 次迭代 × ~1700 task/迭代的推理图）：
- 采集 ~3.5 分钟，**分析+导出另需 5-10 分钟**（单进程啃 50 万行 task 记录）
- 每次全量 profile 落盘 ~1.1GB
- 假设检验轮次多时，profile 本身成为迭代瓶颈

**最小化纪律（按序执行）：**
1. **先缩被测程序的规模**：把应用的迭代数/批次数/层数参数化（如 bench 轮数 env），profile 时调到 10-20 次执行。任务数控制在 5 万行以内，分析 1-2 分钟出数。
2. **缩图规模**：层数减到 1-3 层通常不影响"哪类算子/哪种机制慢"的结论（逐层重复结构）。
3. **只在接受假设后跑一次全量 profile** 做最终确认。
4. 用完清理 profile 目录（`du -sh` 盯着，单次 GB 级）。

## 调用方式

```bash
msprof --output=<目录> <你的程序> [程序参数]     # 新式：直接跟 app
# 或旧式 --application=<path>
```

- **msprof 继承 shell 环境**（ASCEND_RT_VISIBLE_DEVICES / LD_LIBRARY_PATH 等照常 export）。
- 采集默认开 aic task-based + ascendcl；`--task-time=l0/l1/l2` 可调粒度。
- 程序退出后 msprof 自动进入分析+导出阶段，**全程是前台阻塞的**。

## 产物与读取

`<output>/PROF_*/mindstudio_profiler_output/`：

| 文件 | 内容 | 关键列 |
|---|---|---|
| `op_statistic_*.csv` | 按 OP Type 聚合 | Count / Total / Avg / Ratio(%)（除以迭代数得每迭代成本） |
| `task_time_*.csv` | 逐 task 时间线 | task_start(us)/task_stop(us)/kernel_name/stream_id |
| `op_summary_*.csv` | 逐 task 详情 | **Task Wait Time(us)**（找等event的受害者）、Input/Output Shapes |
| `api_statistic_*.csv` | host 侧 ACL API | 含 aclmdlExecuteAsync 跨度、aclnn launcher |
| `fusion_op_*.csv` | 融合算子清单 | 判断编译 pass 融合了什么 |

**CSV 坑**：
- 表头带单位（`task_start(us)`），值可能带尾随 `\t`——解析时 strip。
- `MemcopyAsync` 是 `other` 型，**不在 op_statistic 里**，只在 task_time/op_summary。
- 同名算子可能同时出现在 AI_CORE 和 AI_VECTOR_CORE（混合核 kernel 拆两条记录），聚合计时注意别双算。

## 分析套路（定位"墙钟远大于 kernel 时间"类问题）

1. **busy vs 空闲**：全部流的 task 区间做 union merge，`fill = busy/span`。fill < 50% 时瓶颈是空隙不是算子。
2. **按迭代切窗**：merged 时间线上 >3ms 的空隙作迭代边界，取稳态迭代窗。
3. **空隙归因**：每个大空隙找"结束于哪个 task、开始前最后一个 task"。经典形态：`EVENT → ~20ms 空 → MemcopyAsync` = host 参与的运行时拷贝/调度路径。
4. **Wait Time 聚合**：op_summary 按 Op Name 聚合 Task Wait Time——等待最久的算子通常是子图边界/同步点的下游受害者（不是元凶，但能指路）。
5. **host API 对照**：api_statistic 里 per-iteration 的 Inner*/GetWorkspaceSize 调用 = 图内 host-launcher 算子的指纹。

## 采集失败模式

- **导出静默失败**：msprof 退出码 0、日志说 "Profiling finished"，但 mindstudio_profiler_output 目录为空/缺失——重跑一次通常就好；raw 数据在 `PROF_*/host/sqlite/*.db`（TaskInfo 表等）可救。
- **顽固导出失败（2026-09-19 实测一轮）**：重跑/加长 bench/换 --application=wrapper 形式都无效；device 数据（aicore/hwts slices + all_file.complete + end_info）与 host sqlite 俱在、分析日志无 error、与成功采集的 pipeline 日志逐段相同，仅最后 CSV 导出阶段不产出。未定位根因。**恢复路径**：
  - `host/sqlite/ge_info.db` 的 **TaskInfo**（op_name/op_type/stream_id/task_id/timestamp）——⚠ timestamp 是 host 提交时刻非设备执行时刻（同流相邻 10-20µs 即 launch 序列）；且常被截断（只覆盖前 2-3 次执行）。
  - `device_6/sqlite/hwts-rec.db` 的 **HwtsBatch**（stream_id/task_id/start_time/end_time，设备侧真实时长）——⚠ **主执行流的任务不在其中**（在未导出的 aicore.data 二进制里），只有侧流/分片任务；task_id 是流内序号非全局。
  - 两者按 `(stream_id, task_id)` JOIN 可恢复侧流算子账本；主链时序仍不可得。
- 采集期间 npu-smi 看 AICore 占比没意义（采样时刻），以产物为准。
- 共享芯片上 profile 数字有抖动，对照实验用同芯。

## 边界

- 实测 CANN 9.0.1 / 310P3；msprof 参数面在其他版本可能不同。
- 本库不覆盖 aicpu dump / 算子级 double-click 分析（MindStudio GUI 功能）。
