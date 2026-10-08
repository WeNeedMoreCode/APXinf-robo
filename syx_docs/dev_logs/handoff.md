# Handoff（2026-10-08 晚 分解式 w8a8 出局判决 → 下一轮压缩用）

## 状态一句话

**分解式 w8a8 出局（2026-10-08 晚，全数字见 summary/2026-10-08_qbmv3-pertoken-template-wall.md）**：上轮判"唯一存续"的 DQ+TQP+QBMV3 链在 run 阶段证伪——per-token 语义在 310P kernel 模板清单不存在（core 200 只实例化 u64-scale+无 pertoken；接 pertoken_scale → KeyError '21'，源码+运行时双证）；no-pertoken 唯一形态 = 静态 x scale-only（运行确认 0.027%），且三算子链 m=50 比 qmd **慢 2×**（0.119 vs 0.059ms）——语义、性能双杀。**qmd per-token = 310P 量化侧终点形态，量化侧全线收束**（四条路线判决表见战报）。剩余可动杠杆 = 行为面（校准 v3）与生产面（task7/扩桶）。上轮（qmd 静态 x_scale 探明）见 summary/2026-10-08_qmd-xscale-static-verdict.md。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在两份 summary）——① 终局：分解式 w8a8 出局（per-token 模板墙 KeyError '21' + 静态形态 2× 慢双杀；qmd per-token = 量化侧终点）；判据升级 = `*_tiling_key.h` 模板清单 + `platform_config/<SoC>.ini` AIC_version（core 200=310P / 220=新芯片）强于注册表 json（simplifiedKey 假门）——skill #44 + memory 已更新；② probe 资产：GEB_QMD_Z3（=1 模板墙复现 / =2 DQ 单算 / =3 no-pertoken 语义解码）+ 上轮 XS/WQ/WA/Z/Z2；③ 纪律不变：手烤 OM fusion off、A/B 隔离等价生产根、eval timeout ≥1800、scp 直推单文件（Syncthing 本地未跑时）；服务器 chip 3 空闲（chip 2 被他人 python 占用、4/5 有 ge_model_probe 残留进程待核）。丢弃：probe 迭代过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-08 晚，见 summary/2026-10-08_qbmv3-pertoken-template-wall.md）：量化侧全线收束——分解式 w8a8 出局（per-token 模板墙 + 静态形态 2× 慢），**qmd per-token 是 310P 量化终点形态，0.53× 无路径终审闭合**。两仓已推平（引擎含链 Z3 probe；skill #44 + 速查表改判 + memory 更新）。

**下轮 goal 建议（抄一项即可）**：
1. **校准 v3（行为面优先，当前推荐首项）**——flow 侧 per-step 感知因子 + prefix 多帧；验收 = actions <8% + 全量 10/10 + flow int8 行为梯（回收 flow int8 -5.4ms 的唯一路径；量化侧已收束，行为面是最后一块可动杠杆）。入口：上轮战报 summary/2026-09-30_flow-int8-segment-fusion-verdict.md 的回滚资产（env 开关 + 因子四件套 + 配方）+ 校准 v2 管线（2026-09-28 战报）
2. **task7 segfault 取证 + 扩预置桶**——py-spy 已装；149-156 桶并入生产管理（⚠ 共享 supervisor 僵尸须用户决策）；顺带：chips 4/5 两个 ge_model_probe 残留进程（6.1GB each）核实清理

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；int8 eval 用隔离根 serve_i8 + mini_sup_i8.sh（**当前为回滚位脚本**——再启 flow int8 须改回 GEB_FLOW_* env + int8 flow OM）；**A/B 隔离 = 等价生产根**（全谱系桶 + supervisor）；eval timeout ≥1800；**新量化算子先过 skill 速查表 + #44 判据**（tiling_key.h 模板清单，勿信注册表 json）。

## ④ 性能优化方向清单（2026-09-23 收集，按优先级）

现状锚点：**eval 口径 model_ms P50 = 325.3ms**（含 serve spool 轮询）＝376ms 基线的 0.87×；纯引擎稳态 310.3ms（0.82×）。逐段（serve 实测/调用）：**vision 65-68 / prefix 127-136 / flow 100-118ms**（flow = 10 步欧拉 ≈ 10ms/步 + 每步 x d2h + styles h2d；bench 口径 flow 段内 7.6ms/步）。理论裸算力下限（mm 已 ~20 TFLOPS≈峰值）：粗估 ~200-220ms，**剩余 ~90-120ms 是 host glue + 调度 + 段间往返**——大头不在算子。

| # | 方向 | 预期收益 | 机制 | 风险/前置 |
|---|---|---|---|---|
| **A** | ✅ 已落地（2026-09-23，GEB_SERVE_FAST）段间设备直连 + styles 设备驻留 | 实测 −45~62ms | 同流顺序链 bit 恒等 | 已过验证梯 + 全量回归 10/10 |
| **B** | ✅ 已落地（同 A） | 并入 A | — | — |
| **C** | ✅ 已落地（2026-09-24）：in-process serving（GeServe 门面 + PyO3 + allow_threads 修复）。剩余 = A3 eval 全链 inproc（abi 墙 + 宿主重写 vs ~5ms/帧） | spool 15ms 在 inproc 环境免 | 引擎单实现三入口 | 保持可选 |
| **D** | ✅ prefix int8 生产化收官（2026-09-28）：qmd 7 投影×18 层 + v2 校准 + 10/10；prefix 105→87ms，直调 sum 228ms=0.607× | 已兑现 | — | 已闭环 |
| **E** | ✅ C1 vision glue 修复（2026-09-24）：零拷贝 f16 字节视图 + 挂流单次 sync → vision 59.4ms | 已兑现 −6.6ms | `GEB_SERVE_TIMING=1` 常驻 | 剩 prefix asm 已修、flow enq 2.4ms 小项 |
| **F** | **生产化配套**（非性能项）：动态 L 主体落地（剩 149-156 桶并入生产 supervisor + task7 segfault 取证）；OM 懒加载（3.7GB prefix 每桶 ~1min）；生产 supervisor 僵尸（Sep 24 起）待用户决策重启 | 部署 TTFB/运维 | — | 低 |
| **G** | ~~量化侧新算子~~ **✗ 全线收束（2026-10-08 双轮终审）**：qmd 静态 x ✗ / w8a16 模板墙 ✗ / 分解式 per-token 模板墙 ✗ / 分解式 static 2× 慢 ✗——**qmd per-token = 310P 量化终点形态**；flow int8 -5.4ms 的回收走校准 v3（行为面，非算子面） | — | — | 判决表见 2026-10-08 两份战报 |

**建议路线**：**下一轮 = 校准 v3**（② 菜单 1——量化侧收束后行为面是唯一可动杠杆，flow int8 回滚资产 + v2 管线都在）；task7/扩桶随后。A3 eval 全链 inproc 保持可选。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-08_qbmv3-template-wall.txt（分解式 w8a8 出局：KeyError '21' 源码定罪 + no-pertoken 语义解码 + 2× 慢 kill-shot）
