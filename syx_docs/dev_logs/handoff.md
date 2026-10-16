# Handoff（2026-10-16 消融终裁闭环 → 下一轮压缩用）

## 状态一句话

**10-15 深夜 T4R 闭环**（summary/2026-10-15_t4r-dyn-static-convergence.md）：真帧互差 13.1% 定位 + E1 证伪 range-tiling + **GEB_PREFIX_POOL 池化修复**（t4 5/5、−14.1ms/replan 实测、回退桶真退役、133-136 补烤）。**10-16 晨消融终裁**（summary/2026-10-16_dyn-structural-ablation-verdict.md，用户指定 goal）：**「怪 GE 还是怪组装」= 怪 GE**——组装三维度（bias 折叠 / rope·qswap Data 化 / smooth Const 化）逐一在静态图内复现，输出与 static 基线 **bit 级一致**（互差 0.00%，n_in 170/262/138 vs 260 纯接口化妆）；原 V0（权重 Const 化）证实非差异维度（静态桶与 dyn 同在 GEB_WCONST=1 下烤，昨晚「权重 Data 化」注释系误标已纠）；唯一存活维度 = **desc -1 + dynamicDims 分档编译（MultiBatchClone 逐档特化）本身**，且不可纯净隔离（SetDims 145012 强制携带已证惰性的伴随维度）——**dyn 复活路线正式关闭，池化终审盖章**。引擎 2 commit（子模块 fork/ascend-port 3e47e8e：三门控 GEB_ABL_BIAS/ROPE/SMCONST + prefix 作用域修）；工具 abl_struct_1016.sh；服务器留 tl154_{v1bias,v2rope,v4sm} 三实验桶 ~9.3GB（清理候选）。更早轮次（10-14 舰队换新/孤儿清理、10-15 op census/I9 warmup/I10 判不立项/容器被杀收缩单芯）见对应 summary，此处从略。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**——① **生产 = GEB_PREFIX_POOL 池模式**（supervisor spawn：`GEB_PREFIX_POOL=$OM` + `GEB_OM_DIR=$OM/tl200_i8`、无 GEB_CKPT_SERVE_MIN、llist 仍传；引擎侧 gear_mode() POOL 压 false 等三件）；② **消融终裁 = GE 动态分档通路固有**（组装三维度 bit 级惰性、权重 Const 本就非差异、dyn 复活关闭）；③ 工具链入口：golden_gen/fix_t4、ab_t4_mutual、abl_struct_1016、GEB_E2E_DUMP_MID；④ 遗留：spot 三谱系未复验、池 LRU cap8 未压测、~9.3GB 实验桶清理候选。丢弃：消融轮的崩跑往返（summary §三踩坑已留档）。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-16，见 summary/2026-10-16_dyn-structural-ablation-verdict.md）：**生产 = 单芯池模式不变**（chip4、t4 5/5、−14.1ms/replan）；**消融终裁已闭环：13.1% 互差全权归于 GE 动态分档编译（-1 dims / MultiBatchClone 逐档特化），组装三维度 bit 级惰性，dyn 复活路线关闭，池化终审盖章**。133-136 档已补烤未验；实验桶留档可清。

**下轮 goal 建议（抄一项即可）**：
1. **池模式全谱系复验 + 例行化**：spot_eval 三谱系（object/goal/spatial 各 1 task）→ 验证 133-136 补烤档 + 池 LRU 行为 → fleet_watch 每日快照固化 2-3 天
2. **清理收尾**（半小时）：tl154_{v1bias,v2rope,v4sm} ~9.3GB + tl_dyn_g154 2GB 清或归档；2347 僵尸随下次容器重启自清

**纪律**：手烤 OM 必带 fusion off env；**池模式静态桶烤法 = 无 DYN_LLIST 的 prefix 段烤**（GEB_SEG=prefix、GEB_TOKENS=$L、GEB_SAVE=tl{L}_i8/prefix_real.om——260 接口；GE 单档 dynamicDims 烤不出 rc=-7）；qmd smooth = 1/s 乘法约定；eval 默认生产根 /data/apxinf/serve_gear（单芯 chip4 池模式）；eval 必须容器内跑（`docker exec -d apxinf_npu bash <脚本>`）；results-jsonl 有记录即跳过（复验换新文件）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、容器内 kill 要 namespace 对齐；**119 ssh 必带 kex 配方；上行断流走 push119.sh（push 后 chmod +x）**；docker exec -d 必须脚本文件形态；**跨进程对拍必须同芯同时代 + resp 发完即拷贝 + spool 清场验单实例（代际现象）；合成/垃圾 payload 下 flow 混沌地板 ~11-14%——A/B 数值分歧必须用真帧 golden**；**serve stdout.log 含二进制（权重上传）——读日志先 `tr -d "\000"`**；msprof 最小采集纪律；**舰队操作前先 fleet_watch、重启只走 start_gear_supervisor.sh**；**共享主机纪律：我们只准用 chip 4/5（同事 vLLM 占 0-3/6-7）；探针/加载类批处理合并进单进程（一次加载跑完所有测量）；常驻面任何扩张先问用户**；**消融门控 GEB_ABL_BIAS/ROPE/SMCONST 已入库（SMCONST 仅 prefix 作用域——reg_i8 为 prefix/flow 共用，flow 是对照组不可动）**；bash 坑：`local a=$1 b=x_$a` 单行多赋值 $a 取外层空值——逐行写。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 池模式全谱系复验** —— 生产面稳定性观察：133-136 是深夜补烤、从未被生产路径撞过；LRU cap8 在同 run 撞 >8 个 L 时会驱逐重载（观察是否无感）。跑法：spot_eval 三谱系各 1 task 换新 jsonl，晨检式连跑两三天。
**2. 清理收尾** —— 磁盘 432GB 无压力，纯整洁问题；实验桶是判决证据物化，summary 已入库可清。

## ④ 性能优化方向清单（2026-10-15 更新）

现状锚点：**生产 = 单芯池模式（chip4 serve ×1，GEB_PREFIX_POOL；2026-10-15 深夜起）；prefix p50 87.9ms（−14.1ms/replan 已实测）；warmup 修复后 per-call inference 273.6；spatial t4 = 5/5（池模式复验）**。

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
| — | op 热点 census | ✅ 2026-10-15（summary/2026-10-15_op-hotspot-census.md） | 设备侧 228ms：qmd 37% / ABF 融合 14%（pass 实证）/ mm 13%；空隙 0；复测工具 prof_hotspot_1015.sh |
| — | TransData 14ms（vision 激活 ND→NZ） | 观察项 | 编译器格式规划税，6%，ROI 低 |
| — | 数值代际现象 | 观察项（现役 = 10-14 代） | 行为面多代际全过 |
| — | 2347 僵尸 | 待用户需要时重启 apxinf_rust 即清 | 只占 pid 位不占内存 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-15_container-kill-singlechip-t4-verdict
