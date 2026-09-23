# Handoff（2026-09-23 M3 收官 10/10 → 下一轮性能优化 / 压缩用）

## 状态一句话

**引擎接入主线三步落地（2026-09-23，见 summary/2026-09-23_engine-integration.md）：① 执行器库化——ge_model_probe 6206 行沉到 crate 库面 `src/pi05/ascend_ge.rs` + `GeServe` 进程内门面（open/infer，serve_loop 与直调共用帧实现），验证梯全过（golden step0_x1 0.0%/actions 0.9% 与基线逐字同、新旧二进制冒烟 bit 恒等 0.0244/1.0% 四位全同）——子模块 e7e4cd1；② PyO3 `GeServeModel`（apxinf-py --features ascend，接口与 spool 协议逐位对齐，rust 容器 python 直调三段全通；**已知障碍 = python 宿主内 GE 库在 open 尾声杀进程**，无信号无 Traceback + TBE 子进程 8 连报错，非确定点位，纯 Rust 宿主同代码稳定——疑 GE 的 TBE 子进程管理与 python 宿主相克）——787730a；③ engine.py npu-ge 加 `APXINF_GE_TRANSPORT=inproc` 分支（_InprocClient 直调 PyO3，失败自动回落 spool 桶；npu 容器 torch_npu 8.5.1 与 9.0.1 同进程互斥，spool 仍为生产传输）。**全量 fast 回归终数锁定：10/10 + per-call model_ms P50 256.3ms = 0.682×**（跨任务 254.5-260.5 极稳，④A+B 收口）。此前战绩：M3 全量 10/10 + 0.87×（ada-gate 缺失真凶战报 2026-09-23_ada-gate-missing-root-cause.md）、GEB_SERVE_FAST 254.3ms task0 口径（serve-fast-device-direct.md）。**下一轮候选：python 宿主 GE 存活障碍（TBE 禁用选项/华为渠道）→ eval 全链 inproc（9.0.1 libs 供给 + torch_npu 剥离）→ ④ 动态 L 定形；性能余项顺路（E msprof vision 65ms、D int8 probe）。**

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**M3 终局数字**（eval_gateall：10/10、122-163 步、model_ms P50 325.3ms=0.87×、task0 单测 132 步 eval_gatet0b；golden：step0_x1 0.0%/actions 0.9%）；**gate 修复形态**（e2e_style_pair 三元组、每层 l{i}_agate/mgate [1,AW] Data（qkv3 位 16/17）、gatew=TileD dim0+Mul 两处、残差基 xstream 双轨、四处绑定 6-stride b+16/b+17、aops::gate_mul_fp16；torch 语义 = dense(cond) chunk3 + _gated_residual residual+branch·gate 两处 + suffix 全双向）；**刑侦方法论**（动作每维 std≈1.00=噪声分布 ⇒ flow 未收敛数据流形；镜像参考系同 bug 时组件 parity 全绿是假阴性；多源合流的"原理性"结论前先做分布刑侦）；**serve 运维坑**（stale ready/pid 让 client 撞死桶；清桶须连 OM 三件套新鲜度一起查；eval 的 L 漂移 lazy bake 每新桶 ~4-5min 串行）。丢弃：supervisor 僵尸清理细节、预烤引号翻车过程、中间 golden 数字。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU（**引擎接入三步落地：① crate 库面 GeServe（e7e4cd1，golden/冒烟 bit 恒等双验）② PyO3 GeServeModel（787730a，rust 容器 python 三段全通；python 宿主内 GE 杀进程 = 已知障碍）③ engine.py inproc 传输分支（回落 spool 保底）；全量 fast 回归 10/10 + 256.3ms = 0.682× 收口**——见 summary/2026-09-23_engine-integration.md）。下一轮候选按优先级：**A. python 宿主 GE 存活障碍**（现状：open 尾声（fmech 构装后）GE 杀整进程，无信号无 Traceback，TBE 子进程 8 连 "main process disappeared" 伴随，死亡点位非确定；strace 信号级已验证非 SIGSEGV/SIGABRT；候选：GE init 选项禁 TBE / ge.exec_pythonPath 指向受控 python / 华为渠道）→ 通了则 eval 全链 inproc（还需 9.0.1 libs 拷到 /data 供 npu 容器 + torch_npu 剥离=前处理 CPU 化，**9.0.1 toolkit 在 rust 容器镜像层非挂载**）；B. ④ 动态 L 定形（预置桶集 tl138-148+tl200 已备，padding+mask/shape_range 后置）；C. 性能余项（E msprof vision 65ms 回归源、D int8 单算 probe）。⚠ 库面关键纪律：**GeServe::open 的 env 钉死不含 GEB_DEPTH**（分段默认 vision=27/prefix=18/flow=18，钉 18 砍 vision 层 → n_in 187≠277）；⚠ 新坑（engine-integration 战报运维节全列）：set -u+source rust_env 炸 / bash export 不吃带点名（须 env 前缀）/ ready mtime touch 须在客户端启动后 / cdylib 要 cp 去 lib 前缀 / docker exec -d stdout 丢弃须脚本自落盘 / **eval 期间并行编译用 CARGO_TARGET_DIR=/data/apxinf/target_libcheck 不碰生产二进制**。验证梯照旧（golden ≤0.1%/≤2% → 冒烟 A/B bit 同 → task0 → 全量大改后）。

## ④ 性能优化方向清单（2026-09-23 收集，按优先级）

现状锚点：**eval 口径 model_ms P50 = 325.3ms**（含 serve spool 轮询）＝376ms 基线的 0.87×；纯引擎稳态 310.3ms（0.82×）。逐段（serve 实测/调用）：**vision 65-68 / prefix 127-136 / flow 100-118ms**（flow = 10 步欧拉 ≈ 10ms/步 + 每步 x d2h + styles h2d；bench 口径 flow 段内 7.6ms/步）。理论裸算力下限（mm 已 ~20 TFLOPS≈峰值）：粗估 ~200-220ms，**剩余 ~90-120ms 是 host glue + 调度 + 段间往返**——大头不在算子。

| # | 方向 | 预期收益 | 机制 | 风险/前置 |
|---|---|---|---|---|
| **A** | ✅ **已落地（2026-09-23，GEB_SERVE_FAST）**：**段间设备直连**——prefix 36 路 kv 异步 d2d（零 host 中转）+ flow x 设备驻留（ob→binds[0] d2d，只末步下载）+ 去 per-step sync（10 次→1 次） | **实测 −45~62ms**（flow 117→80、prefix 130→105-115；task0 model_ms 316→254.3） | 同流顺序链保证计算序不变——bit 恒等 | 已过验证梯：冒烟 A/B bit 同（max_diff 四位全同）+ task0 success 1.0；全量回归待下一轮 |
| **B** | ✅ **已落地（同上，与 A 同一开关）**：**styles 设备驻留**——legacy 110 槽被 10 步复用须逐步重传（1100 次 h2d/调用）；改为每步独立视图拼 2.25MB master 一次上传 ⇒ **帧内零拷贝** | 并入上项（flow −35~37ms 的主体） | styles 跨帧恒定 + DeviceBuffer::view_of 非拥有视图 | 低（同 A） |
| **C** | ✅ **已落地（2026-09-23，e7e4cd1+787730a+engine.py inproc 分支）**：**in-process serving**——执行器沉 crate 库面（GeServe 门面，spool/直调同源帧实现）+ PyO3 GeServeModel + npu_ge.py `APXINF_GE_TRANSPORT=inproc`（回落 spool 保底） | spool 15ms 在 inproc 生效环境免（eval 全链 inproc 待 python 宿主 GE 障碍解除） | 引擎单实现三入口（example/PyO3/spool）；python 宿主 GE 存活障碍见 summary/2026-09-23_engine-integration.md | 已过：golden+bit 恒等双验、rust 容器 python 三段直调全通；task0/全量回归走 spool 保底无回归 |
| **D** | **int8/w8a8 权重量化**（prefix/vision 大头）：310P int8 cube ~100 TOPS vs fp16 16 TFLOPS（6× 算力比）；prefix 116ms 里 MatMul 主导 | prefix **或 −30~60%** | CUDA 侧原仓有 int8/fp8 executor 先例；昇腾侧 MatMulV2 int8 支持待探（opp 注册表 + 单算 probe） | 高：数值校准（Gemma outlier）+ 全链行为复验；先做单算 probe 定可行性再立项 |
| **E** | **vision/prefix 图组织复查**（msprof 数据驱动）：vision 65ms vs 早期 55.9ms 的回归源；LN aux 输出、TransData 残余、attention 形态（manual vs PFA）复选 | 未知（5-15ms 级） | gate 修复后数值可信，可放心换算子形态对拍；DUMP_GE_GRAPH 查融合机会 | 低：纯实验性，逐项 golden 对拍守护 |
| **F** | **生产化配套**（非性能项）：动态 L 方案定形（预置桶集 vs padding+mask vs input_shape_range）、OM 懒加载/共享加载（3.7GB prefix 每桶 spawn ~1min）、M2 eager 路径补 gate、NORM32 归档决策 | 部署 TTFB/运维 | — | 低 |

**建议路线**：~~A+B 先做~~ **已完成（全量口径 256.3ms = 0.682×，10/10）**。~~主线 = 引擎接入~~ **三步已落地（①库化 e7e4cd1 ②PyO3 787730a ③engine.py inproc 分支）**。下一轮优先级：python 宿主 GE 存活障碍（TBE 禁用选项/华为渠道）→ eval 全链 inproc（9.0.1 libs 供给 + torch_npu 剥离）→ ④ 动态 L 定形；D int8 probe / E msprof 顺路。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_ada-gate-root-cause.md（M3 收官：ada-gate 缺失真凶 + 动作刑侦翻案 + 全量 eval 10/10 + 0.87×）
