# Handoff（2026-10-15 换新收口 + op census + I9 闭环 + I10 判决 → 下一轮压缩用）

## 状态一句话

**10-14 轮**（summary/2026-10-14_fleet-renewal-cleanup-ops.md）：gear 舰队换新生产兑现（**298694a，from_map_serve 687ms/ckpt 6.57s，spot 3/3**）+ 孤儿全清 245 只（+176GB）+ 运维三件套（fleet_watch / spot_eval / start_gear_supervisor）；**infra 定案：supervisor/serve 全家住 apxinf_rust 容器，判活只信 environ 指纹**（memory fleet-infra-container-topology）。**10-15 轮**（summary/2026-10-15_op-hotspot-census.md + 2026-10-15_i9-firstcall-warmup.md + **2026-10-15_i10-vision-int8-verdict.md**）：op census 实测设备侧 228ms 无隐藏热点；**I9 闭环**（「tokenize 186ms」证伪 → 真凶首调用 eager 编译无 warmup → 修复 **inference 433→273.6**，行为保持）；**I10 预检四步走完判不立项**：权重谱过关（0.893% ≈ prefix）+ 激活谱温和（dump 就位）+ L2-lite 模拟 α=0.5 全量 med 1.32% 回先例带**但 fc2 结构性超带**（1.86/4.1%，α/clip/floor 三旋钮全救不动）+ 收益重估（「2.41×/−18ms」是合成形状虚高，实数 mixed **−6~7ms** = model 的 2.5-3%）→ 战役代价不值，降级 backlog；**量化域到此到头，性能线收官**。多 ckpt 放弃（I7）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在四份 summary）——① 换新完成态（298694a 生产运行、spot 3/3 验收过）；② infra 拓扑事实（supervisor/serve 住 apxinf_rust 容器、start_gear_supervisor.sh 唯一启动姿势、fleet_watch environ 指纹判活）；③ census 结论（228ms 设备侧无隐藏热点）；④ **I9 闭环**（tokenizer 0.43ms / 真凶首调用 eager 编译 3.9s / warmup 修复后 inference 273.6 / 逐调用开关 APXINF_GE_PERCALL=1）；⑤ **I10 判决**（权重谱过关 0.89% / α=0.5 全量 med 1.32% / **fc2 结构地板 1.86-4.1% 救不动** / 实数 mixed −6~7ms / 判不立项降 backlog / 校准数据 calib_vision_v1.safetensors + 三脚本留档）；⑥ 性能线收官（量化域到头）。丢弃：I9 证伪四步与 I10 预检的探针往返——战报已记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-15，见 summary/2026-10-14_fleet-renewal-cleanup-ops.md + 2026-10-15_op-hotspot-census.md + 2026-10-15_i9-firstcall-warmup.md + 2026-10-15_i10-vision-int8-verdict.md）：舰队换新完成（298694a 生产、spot 3/3）；op census 收口（228ms 设备侧无隐藏热点）；**I9 闭环**（warmup 修复，inference 433→273.6，客户端已同步 robo_src）；**I10 预检走完判不立项**（fc2 结构地板 + 实数仅 −6~7ms，降级 backlog，数据/工具留档）——**性能线与量化域双双收官**。服务器：4 芯 10-14 代际健康 + 回退 7/7 + available ~298GB。

**下轮 goal 建议（抄一项即可）**：
1. **长跑例行化**（fleet_watch 每日快照 + spot_eval 晨检跑 2-3 天：respawn/内存/档表外 L/新代际稳定性 → 固化 cron 或手跑清单——工具全就位，缺的只是跑出规律；可顺带 2347 僵尸清理（重启 apxinf_rust 容器演练 + 换新复验 spot））

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（回退桶 /data/apxinf/serve 由 v3 supervisor 认养）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x——push 通道不带执行位）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + 测前 spool 清场验单实例（代际现象，见 memory）**；msprof 用最小采集纪律（ascend-msprof skill：迭代数控制 task 行 <5 万、用毕删目录）；**舰队操作前先 fleet_watch 看指纹快照、重启只走 start_gear_supervisor.sh（宿主起必败——见 memory fleet-infra-container-topology）**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 长跑例行化** —— 运维面收官。
- **为什么**：性能线已收官（I9 闭环 + I10 判不立项），系统进入生产稳态期；换新后的舰队还没跑出过 2-3 天的连续观测（respawn 频率、内存走势、档表外 L、代际稳定性都是单日快照，无趋势）。
- **怎么做**：每天一次 `bash /data/apxinf/fleet_watch.sh`（快照存档）+ `docker exec -d apxinf_npu bash /data/apxinf/spot_eval.sh`（三谱系晨检，结果按天戳 jsonl）；2-3 天后汇总规律固化（cron 或手跑清单）。可选顺带：2347 僵尸清理 = 重启 apxinf_rust 容器（**先 fleet_watch 留快照、重启只走 start_gear_supervisor.sh**，重启后 spot 3/3 复验）。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 fleet = 新二进制 298694a（冷启动 6.57s/芯）；model_ms 246.9 = 设备侧 228ms（census 分布健康）+ glue 19ms；warmup 修复后 per-call inference 273.6（2026-10-15 I9）。性能线与量化域收官（I10 判不立项，mm 域再无未开垦地）**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略） | qmd per-token 终点；单一因子集三谱系 |
| I3 | 动态 L 分桶（gear） | ✅ 转正 + 换新（298694a 代） | 回退面 151-157 新生代验证 ✓ |
| I5 | OM 冷启动 lazy | ✅ **生产兑现**（687ms/6.57s 实测） | 零物化 + 并行转置 + serve_min |
| I6 | eval 全链 inproc | ✅ 闭环 | 配方 cann901_eval_inproc.sh |
| I7 | 多 checkpoint 泛化 | ❌ **用户决策放弃**（2026-10-15） | 行为面验收的第二只有 LIBERO 能力的 π0.5 无现成来源（官方只放一只），自训成本在训练侧不在推理管线；管线留档全参数化，未来有需求可重启 |
| I8 | 舰队换新二进制 | ✅ **执行完成**（2026-10-14，spot 3/3） | 孤儿清理 + pid 假阳修复一并落地 |
| **I9** | **客户端推理调用链（原命题 tokenize 前缀缓存）** | ✅ **闭环**（2026-10-15，summary/2026-10-15_i9-firstcall-warmup.md） | **归因证伪 + warmup 修复**：「tokenize 186ms」四步取证证伪——tokenizer 实为 0.43ms/调用、客户端全链稳态仅 15-25ms；真凶 = npu-ge 无 warmup，首调用 eager NPU 算子编译 3.9s 摊进 27 次均值（eval_libero 原只对 npu-torch 调 warmup）。修复 = `GeServePi05Policy.warmup()`（不发请求零数值改动）+ eval_libero 放宽 warmup 条件 → **inference 433.3→273.6（−37%）、server_processor 186→25、行为保持（success 1.0）**。剩余稳态 gap 25ms（unfold 5.9+pipeline 转换税+to_frame）不立项（要绕开 lerobot 同代码路径设计，ROI 低）；L 漂移 gear 下零感，需求消失；tokenize 缓存/查表方案归档（前提证伪，per-int 查表还有 "▁-" 跨界合并陷阱）。逐调用计时开关 `APXINF_GE_PERCALL=1` 常驻 |
| **I10** | **vision 段 int8**（SigLIP 27 层 mm） | 📉 **预检走完判不立项，降级 backlog**（2026-10-15，summary/2026-10-15_i10-vision-int8-verdict.md） | **预检四步全走完**：① 权重谱过关（补扫当年漏的 q/k/v：总体 0.893% ≈ prefix 0.895%，无障碍）；② 激活 dump 就位（40 真帧含空视图 pad 包络，SigLIP 温和 ≤15 vs Gemma 559，calib_vision_v1.safetensors 267MB 留档）；③ L2-lite 模拟：α=0.5 定案（全量 med 1.32% 回先例带 0.66-1.42%；α 再大全面恶化——vision 是权重侧瓶颈）**但 vfc2 结构性超带 1.86/4.1%**（gelu 输出唯一无归一化站 + 权重行 outlier；α/权重 clip/s-floor 三旋钮全救不动，clip 反而爆炸）；④ **收益重估**：「2.41×/−18ms」是合成形状虚高（C2 实数 1.5×）→ 全量 −10.3ms 带行为风险，mixed（fc2 留 f16）**−6~7ms = model 的 2.5-3%** → 战役代价（引擎 vision 图 int8 发发 + 校准 + 烤桶 + L2-L4 + 行为全量）不值。未来要榨：前置全留档可秒重启 |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-14_fleet-renewal-cleanup-ops
D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-15_i9-firstcall-warmup
D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-15_i10-vision-int8-verdict
