# Handoff（2026-10-15 换新收口 + op census + I9 闭环（warmup 修复）→ 下一轮压缩用）

## 状态一句话

**10-14 轮**（summary/2026-10-14_fleet-renewal-cleanup-ops.md）：gear 舰队换新生产兑现（**298694a，from_map_serve 687ms/ckpt 6.57s，spot 3/3**）+ 孤儿全清 245 只（+176GB）+ 运维三件套（fleet_watch / spot_eval / start_gear_supervisor）；**infra 定案：supervisor/serve 全家住 apxinf_rust 容器，判活只信 environ 指纹**（memory fleet-infra-container-topology）。**10-15 轮**（summary/2026-10-15_op-hotspot-census.md + **2026-10-15_i9-firstcall-warmup.md**）：op census（最小 msprof）实测设备侧 228ms 无隐藏热点（qmd 37%/ABF 14%/mm 13%，空隙 0）；**I9 闭环——归因证伪 + warmup 修复**：「tokenize 186ms」四步取证证伪（tokenizer 实为 0.43ms，全客户端链稳态仅 15-25ms），真凶 = npu-ge 无 warmup、首调用 eager 算子编译 3.9s 摊进均值；补 `GeServePi05Policy.warmup()`（不发请求零数值改动）+ eval_libero 放宽 warmup 条件 → **inference 433.3→273.6（−37%），行为保持**。I10（vision int8）已记录未立项；多 checkpoint 泛化经用户决策放弃（I7 关闭）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在三份 summary）——① 换新完成态（298694a 生产运行、2026-10-14 代际、spot 3/3 验收过）；② infra 拓扑事实（supervisor/serve 住 apxinf_rust 容器、start_gear_supervisor.sh 唯一启动姿势、fleet_watch environ 指纹判活、pid 文件两坑）；③ census 结论（228ms 设备侧分布健康、无隐藏热点、复测工具就位）；④ **I9 闭环结论**（tokenizer 0.43ms / 客户端稳态 15-25ms / 真凶首调用 eager 编译 3.9s / warmup 修复后 inference 273.6 / 逐调用开关 APXINF_GE_PERCALL=1）；⑤ I10 入口在 handoff ④ 表。丢弃：证伪四步的探针往返细节、msprof 往返——战报已记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-15，见 summary/2026-10-14_fleet-renewal-cleanup-ops.md + 2026-10-15_op-hotspot-census.md + 2026-10-15_i9-firstcall-warmup.md）：舰队换新完成（298694a 生产、spot 3/3）；op census 收口（228ms 设备侧无隐藏热点）；**I9 闭环**（tokenize 186ms 归因证伪 → 真凶首调用 eager 编译 3.9s 无 warmup → 修复后 **inference 433→273.6、行为保持**，客户端代码已同步 robo_src）；待办 = **I10 vision int8**（量化域最后一块）。服务器：4 芯 10-14 代际健康 + 回退 7/7 + available ~289GB。

**下轮 goal 建议（抄一项即可）**：
1. **I10：vision 段 int8**（量化域最后一块地：M=768 大段机制同 prefix 已证，预期 −18ms；工程量 = 校准战役重打一遍，SigLIP LayerNorm 分布 + 空视图 -1 pad 包络两个新变量；**先做权重谱预检再决定投入**。详见 ④ I10 行）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（回退桶 /data/apxinf/serve 由 v3 supervisor 认养）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x——push 通道不带执行位）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + 测前 spool 清场验单实例（代际现象，见 memory）**；msprof 用最小采集纪律（ascend-msprof skill：迭代数控制 task 行 <5 万、用毕删目录）；**舰队操作前先 fleet_watch 看指纹快照、重启只走 start_gear_supervisor.sh（宿主起必败——见 memory fleet-infra-container-topology）**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. I10 vision int8** —— 量化域收官战。
- **为什么**：census 把 MatMulV2 30.8ms 主体定位到 vision f16 mm（M=768 与 prefix 同款算力瓶颈形态，prefix 已证 2.41×）；打完此块 mm 域量化到头。
- **怎么做**：① 权重谱预检（vision 谱未测过，rel_rms 差则止损）；② SigLIP 真激活 dump（LayerNorm 非 RMSNorm，Gemma outlier 经验不搬；**空视图 -1 pad 成分必须进包络**——校准错配=行为翻车的 v3 教训）；③ α sweep 离线筛 → 烤桶 → 对拍梯 L2-L4 全走。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 fleet = 新二进制 298694a（冷启动 6.57s/芯）；model_ms 246.9 = 设备侧 228ms（census 分布健康）+ glue 19ms；warmup 修复后 per-call inference 273.6（首调用 eager 编译已移出计时面，2026-10-15 I9）**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略） | qmd per-token 终点；单一因子集三谱系 |
| I3 | 动态 L 分桶（gear） | ✅ 转正 + 换新（298694a 代） | 回退面 151-157 新生代验证 ✓ |
| I5 | OM 冷启动 lazy | ✅ **生产兑现**（687ms/6.57s 实测） | 零物化 + 并行转置 + serve_min |
| I6 | eval 全链 inproc | ✅ 闭环 | 配方 cann901_eval_inproc.sh |
| I7 | 多 checkpoint 泛化 | ❌ **用户决策放弃**（2026-10-15） | 行为面验收的第二只有 LIBERO 能力的 π0.5 无现成来源（官方只放一只），自训成本在训练侧不在推理管线；管线留档全参数化，未来有需求可重启 |
| I8 | 舰队换新二进制 | ✅ **执行完成**（2026-10-14，spot 3/3） | 孤儿清理 + pid 假阳修复一并落地 |
| **I9** | **客户端推理调用链（原命题 tokenize 前缀缓存）** | ✅ **闭环**（2026-10-15，summary/2026-10-15_i9-firstcall-warmup.md） | **归因证伪 + warmup 修复**：「tokenize 186ms」四步取证证伪——tokenizer 实为 0.43ms/调用、客户端全链稳态仅 15-25ms；真凶 = npu-ge 无 warmup，首调用 eager NPU 算子编译 3.9s 摊进 27 次均值（eval_libero 原只对 npu-torch 调 warmup）。修复 = `GeServePi05Policy.warmup()`（不发请求零数值改动）+ eval_libero 放宽 warmup 条件 → **inference 433.3→273.6（−37%）、server_processor 186→25、行为保持（success 1.0）**。剩余稳态 gap 25ms（unfold 5.9+pipeline 转换税+to_frame）不立项（要绕开 lerobot 同代码路径设计，ROI 低）；L 漂移 gear 下零感，需求消失；tokenize 缓存/查表方案归档（前提证伪，per-int 查表还有 "▁-" 跨界合并陷阱）。逐调用计时开关 `APXINF_GE_PERCALL=1` 常驻 |
| **I10** | **vision 段 int8**（SigLIP 27 层 mm） | ⏸ **已记录未立项**（2026-10-15） | **量化域最后一块地**：census 定位 MatMulV2 30.8ms 主体 = vision f16 mm，M=768 大段与 prefix 同款算力瓶颈（prefix 已证 2.41×/−18ms）→ 预期 **−18ms（246.9→~229）**。工程量 = prefix int8 战役重打一遍：SigLIP 激活 dump（LayerNorm 非 RMSNorm，Gemma outlier 经验不直接搬）+ **空视图 -1 pad 输入的分布包络**（校准错配=行为翻车教训）+ α sweep + 权重谱预检（vision 谱未测过，先看 rel_rms 再立项）+ 行为验收全量。下轮 goal 首位；打完此块 mm 域量化到头（flow attention 小 M 已判不值、其余热点非 mm 层） |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-14_fleet-renewal-cleanup-ops
D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-15_i9-firstcall-warmup
