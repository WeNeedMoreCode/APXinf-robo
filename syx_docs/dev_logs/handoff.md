# Handoff（2026-10-14 舰队换新 + 大清理 + 运维化 → 下一轮压缩用）

## 状态一句话

**goal 三项收口**（全数字见 summary/2026-10-14_fleet-renewal-cleanup-ops.md）：① **gear 舰队换新生产兑现**（用户双授权）——**新二进制 298694a 生效：from_map_serve 687ms / ckpt 总段 6.57s**（旧 17s/22s），4 芯每芯恰 2p 零抢答，**三谱系 spot 3/3 全 success**（含 spatial t4 走新回退桶、goal t9 档表外修复面）；② **孤儿全清 245 只回收 ~176GB**（available 126→302GB）——顺带揪出生产 spool 78 只超额抢答残留与「生产裸奔 36h」pid 复用假阳案；③ **运维三件套落地**（fleet_watch / spot_eval 参数化 / start_gear_supervisor）。②' 多 ckpt 卡点维持。**infra 定案：supervisor/serve 全家住 apxinf_rust 容器**（宿主无 CANN toolkit；启动只走 start_gear_supervisor.sh；判活只信 environ 指纹——已入 memory fleet-infra-container-topology）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-14_fleet-renewal-cleanup-ops.md）——① 换新完成态（新二进制 298694a 生产运行、新代际 2026-10-14、spot 3/3 验收过）；② infra 拓扑事实（supervisor/serve 住 apxinf_rust 容器、start_gear_supervisor.sh 唯一启动姿势、fleet_watch environ 指纹判活、pid 文件两坑）；③ 遗留（2347 僵尸需重启 apxinf_rust 才清——用户需要时做；老 supervisor daemon 失灵机制未定罪但不影响现役）。丢弃：换新三连坑的排障过程、孤儿审计细节——战报已记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-14，见 summary/2026-10-14_fleet-renewal-cleanup-ops.md）：舰队换新完成（298694a 生产运行、from_map_serve 687ms、spot 3/3）；孤儿清零（+176GB）；运维三件套就位（fleet_watch / spot_eval / start_gear_supervisor）。多 ckpt 卡点维持。服务器：4 芯新代际健康 + 回退桶 7/7 自愈新生代 + available 302GB。

**下轮 goal 建议（抄一项即可）**：
1. **生产化长跑例行化**（fleet_watch 每日快照 + spot_eval 晨检脚本化跑 2-3 天：respawn/内存/档表外 L/新代际稳定性；发现规律后固化 cron 或手跑清单）
2. **多 checkpoint 泛化**（管线全参数化就绪：record 换 ckpt → golden → sweep v3o 对照 → transfer → eval；**卡点 = 第二只 checkpoint 到位**，选前先确认）
3. **性能归因报告落档**（用户前几轮问的「历次优化收益占比」已成对话结论——可整理成 syx_docs 正式文档供汇报用：自身链 8.4× 的 78% 执行框架 / 23% 图组织 / 1.5% 量化；vs torch 1.65× 里权重管线 Const 烤入 68%、int8 16%、tiling+host 16%；APXinf 本体 per-call 独占 = 0，价值在冷启动 50×/部署形态/优化固化）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（回退桶 /data/apxinf/serve 由 v3 supervisor 认养）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + 测前 spool 清场验单实例（代际现象，见 memory）**；回退桶落桶 ≤3 只/批错峰 30s；**舰队操作前先 fleet_watch 看指纹快照、重启只走 start_gear_supervisor.sh（宿主起必败——见 memory fleet-infra-container-topology）**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 生产化长跑例行化** —— 换新后的持续验证。
- **为什么**：新代际 + 新 supervisor + 清理后的舰队是新状态组合，过夜/多日观察才能盖 章；fleet_watch 已能一键出快照但还没跑出规律。
- **怎么做**：每日固定时点 `bash /data/apxinf/fleet_watch.sh` 留档 + `docker exec -d apxinf_npu bash /data/apxinf/spot_eval.sh` 晨检（默认三谱系各 1 任务）；观察 respawn（supervisor.log delta）/内存水位/档表外新 L；2-3 天后把节奏固化成 cron 或手跑清单。

**2. 多 checkpoint 泛化** —— 卡点在资源不在工程（同前，先确认第二只 ckpt 到位再选）。

**3. 性能归因报告落档** —— 对话结论文档化。
- **为什么**：用户问「多少是模型优化多少是框架功劳」三轮收敛出的口径（三层来源模型 + APXinf 本体 per-call 独占 = 0 + 真实价值在冷启动/部署形态/优化固化）值得沉淀成正式文档，供对外汇报直接引用。
- **怎么做**：以对话结论为骨、roadmap 数字为据，落 `syx_docs/analysis/` 或 summary；表格 + 口径警示（串行归因近似、口径差异）照搬对话版。

## ④ 性能优化方向清单（2026-10-14 更新）

现状锚点：**生产 fleet = 新二进制（冷启动 6.57s/芯）；per-call 246.9ms（spot object 实测）**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略） | qmd per-token 终点；单一因子集三谱系 |
| I3 | 动态 L 分桶（gear） | ✅ 转正 + 换新（298694a 代） | 回退面 151-157 新生代验证 ✓ |
| I5 | OM 冷启动 lazy | ✅ **生产兑现**（687ms/6.57s 实测） | 零物化 + 并行转置 + serve_min |
| I6 | eval 全链 inproc | ✅ 闭环 | 配方 cann901_eval_inproc.sh |
| I7 | 多 checkpoint 泛化 | 管线就绪；卡点 = 第二 ckpt | |
| I8 | 舰队换新二进制 | ✅ **执行完成**（2026-10-14，spot 3/3） | 孤儿清理 + pid 假阳修复一并落地 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-14_fleet-renewal-cleanup-ops
