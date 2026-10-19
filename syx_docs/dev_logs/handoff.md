# Handoff（2026-10-19 立案四件遗留 → 下一轮压缩用）

## 状态一句话

**10-16 全天两役**：① 晨**消融终裁**（summary/2026-10-16_dyn-structural-ablation-verdict.md）：「怪 GE 还是怪组装」= **怪 GE**——组装三维度（bias/rope·qswap/smooth）逐一静态图内复现全部 bit 级一致（互差 0.00%，接口 260/170/262/138/14 纯化妆），唯一元凶 = desc -1 分档编译本身，**dyn 复活路线关闭、池化终审盖章**。② 下午**Range padding + mask 化生产化**（summary/2026-10-16_range-padding-mask.md，用户拍板）：**精确 26 桶 → stride-8 网格 9 桶**（{136..200}，GEB_ATTN_MASK softmax 加性 mask + GEB_POOL_GRID 引擎侧 L→桶界映射、**客户端零改动**）；数值验收：l0 **bit 级一致**、actions vs torch 3.7%（static 4.3%）、互差 3.8%（等效量级新个性）；行为验收：**t4 ×5 = 5/5（全程仅 1 次 lazy load）+ 三谱系 spot 3/3（与基线完全对照）**；**表外 L 根除、局内 L 漂移归一零装载**（意外发现：goal:9 一局曾连装 4 桶）、磁盘 49→17GB。生产 = serve_range_supervisor.sh（回滚 = 改回 serve_gear_supervisor.sh，精确桶留档）。引擎 8 commit（fork/ascend-port 3e47e8e→fix5，含 bind_names 平行表根除 names/binds 不对齐老地雷）。更早轮次见对应 summary。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**——① **生产 = range padding 池模式**（supervisor = serve_range_supervisor.sh：`GEB_PREFIX_POOL/FLOW_POOL=om_cache/grid8` + `GEB_POOL_GRID=8(+MIN136/MAX200)` + `GEB_ATTN_MASK=1` + llist=九桶网格 + OM_DIR=grid8/tl200_i8；客户端零改动发真 L，引擎侧 pad + mask + flow rope 按真 L）；② 消融/per-token 终审均闭环（GE 分档编译固有、组装无罪、310P 无 per-token——gitcode ops-transformer master 盖章）；③ 网格桶烤法 = GEB_SEG=prefix/flow + GEB_ATTN_MASK=1 + GEB_TOKENS=P + SAVE 到 grid8/tl{P}_i8；④ **四件遗留已立案为下轮 goal**（qmd x_scale 静态化 / TBE 孤儿死亡循环 / range 观察期 / pool cap 8→9）。丢弃：range 上线当日 5 连修往返（summary §三b 已留档）。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-19，见 summary/2026-10-16_range-padding-mask.md + _dyn-structural-ablation-verdict.md）：**生产 = 单芯 range padding 池模式**（chip4、grid8 九桶 + softmax mask + GEB_POOL_GRID 映射；表外 L 根除；t4 5/5 全程 1 次装载 + spot 三谱系 3/3 与基线对照；数值 l0 bit 级/actions 3.7%；观察期例行进行中）。消融终裁、per-token 上游终审均闭环。回滚 = serve_gear_supervisor.sh + 精确 26 桶（留档）。

**下轮 goal（四件套，用户拍板 2026-10-19）**：
1. **qmd x_scale 静态化终审**（性能最后一杠杆）：flow 77.8ms 中 ~70ms 纯设备时间，大头 = qmd 算子内逐 token 激活量化流水；目标 = x_scale 换静态校准值砍 quant 流水，预期 flow 75→~50ms、端到端 230→~205ms（0.53× 最后一段）。已知：旧形态一次 bin 忽略输入（09-30 早），IR 面未探明；打法 = GEB_OPTEST=qmd 探针族 + IR/slog 取证，撞墙则 0.53× 重新谈判收线
2. **TBE 孤儿死亡循环根因**：supervisor 连续代 serve ~3min 静默死（无 panic、前台同 env 全绿、pkill 清场重发即愈；启动偶发慢 ~8min 一并解释）。无人值守重启场景有风险。取证面 = CANN slog 崩代 vs 健康代对比
3. **range 观察期收尾 + 清理**：隔日 spot_eval_range 三谱系 ×2 + fleet_watch 快照 → 稳定后清精确 26 桶 + 实验桶（tl154_v* 9.3GB、tl_dyn_g154 2GB、dump 目录；回滚保险期结束）
4. **pool cap 8→9 一行修**（下次重启窗口顺手）：`pool_cap: 8` 硬编码（PrefixMech 构造）< 桶数 9——满谱系撞 9 桶会驱逐重装（2.7s/次）；改 9 或 env 化 + 子模块两步提交

**纪律**：手烤 OM 必带 fusion off env；**池模式静态桶烤法 = 无 DYN_LLIST 的 prefix 段烤**（GEB_SEG=prefix、GEB_TOKENS=$L、GEB_SAVE=tl{L}_i8/prefix_real.om——260 接口；GE 单档 dynamicDims 烤不出 rc=-7）；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（单芯 chip4 池模式）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + spool 清场验单实例（代际现象）；合成/垃圾 payload 下 flow 混沌地板 ~11-14%——A/B 数值分歧必须用真帧 golden**；**serve stdout.log 含二进制（权重上传）——读日志先 `tr -d "\000"`**；msprof 最小采集纪律；**舰队操作前先 fleet_watch、重启只走 start_gear_supervisor.sh**；**共享主机纪律：我们只准用 chip 4/5（同事 vLLM 占 0-3/6-7）；探针/加载类批处理合并进单进程（一次加载跑完所有测量）；常驻面任何扩张先问用户**；**消融门控 GEB_ABL_BIAS/ROPE/SMCONST 已入库（SMCONST 仅 prefix 作用域——reg_i8 为 prefix/flow 共用，flow 是对照组不可动）**；bash 坑：`local a=$1 b=x_$a` 单行多赋值 $a 取外层空值——逐行写。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. qmd x_scale 静态化** —— 0.53× 性能目标的最后一段。为什么是它：flow 段 70.6ms 设备时间是三段里 int8 动不了的最大块（09-30 战报的带宽模型 + 实测排除法定位到 qmd 执行面）；量化流水（激活逐 token 量化）是其中唯一没动过的部分。怎么做：先 IR 取证（qbmm/qmd 的 x_scale 输入编译行为）再定改法——历史上「静态 x」有两代前科（bin 忽略输入、f16 值域陷阱），所以是「终审」不是「实施」：撞墙即触发 0.53× 重新谈判。
**2. TBE 孤儿死亡循环** —— 生产可靠性项。现象/复现/清场 workaround 全在 range-padding 战报 §三b；根因疑 TBE 编译守护跨代残留毒害 GE init（同 10-12 重启风暴）。无人值守重启（掉电恢复/容器重启）可能撞上需人肉——值不值得半天 slog 取证看这个场景的真实概率。
**3. range 观察期** —— 例行：新模式只有一天生产行为数据；两三天 spot 晨检全绿即收尾清旧资产（精确桶是回滚保险，期内不动）。
**4. pool cap** —— 已知小 bug：cap 硬编码 8、桶有 9 只，满谱系连跑时第 9 桶驱逐第 1 桶、回撞付 2.7s 重装。单任务永远碰不到。修是一行，趁重启窗口带上（和 #2/#1 的部署窗口合并）。

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
| **P1** | **qmd x_scale 静态化**（0.53× 最后一杠杆） | 🎯 **下轮 goal #1**（2026-10-19 立案） | flow ~70ms 设备时间的执行面大头；预期 flow 75→~50、端到端 230→~205；两代前科（bin 忽略输入、f16 值域陷阱）——先 IR 终审再实施，撞墙即 0.53× 重新谈判 |
| — | TBE 孤儿死亡循环 / range 观察期 / pool cap 8→9 | 🎯 下轮 goal #2-4 | 见 ②b 注解；cap<桶数是已知一行 bug，趁重启窗口修 |
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-16_ablation-verdict-range-padding-plan
