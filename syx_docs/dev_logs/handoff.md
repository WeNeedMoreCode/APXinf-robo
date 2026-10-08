# Handoff（2026-09-30 flow int8 行为翻车回滚 + 段间融合否决 → 下一轮压缩用）

## 状态一句话

**goal ①（flow int8 / 段间融合）取证收官（2026-09-30，全数字见 summary/2026-09-30_flow-int8-segment-fusion-verdict.md）**：flow int8（gate,up,down 子集）数值面全绿（对拍零翻转 / golden step0 0.1%、actions 10.0% / serve flow 81→75.6ms、sum 225.1 = 0.598×）但**行为面 task0/task1 连续 520 打满 → 生产回滚 flow f16**（全桶已换 + mini_sup 已撤 env；回滚位 = Sep 28 验收的 prefix int8 v2 + flow f16 配置）；**段间融合（10 步单 OM）取证否决**（flow sync=70.6ms 纯设备时间主导，enq 仅 3ms，unroll 上界 ~3ms）；**qmd 小 M 收益被 per-op quant 开销吃掉**（-5.4ms vs 带宽模型 -30ms，单算+全图双取证）。历史里程碑见 ④ 与各战报。下轮 = ② 菜单。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-09-30_flow-int8-segment-fusion-verdict.md）——① 终局事实：flow int8 数值绿/行为翻车已回滚（资产保留：引擎 env 开关 + 因子四件套 + 烤制配方）；段间融合否决；qmd M=50 开销定罪；② 下轮入口：goal 菜单见 ②；物料 = /data/apxinf/pyo3_check/（flow 因子四件套 + prefix v2 生产因子）+ serve_i8（回滚位）+ probe_fi8/tl144_ab 实验桶；③ 纪律：**A/B 隔离根必须全谱系桶+supervisor**（单桶根过不了 L 漂移）、eval timeout ≥1800 且谱系桶先烤全、docker exec -d bash -c 内联形态进程随 ssh 断连无声死（用脚本文件形态）。丢弃：sshd 断连风暴应对过程、A/B 三连阻排查过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-08 补验闭合，见 summary/2026-09-30_flow-int8-segment-fusion-verdict.md）：① flow int8 数值全绿 + perf 75.6ms（-5.4）但 task0/1 连续打满 → **已回滚且复验闭合**（回滚位 task0 **SUCCESS 232 步** @ 2026-10-08——与 int8 位 520 打满构成完整 A/B，flow int8 行为退化定罪成立；服务器 10-04 断电重启 /data 全幸存，环境已恢复：容器重启 + mini_sup 回滚位运行中）；② 段间融合取证否决（sync 70.6 设备主导）；③ qmd 小 M 开销定罪（单算 probe GEB_QMD_M/K + 全图双取证）。两仓已推平（引擎 50024cb / 外层 e80ea93+）。

**下轮 goal 建议（抄一项即可）**：
1. **qmd x_scale 静态化探明**——0.53× 剩余 ~25ms 的唯一大杠杆（flow 设备 70.6ms 的 quant 流水若砍半 → flow ~50ms、sum ~200 达标）；IR 面 x_scale/x_offset 输入 310P 未探明，先单算 probe
2. **校准 v3（行为面优先）**——flow 侧因子改 per-step 感知（当前 10 步 amax 包络可能过平滑）+ prefix 多帧；验收 = actions <8% + 全量 10/10 + **flow int8 重启行为梯**
3. **task7 segfault 取证 + 扩预置桶**——py-spy 已装（apxinf_npu）；**本轮新增同款证据：task0 也出现客户端停摆（L 漂移 ensure 死锁）**——task7 疑云可用同工具链复现；149-156 桶并入生产管理（⚠ 共享 supervisor 僵尸 Sep 24 起**须用户决策重启**）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；int8 eval 用隔离根 serve_i8 + mini_sup_i8.sh（**当前为回滚位脚本**——再启 flow int8 须改回 GEB_FLOW_* env + int8 flow OM）；**A/B 隔离 = 等价生产根**（全谱系桶 + supervisor，单桶根被 L 漂移击穿）；eval timeout ≥1800。

## ④ 性能优化方向清单（2026-09-23 收集，按优先级）

现状锚点：**eval 口径 model_ms P50 = 325.3ms**（含 serve spool 轮询）＝376ms 基线的 0.87×；纯引擎稳态 310.3ms（0.82×）。逐段（serve 实测/调用）：**vision 65-68 / prefix 127-136 / flow 100-118ms**（flow = 10 步欧拉 ≈ 10ms/步 + 每步 x d2h + styles h2d；bench 口径 flow 段内 7.6ms/步）。理论裸算力下限（mm 已 ~20 TFLOPS≈峰值）：粗估 ~200-220ms，**剩余 ~90-120ms 是 host glue + 调度 + 段间往返**——大头不在算子。

| # | 方向 | 预期收益 | 机制 | 风险/前置 |
|---|---|---|---|---|
| **A** | ✅ **已落地（2026-09-23，GEB_SERVE_FAST）**：**段间设备直连**——prefix 36 路 kv 异步 d2d（零 host 中转）+ flow x 设备驻留（ob→binds[0] d2d，只末步下载）+ 去 per-step sync（10 次→1 次） | **实测 −45~62ms**（flow 117→80、prefix 130→105-115；task0 model_ms 316→254.3） | 同流顺序链保证计算序不变——bit 恒等 | 已过验证梯：冒烟 A/B bit 同（max_diff 四位全同）+ task0 success 1.0；全量回归待下一轮 |
| **B** | ✅ **已落地（同上，与 A 同一开关）**：**styles 设备驻留**——legacy 110 槽被 10 步复用须逐步重传（1100 次 h2d/调用）；改为每步独立视图拼 2.25MB master 一次上传 ⇒ **帧内零拷贝** | 并入上项（flow −35~37ms 的主体） | styles 跨帧恒定 + DeviceBuffer::view_of 非拥有视图 | 低（同 A） |
| **C** | ✅ **已落地（2026-09-23，e7e4cd1+787730a+engine.py inproc 分支）；python 宿主障碍已终结（2026-09-24 2dbffe9，GIL 劫持定罪 + allow_threads 修复，open 完整返回 + infer 与 spool 逐位同）**：**in-process serving**——执行器沉 crate 库面（GeServe 门面，spool/直调同源帧实现）+ PyO3 GeServeModel + npu_ge.py `APXINF_GE_TRANSPORT=inproc`（回落 spool 保底）。**剩余 = A3 eval 全链 inproc**（9.0.1 libs 供给 npu 容器 + torch_npu 剥离=前处理 CPU 化） | spool 15ms 在 inproc 生效环境免 | 引擎单实现三入口（example/PyO3/spool） | 已过：golden+bit 恒等双验、rust 容器 python 直调全通（修复后 RC=0 稳定）；task0/全量回归走 spool 保底无回归 |
| **D** | **✅ prefix int8 生产化收官（2026-09-28，见 summary/2026-09-28_prefix-int8-rebake.md）**：7 投影 ×18 层全换 QuantMatmulDequant（native smooth_scale = **1/s 乘法约定** + Const 烤入免 ND→NZ 税 + Gemma (1+g) 回图方案）；验收梯 4/4——对拍 npz 金标准 ALL_OK / golden L0 1.6-1.8%（18 层线性累积 L17 ~31-42%，actions 13.3%）/ task0 1.0 / **全量 10/10**；prefix 105→**87ms**，直调 sum **228ms = 0.607×**。三 bug 教训入 ② 纪律（fusion off 手烤必带等）。剩：校准 v2/per-group（误差杠杆）、flow 侧 int8（预算缺口主体）、bias int32 输入 310P 编译不可用留档 | 0.53× 预算剩 ~28ms 缺口（vision 60 + prefix 87 + flow 81 分解） | — | 已闭环 |
| **E** | **✅ C1 判决+修复完成（2026-09-24，子模块 ada176d）**：vision serve 65-68 "回归" = 纯 host glue（E2 设备 bench 56.26 ≈ C2 收官 55.86，设备侧洗清；真凶 = d2h 3.4 + f16 解码 5.1ms；111 输出 dataset 重建 0.3ms 洗清）→ 零拷贝字节视图 + `copy_h2d/d2h_async` 三段挂流单次 sync → **vision 59.4 / sum 246 = 0.654×**，bit 恒等 + task0 1.0 | **已兑现 −6.6ms** | `GEB_SERVE_TIMING=1` 分段计时常驻 | 剩余小项：~~prefix asm 2.5ms~~ 已修（token 查表缓存 1bf4201，asm→1.5ms）、flow enq 2.4ms；aclmdlExecuteAsync 实为 host 阻塞语义（bench 循环掩盖/serve 单发暴露） |
| **F** | **生产化配套**（非性能项）：~~动态 L 方案定形~~ ✓ 主体落地（2026-09-29：spatial 谱系 149-156 实证 + 隔离 mini-sup 基建；剩 149-156 桶并入生产 supervisor 管理 + task7 segfault 取证）；~~M2 eager 路径补 gate~~ ✓（e768fb2）；OM 懒加载/共享加载（3.7GB prefix 每桶 spawn ~1min）；NORM32 归档决策；**生产 supervisor 僵尸自 Sep 24 待用户决策重启** | 部署 TTFB/运维 | — | 低 |

**建议路线**（历史划线从略：A/B 设备直连、引擎接入、C1 vision glue、C2 int8 生产化、校准 v2、spatial 泛化、M2 gate 均已收官，数字见表内与战报）：**下一轮 = ② 的 goal 三选一**——① flow int8 / 段间融合（0.53× 缺口主体）→ ② 校准 v3 多帧 → ③ task7 segfault 取证 + 扩桶落地。A3 eval 全链 inproc 保持可选（abi 墙 + 宿主重写 vs ~5ms/帧收益，见 ④C）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-28_prefix-int8-rebake.txt（int8 生产化三 bug 取证 + 10/10 + v2 校准 + spatial 9/9 泛化 + M2 gate）
