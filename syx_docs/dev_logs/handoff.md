# Handoff（2026-10-15 换新 + census + I9/I10 收口 + 单芯收缩与 t4 判决 → 下一轮压缩用）

## 状态一句话

**10-14 轮**（summary/2026-10-14_fleet-renewal-cleanup-ops.md）：gear 舰队换新生产兑现（**298694a，from_map_serve 687ms/ckpt 6.57s，spot 3/3**）+ 孤儿全清 245 只（+176GB）+ 运维三件套（fleet_watch / spot_eval / start_gear_supervisor）；**infra 定案：supervisor/serve 全家住 apxinf_rust 容器，判活只信 environ 指纹**（memory fleet-infra-container-topology）。**10-15 轮**（summary/2026-10-15_op-hotspot-census.md + _i9-firstcall-warmup.md + _i10-vision-int8-verdict.md + **_container-kill-singlechip-t4-verdict.md**）：op census 无隐藏热点；**I9 闭环**（tokenize 186ms 证伪 → warmup 修复，inference 433→273.6）；**I10 判不立项**（fc2 结构地板 + 实数 −6~7ms）。**晚场三段**：① 同事 SIGKILL 双容器（我方取证批处理 30 分钟 5 次全量加载在共享主机上过显眼——对账认责）；② **拓扑收缩单芯**（用户指令「常驻一两张卡」：gear supervisor CHIPS=4、旧 chip0-3 归档、无回退、2347 僵尸随容器清零、fleet_watch/spot_eval 适配）；③ **回退桶退役验证失败 + 正向取证定性**（用户指令「正向解」）：gear t4 **3/5** vs 静态 **5/5**——回退桶编码的数值差异**真实且行为相关**；取证链：高 L 档 bug 证伪（垃圾 payload 混沌地板 11-14%）、golden 逐层 bisect 证 **static/dyn 是彼此等距近似**（kvk/kvv 剖面相同、互差 ~1% actions 级）、**dyn prefix 同 L 慢 13-16ms**（tiling 差异 = 修复红利）。终态：单芯无回退，t4 暂态 ~60%，下一战役 = dyn-vs-static 收敛（靶子已锁定）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**——① **拓扑终态 = 单芯**（chip4 gear serve ×1、无回退、v3 supervisor 不常驻、start_gear_supervisor.sh 唯一启动、fleet_watch GEAR_CHIPS 参数化、spot_eval CHIP=4、共享主机我们只准 4/5）；② I9 闭环（warmup 修复 inference 273.6）+ I10 判不立项；③ **t4 判决链**：gear 3/5 vs 静态 5/5（互差真实且行为相关）、static/dyn 彼此等距近似（golden 逐层剖面相同）、差异源 = dyn OM tiling/fusion（慢 13-16ms 旁证）、垃圾 payload 混沌地板 11-14%（A/B 必须真帧）；④ 下轮主线 = T4R 收敛战役（t4 真帧 golden → 逐层互差 → 钉 tiling/fusion → 复验 + 回收 14ms）。丢弃：容器被杀对账细节、A/B 探针往返——战报已记录（summary/2026-10-15_container-kill-singlechip-t4-verdict.md）。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-15 深夜，见 summary/2026-10-15_container-kill-singlechip-t4-verdict.md 等）：**拓扑 = 单芯**（chip4 gear serve ×1 + eval 宿主复用；无回退桶、v3 supervisor 不常驻；fleet_watch GEAR_CHIPS 参数化、spot_eval CHIP=4）；spatial t4 在 gear 暂态 ~60%（3/5，已知未修复）；同事 vLLM 占 0-3/6-7（共享主机，探针只准 pin 4/5）；I9 闭环（inference 273.6）、I10 判不立项。

**下轮 goal 建议（抄一项即可）**：
1. **t4 根因战役：dyn-vs-static 收敛**（正向解主线）：录 t4 真实帧 golden（L=151 主档）→ 逐层 dyn-vs-static **互差**定位（对拍工具已就位）→ 钉 dyn OM 构建的 tiling/fusion 对齐静态 → 互差 ~1%→<0.3% → t4 ×5 复验 ≥ 静态 → 回退桶真退役 + **白捡 ~14ms/调用**（dyn prefix 慢静态 13-16ms 实测）。详见 summary/2026-10-15_container-kill-singlechip-t4-verdict.md §五
2. **长跑例行化**（单芯新拓扑下的 fleet_watch 每日快照 + spot_eval 晨检；注意 spatial t4 未修复前 spot 三谱系会偶发红——预期内）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（单芯 chip4；回退桶已退役——临时拉桶工具 spawn_fallback_bucket.sh + 单芯 v3 脚本都在盘上）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + spool 清场验单实例（代际现象）；合成/垃圾 payload 下 flow 混沌地板 ~11-14%——A/B 数值分歧必须用真帧 golden**；msprof 最小采集纪律；**舰队操作前先 fleet_watch、重启只走 start_gear_supervisor.sh**；**共享主机纪律：我们只准用 chip 4/5（同事 vLLM 占 0-3/6-7）；探针/加载类批处理合并进单进程（一次加载跑完所有测量——2026-10-15 五连加载被同事杀容器教训）；常驻面任何扩张先问用户**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. t4 根因战役（dyn-vs-static 收敛）** —— 回退桶的正向替代。
- **为什么**：t4 = 刀锋任务，static/dyn 互差 ~1%（actions 级）足以翻转成功率（gear 3/5 vs 静态 5/5 实测）；两路径对 torch golden 的逐层漂移剖面相同（彼此等距近似）→ 差异来自**动态 OM 构建的 tiling/fusion 决策不同**（旁证：dyn prefix 同 L 慢 13-16ms）。收敛它 = 行为对齐 + 性能红利一石二鸟。
- **怎么做**：① 录 t4 真帧 golden（golden_gen 工具链 + t4 prompt，L=151 主档）；② `ab_golden_dyn_static_1015.sh` 思路改跑 t4 帧 + 增加 dyn-vs-static 互差逐层打印（kvk_l{i} 双方输出都落盘互比）；③ 互差集中层/算子 → 引擎侧钉 tiling/fusion（ge_builder 层面）；④ t4 ×5 gear 复验 ≥4/5 → 真退役；顺带回收 ~14ms。

**2. 长跑例行化** —— 单芯新拓扑的稳定性观察（同前：fleet_watch + spot_eval 跑 2-3 天固化；t4 未修复前 spatial 偶发红是预期内）。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 = 单芯拓扑（chip4 gear serve ×1，无回退桶；2026-10-15 深夜起）；model_ms 246.9（dyn prefix 比静态慢 13-16ms = t4 根因战役修复红利）；warmup 修复后 per-call inference 273.6；spatial t4 gear 暂态 3/5（静态 5/5，互差真实且行为相关）**。

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
| **T4R** | **t4 根因：dyn-vs-static 收敛**（回退桶正向替代） | 🔴 **立项（2026-10-15 深夜）** | **回退桶退役验证失败**：gear t4 3/5 vs 静态 5/5（双 jsonl 实证）——数值差异真实且行为相关（刀锋任务 + ~1% 互差）。取证定性：高 L 档 bug 证伪（垃圾 payload 混沌地板 11-14%，L144 对照与 L152 同差）；golden 逐层 bisect 证 static/dyn **彼此等距近似**（kvk/kvv 剖面相同：3-20%、l17 最差、kvv>kvk，vision 0.3% 无嫌疑）→ 差异源 = **动态 OM 构建 tiling/fusion 决策**（旁证 dyn prefix 慢 13-16ms）。路径：t4 真帧 golden → 逐层互差 → 钉 tiling/fusion → 复验 ≥4/5 → 真退役 + 回收 ~14ms。工具 ab_golden_dyn_static_1015.sh 等已入库 |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-15_container-kill-singlechip-t4-verdict
