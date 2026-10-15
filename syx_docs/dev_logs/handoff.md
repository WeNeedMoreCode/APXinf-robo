# Handoff（2026-10-15 换新收口 + op census + I9/I10 立项记录 → 下一轮压缩用）

## 状态一句话

**10-14 轮**（summary/2026-10-14_fleet-renewal-cleanup-ops.md）：gear 舰队换新生产兑现（**298694a，from_map_serve 687ms/ckpt 6.57s，spot 3/3**）+ 孤儿全清 245 只（+176GB）+ 运维三件套（fleet_watch / spot_eval / start_gear_supervisor）；**infra 定案：supervisor/serve 全家住 apxinf_rust 容器，判活只信 environ 指纹**（memory fleet-infra-container-topology）。**10-15 轮**（summary/2026-10-15_op-hotspot-census.md）：**op 级热点普查**（最小 msprof 12 迭代/278MB）——设备侧 228ms：qmd 37% / ABF 元素融合 14%（fusion pass 实证）/ mm 13%（vision f16 主体）/ 空隙 0，总量与生产 246.9 自洽；**实测无隐藏热点，性能线以此收口**；复测工具 prof_hotspot_1015.sh 入库。**I9（tokenize 前缀缓存，−186ms 目标）与 I10（vision int8，−18ms 预期）已记录未立项**（handoff ④）。多 ckpt 卡点维持。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在两份 summary）——① 换新完成态（298694a 生产运行、2026-10-14 代际、spot 3/3 验收过）；② infra 拓扑事实（supervisor/serve 住 apxinf_rust 容器、start_gear_supervisor.sh 唯一启动姿势、fleet_watch environ 指纹判活、pid 文件两坑）；③ census 结论（228ms 分布健康、ABF 实证 fusion pass 在干活、TransData 14ms=vision 激活 ND→NZ 观察项、复测工具就位）；④ I9/I10 入口在 handoff ④ 表。丢弃：换新三连坑排障过程、census 的 msprof 往返细节——战报已记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-15，见 summary/2026-10-14_fleet-renewal-cleanup-ops.md + 2026-10-15_op-hotspot-census.md）：舰队换新完成（298694a 生产、spot 3/3）；op census 收口（228ms 设备侧无隐藏热点，qmd 37%/ABF 14%/mm 13%，空隙 0）；待办 = I9 tokenize 前缀缓存（−186ms）> I10 vision int8（−18ms）> 长跑例行化；多 ckpt 卡点。服务器：4 芯 10-14 代际健康 + available 302GB。

**下轮 goal 建议（抄一项即可）**：
1. **I9：客户端 tokenize 前缀缓存 + state 直查表**（推理路径最后一个大项：prompt 前缀 episode 内不变 + 离散化 bin→tokenid 纯确定性 → tokenize 186→<5ms、**inference 433→~250ms**；顺带修 L 漂移（144/145）；验证 = token 序列逐位对拍 + 行为 spot。详见 handoff ④ I9 行）
2. **I10：vision 段 int8**（量化域最后一块地：M=768 大段机制同 prefix 已证，预期 −18ms；工程量 = 校准战役重打一遍，SigLIP LayerNorm 分布 + 空视图 -1 pad 包络两个新变量；**先做权重谱预检再决定投入**。详见 ④ I10 行）
3. **长跑例行化**（fleet_watch 每日快照 + spot_eval 晨检跑 2-3 天：respawn/内存/档表外 L/新代际稳定性 → 固化 cron 或手跑清单）
4. **多 checkpoint 泛化**（管线全参数化就绪；**卡点 = 第二只 checkpoint 到位**，选前先确认）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（回退桶 /data/apxinf/serve 由 v3 supervisor 认养）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x——push 通道不带执行位）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + 测前 spool 清场验单实例（代际现象，见 memory）**；msprof 用最小采集纪律（ascend-msprof skill：迭代数控制 task 行 <5 万、用毕删目录）；**舰队操作前先 fleet_watch 看指纹快照、重启只走 start_gear_supervisor.sh（宿主起必败——见 memory fleet-infra-container-topology）**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. I9 tokenize 前缀缓存** —— 客户端工程，不碰引擎。
- **为什么**：op census 已证引擎侧无大项；inference 433ms 里 186ms 是 processor 链（state 离散化→prompt 拼接→tokenizer CPU 全量重跑），而 prompt 前缀 episode 内不变——纯循环不变量没外提。且 torch 基线不付这笔（prompt 固定），调用级对比我们反而吃亏。
- **怎么做**：eval 客户端（src/apxinf_robo 的 processor 链）拆前缀/后缀——前缀 token ids 缓存一次；state 后缀的离散化 bin→tokenid 映射是确定性函数，预计算成查表。验证三层：token 序列逐位对拍（对拍梯 L3，新旧链同输入）→ spot 三谱系 → 全量 eval。顺带 L 漂移（144/145）若因 padding 顺手固定。

**2. I10 vision int8** —— 量化域收官战。
- **为什么**：census 把 MatMulV2 30.8ms 主体定位到 vision f16 mm（M=768 与 prefix 同款算力瓶颈形态，prefix 已证 2.41×）。
- **怎么做**：① 权重谱预检（vision 谱未测过，rel_rms 差则止损）；② SigLIP 真激活 dump（LayerNorm 非 RMSNorm，Gemma outlier 经验不搬；**空视图 -1 pad 成分必须进包络**——校准错配=行为翻车的 v3 教训）；③ α sweep 离线筛 → 烤桶 → 对拍梯 L2-L4 全走。排在 I9 后（收益/工程量比差一个量级）。

**3. 长跑例行化** —— 工具全就位（fleet_watch/spot_eval 参数化），缺的只是跑出规律并固化。

**4. 多 ckpt** —— 卡点在资源不在工程（先确认第二只 ckpt 到位再选）。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 fleet = 新二进制 298694a（冷启动 6.57s/芯）；per-call 246.9ms（spot object 实测）= 设备侧 228ms（census 分布健康）+ glue 19ms**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略） | qmd per-token 终点；单一因子集三谱系 |
| I3 | 动态 L 分桶（gear） | ✅ 转正 + 换新（298694a 代） | 回退面 151-157 新生代验证 ✓ |
| I5 | OM 冷启动 lazy | ✅ **生产兑现**（687ms/6.57s 实测） | 零物化 + 并行转置 + serve_min |
| I6 | eval 全链 inproc | ✅ 闭环 | 配方 cann901_eval_inproc.sh |
| I7 | 多 checkpoint 泛化 | 管线就绪；卡点 = 第二 ckpt | |
| I8 | 舰队换新二进制 | ✅ **执行完成**（2026-10-14，spot 3/3） | 孤儿清理 + pid 假阳修复一并落地 |
| **I9** | **客户端 tokenize 前缀缓存 + state 直查表** | ⏸ **已记录未立项**（2026-10-15） | **推理路径最后一个大项**：prompt 前缀 episode 内不变 + state 离散化 bin→tokenid 映射纯确定性可预计算表 → tokenize 186→<5ms、**inference 433→~250ms**；顺路 = prefix 嵌入前缀行缓存（2.5ms）+ L 漂移（144/145）同源修掉；验证 = token 序列逐位对拍（对拍梯 L3）。引擎侧静态化已榨干（styles/euler/rope/因子四大战役全闭环，2026-10-15 op census 实测无重复计算大项）；prefix 双向 attention 无 KV 前缀缓存数学基础（结构死路，勿惦记） |
| **I10** | **vision 段 int8**（SigLIP 27 层 mm） | ⏸ **已记录未立项**（2026-10-15） | **量化域最后一块地**：census 定位 MatMulV2 30.8ms 主体 = vision f16 mm，M=768 大段与 prefix 同款算力瓶颈（prefix 已证 2.41×/−18ms）→ 预期 **−18ms（246.9→~229）**。工程量 = prefix int8 战役重打一遍：SigLIP 激活 dump（LayerNorm 非 RMSNorm，Gemma outlier 经验不直接搬）+ **空视图 -1 pad 输入的分布包络**（校准错配=行为翻车教训）+ α sweep + 权重谱预检（vision 谱未测过，先看 rel_rms 再立项）+ 行为验收全量。排序在 I9 之后（收益/工程量比差一个量级）；打完此块 mm 域量化到头（flow attention 小 M 已判不值、其余热点非 mm 层） |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-14_fleet-renewal-cleanup-ops
