# Handoff（2026-10-13 冷启动零物化 + 代际取证 → 下一轮压缩用）

## 状态一句话

**goal 三项收口**（全数字见 summary/2026-10-13_cold-start-serve-min-cohort-forensics.md）：① **冷启动 lazy 剩余闭环**——零物化骨架（`Tensor::zeros` 懒零页）+ 39 件 style `std::thread::scope` 并行转置：from_map_serve 数学段 **17s→0.53s**；PyO3 open 接 `GEB_CKPT_SERVE_MIN`（inproc open **145.5→81.9s**）；GEB_PRELOAD_EARLY **退役判决**（ckpt 段缩到 0.5s 后提前量 <2s，修复无 ROI）。② **稳定性长跑完成**——11h 过夜零 respawn/内存稳/晨间 spot eval 2/2（object t0 133 步 + spatial t4 120 步走回退）。③ 多 ckpt 卡点维持。**过程大戏：数值「代际」现象九格取证**——同 payload 下昨日进程=A、今日进程=B（~0.3%），二进制/源码/机制/填充/芯片/文件/env 全排除，GE 运行时固有非回归。引擎 `298694a` 已 push；BIN 路径已就位新二进制（**生产 4 芯仍跑旧二进制 A 代际，未动——换binary 留用户决策**）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-13_cold-start-serve-min-cohort-forensics.md）——① 零物化骨架（synthetic_skeleton = Tensor::zeros 占位，GEB_LOAD 路径占位不被读；parallel_transpose = thread::scope 分块无锁）+ PyO3 serve_min（env GEB_CKPT_SERVE_MIN，eval wrapper 已带）；② 代际现象结论（对拍须同芯同时代 + spool 发完即拷贝 + 测前清场验单实例，test_serve_cleanup_1013.sh）；③ 服务器终态（生产旧二进制 A 代际 + BIN 已就位新二进制 + cp311 .so 已更新）。丢弃：九宫格排除的实验过程、脚本往返细节——战报已记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-13，见 summary/2026-10-13_cold-start-serve-min-cohort-forensics.md）：serve-min 零物化 + 并行转置 + PyO3 serve_min 全落地（17s→0.53s / open 145→82s）；数值代际现象取证定案（GE 固有非回归）；稳定性过夜 + spot 2/2；多 ckpt 卡点。生产舰队未动（旧二进制健康），新二进制在 BIN 路径待 respawn。

**下轮 goal 建议（抄一项即可）**：
1. **舰队换新 + 行为复验**（授权重启 4 芯 serve 走 supervisor ctrl stop/ensure → 新二进制 298694a 生效 → 三谱系各抽 2-3 任务 spot + 冷启动计时留档；顺带处置 414 只孤儿 helper ~30GB——用户决策项）
2. **多 checkpoint 泛化**（管线全参数化就绪：record 换 ckpt → golden → sweep v3o 对照 → transfer → eval；**卡点 = 第二只 checkpoint 到位**，选前先确认）
3. **生产化长跑/运维面**（gear 舰队 + 回退桶连续多日观察：respawn 风暴/档表外 L/内存水位 + 晨间 spot 例行化脚本化）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（回退桶在 /data/apxinf/serve 由 v3 supervisor 认养）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`——宿主无 LIBERO）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（push119.sh 一条命令）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + 测前 spool 清场验单实例（代际现象，见 memory）**；回退桶落桶 ≤3 只/批错峰 30s。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 舰队换新 + 行为复验** —— 把已构建验证的优化二进制上生产。
- **为什么**：新二进制（零物化 + serve_min，298694a）已 bit 级验证但生产 4 芯仍跑昨日二进制（健康、spot 2/2，无紧急性）——冷启动 32× 收益要 respawn 才兑现；414 只孤儿 helper（~30GB）也该一并决策。
- **怎么做**：supervisor 协议重启（ctrl stop_chipN → ensure_chipN，或用户直接授权 kill 让 daemon 循环接管）→ 确认 from_map_serve ~0.5s 计时行 → 三谱系 spot（object 0 / spatial 4 / goal 9 各 1 任务）→ 冷启动数字留档。注意换 binary = 新代际数值，行为 spot 是验收线。

**2. 多 checkpoint 泛化** —— 卡点在资源不在工程。
- **为什么/怎么做**：同前（管线全参数化；先确认第二只 ckpt 到位再选）。

**3. 生产化长跑/运维面** —— 转正拓扑的持续验证例行化。
- **为什么**：过夜空载 + spot 只覆盖了两类风险（respawn/内存）；多日带载行为、档表外新 L、supervisor 日志例行巡检还没脚本化。
- **怎么做**：留观脚本（ready mtime / 内存 / supervisor.log 增量）+ 晨间 spot 一键脚本化（spot_eval_1013.sh 已是雏形——参数化 suite/tasks 即可）。

## ④ 性能优化方向清单（2026-10-13 更新）

现状锚点：**per-call 236-250ms 维持；冷启动 serve 侧 ckpt 段 22→5.7s、inproc open 145→82s**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略） | qmd per-token 终点；单一因子集三谱系 |
| I3 | 动态 L 分桶（gear） | ✅ 转正（默认根 + 30/30 + 回退面 151-157） | t4 永久回退依赖已记录 |
| I5 | OM 冷启动 lazy | ✅ **收口**（零物化骨架 + 并行转置 + PyO3 serve_min；io 5.5s mmap 为剩余大项，按 header 过滤读可再砍但 ROI 降） | PRELOAD_EARLY 退役判决 |
| I6 | eval 全链 inproc | ✅ 闭环 + serve_min（open 82s） | 配方 cann901_eval_inproc.sh |
| I7 | 多 checkpoint 泛化 | 管线就绪；卡点 = 第二 ckpt | |
| I8 | 舰队换新二进制 | ⏸ 待用户授权重启 | BIN 已就位 298694a |
| — | 数值代际现象 | 观察项（GE 固有，行为双代际都过） | 机制未明；对拍纪律已入 memory |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-13_serve-min-zero-skeleton-cohort-forensics
