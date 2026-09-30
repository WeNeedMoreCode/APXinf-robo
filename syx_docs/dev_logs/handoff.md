# Handoff（2026-09-29 int8 生产化 + spatial 泛化收官 → 下一轮压缩用）

## 状态一句话

**prefix int8 生产化全梯收官 + libero_spatial 泛化落地（2026-09-28~29，全数字见 summary/2026-09-28_prefix-int8-rebake.md）**：int8 验收梯 4/4（对拍 ALL_OK / golden L0 0.9%（v2 校准）/ task0 / **全量 10/10 @ 238.9ms**，f16 基线 256.3），prefix 105→87-88ms、直调 228ms = 0.607×；spatial **9/9 全 success**（泛化证据）+ 谱系 149-156 实证；M2 eager gate 闭环。历史里程碑（引擎库化/PyO3/inproc、C1 vision glue、C2 单算 probe、GIL 劫持终结）见 ②④ 与各战报。下轮 = ② 的 goal 菜单三选一。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-09-28_prefix-int8-rebake.md）——① 终局事实：prefix int8 生产化（全量 10/10 + 0.607× + v2 校准 L0 0.9%）；spatial 9/9 泛化 + 谱系 149-156；关键教训 = fusion off 手烤必带 / qmd smooth 乘法约定 1/s / **mini-sup 同根只许一份** / PYTHONPATH 须追加式；② 下轮入口：goal 菜单见 ②；物料 = /data/apxinf/pyo3_check/（**smooth_calib_v2_engine.safetensors 生产因子** / int8_weights_v1.npz 金标准 / 全套脚本）+ om_cache/tl{140-148,200}_i8 桶（v2）+ serve_i8 / serve_f16iso 隔离 eval 设施；③ 纪律：手烤 fusion off env、env 须追随 OM 的因子版本、隔离 eval 根、验证梯四步。丢弃：三只 bug 取证过程、spatial 四坑排查过程、桶重烤波折——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-09-29 凌晨终局，见 summary/2026-09-28_prefix-int8-rebake.md）：① int8 验收梯 4/4 + 终版全量 **10/10 @ 238.9**（f16 256.3）+ **校准 v2**（L0 减半 0.9%、actions 10.1%、桶全量 v2 化），prefix 105→**87-88ms**、直调 **228ms = 0.607×**；② **libero_spatial 泛化 9/9 全 success**（task7 客户端 segfault 缺测非失败；谱系 149-156 实证）；③ M2 gate 闭环（e768fb2）。两仓已推平。

**下轮 goal 建议（抄一项即可）**：
1. **flow int8 或段间融合**——0.53×（200ms）预算剩余缺口 = flow 81 + vision 60；物料同 prefix（校准 v2 生成器可同法扩 flow 侧 dump）
2. **校准 v3（多帧）**——v2 已把层间错配修掉（L0 0.9%），多帧激活（3-5 帧）压尾差；验收 = actions <8% + 全量 10/10
3. **spatial task7 segfault 取证 + 扩预置桶落地**——gdb/py-spy 附着复现（唯一缺测项）；149-156 桶并入生产 supervisor 管理（⚠ 两个生产 supervisor 僵尸 Sep 24 起**须用户决策重启**）

顺手项（不设 goal 也可）：PyO3 inproc int8 open 挂（AclError -2，非生产路径）；per-group 受算子契约约束已判不可行（留档）；**纪律：mini-sup 同根只许一份（多实例互杀，memory 已记）**。

**纪律**：手烤 OM 命令必须带 `env GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（**漏带 = legacy 算子图重载后静默全饱和**，2026-09-28 实锤；bash 不认带点变量名前缀赋值）；qmd smooth_scale = **1/s（乘法约定）** f16 [k]；int8 eval 用隔离根 `APXINF_GE_SERVE_ROOT=/data/apxinf/serve_i8` + mini_sup_i8.sh（勿动共享 supervisor）。验证梯照旧。

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
