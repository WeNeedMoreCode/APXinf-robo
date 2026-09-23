# Handoff（2026-09-23 M3 收官 10/10 → 下一轮性能优化 / 压缩用）

## 状态一句话

**M3 达成——全量 LIBERO eval 10/10（success_rate 1.0，超越 torch 基线 9/10）+ 延迟 model_ms P50 325ms = 基线 376ms 的 0.87×**。闭环 0/10 真凶 = **ada-norm gate 通路整体缺失**（openpi `_gated_residual` 的 dense(cond) 第三段 gate 被引擎丢弃，36 处分支输出未门控）+ 残差基错用归一化值——修复在子模块 **ff42d2f**/外层 **e547717**，golden e2e step0_x1 13.8%→0.0%、actions 409%→0.9%，task0 132 步、全量 10 任务 122-163 步全成功。破案靠 replay 动作刑侦（std≈1.00 噪声分布推翻"norm 天花板"误诊）+ 源码对读；完整战报 summary/2026-09-23_ada-gate-missing-root-cause.md。serve 系统已停（芯片回基线；下次起 serve 前清 serve/tl*/ready+pid+shutdown，并核对桶内三件 OM 新鲜度——tl148 曾带 pre-gate 陈旧 flow 被误 spawn）。**M3 剩余为可选后置项**：ascend_executor M2 eager 路径补 gate、NORM32 系重估（n32 桶 flow 旧 + rms32 v2 l17 ssum 饱和 29.5%）、生产化（动态 L 分桶/引擎注册链接入 apxinf-robo 主路径）。**性能轮第一点已落地（2026-09-23，GEB_SERVE_FAST = ④A 段间设备直连 + ④B styles 设备驻留）：task0 model_ms 316.1→254.3ms = 376 基线 0.68×（破 0.70× 线），bit 级恒等（冒烟 max_diff 四位小数全同）+ task0 success 1.0——见 summary/2026-09-23_serve-fast-device-direct.md。下一轮 = 全量 10 任务回归（fast 版）→ C in-process serving → E msprof（vision 65ms 回归源）→ D int8 单算 probe 定生死。**

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**M3 终局数字**（eval_gateall：10/10、122-163 步、model_ms P50 325.3ms=0.87×、task0 单测 132 步 eval_gatet0b；golden：step0_x1 0.0%/actions 0.9%）；**gate 修复形态**（e2e_style_pair 三元组、每层 l{i}_agate/mgate [1,AW] Data（qkv3 位 16/17）、gatew=TileD dim0+Mul 两处、残差基 xstream 双轨、四处绑定 6-stride b+16/b+17、aops::gate_mul_fp16；torch 语义 = dense(cond) chunk3 + _gated_residual residual+branch·gate 两处 + suffix 全双向）；**刑侦方法论**（动作每维 std≈1.00=噪声分布 ⇒ flow 未收敛数据流形；镜像参考系同 bug 时组件 parity 全绿是假阴性；多源合流的"原理性"结论前先做分布刑侦）；**serve 运维坑**（stale ready/pid 让 client 撞死桶；清桶须连 OM 三件套新鲜度一起查；eval 的 L 漂移 lazy bake 每新桶 ~4-5min 串行）。丢弃：supervisor 僵尸清理细节、预烤引号翻车过程、中间 golden 数字。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU（**M3 收官 10/10 + 0.87× → 性能第一点 GEB_SERVE_FAST 落地：task0 254.3ms = 0.68×，bit 恒等**）。**下一轮主线已改（2026-09-23 与用户对齐）：引擎正式接入 apxinf-robo 主路径**（此前一直是 ge_model_probe 探针 + spool 文件轮询的脚手架形态——行为/性能已达标，接入才算"适配完成"）。施工四步：① 执行器库化（三段执行器 + styles 预计算 + E2eStage 含 GEB_SERVE_FAST 从 example 沉到 crate 库面）② PyO3 最小接口（apxinf-py `--features ascend` 构建先例；暴露 load + infer(obs)→actions）③ engine.py 路由 `engine="npu-ge"`（阶段 1 npu-torch 同构先例）④ 动态 L 定形（预置桶集先行，padding+mask/shape_range 后置）——做完 ①-③ 即进程内直调（= ④C in-process，spool 15ms 顺便消失），全量 10/10 回归收口。**接入前先跑全量回归（fast 版）锁 0.68× 终数**：fast supervisor（start_supervisor_fast.sh）→ `run_ge_eval.sh all gatefastall`（~40min）。性能余项降为顺路：E msprof vision 65ms 回归源、D int8 单算 probe。验证梯（10/10 是回归基线）：golden step0_x1/actions（4min，≤0.1%/≤2%）→ smoke A/B bit 同一性 → task0（~15min）→ 全量（25-40min，只在大改后跑）。⚠ 复现 eval 前置：起 serve 前清 serve/tl*/ready+pid+shutdown + 核对桶内三件 OM 新鲜度；**直起桶后起冒烟客户端须 touch ready（mtime 判定陷阱）**；eval summary 开跑即写骨架（null ≠ 崩溃）；⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/kill 用 pgrep+方括号+stat 判 Z/长命令带 date/验证档位梯/服务器脚本"本地写 → scp → bash 文件"三步——docker exec 嵌套引号必翻车）。

## ④ 性能优化方向清单（2026-09-23 收集，按优先级）

现状锚点：**eval 口径 model_ms P50 = 325.3ms**（含 serve spool 轮询）＝376ms 基线的 0.87×；纯引擎稳态 310.3ms（0.82×）。逐段（serve 实测/调用）：**vision 65-68 / prefix 127-136 / flow 100-118ms**（flow = 10 步欧拉 ≈ 10ms/步 + 每步 x d2h + styles h2d；bench 口径 flow 段内 7.6ms/步）。理论裸算力下限（mm 已 ~20 TFLOPS≈峰值）：粗估 ~200-220ms，**剩余 ~90-120ms 是 host glue + 调度 + 段间往返**——大头不在算子。

| # | 方向 | 预期收益 | 机制 | 风险/前置 |
|---|---|---|---|---|
| **A** | ✅ **已落地（2026-09-23，GEB_SERVE_FAST）**：**段间设备直连**——prefix 36 路 kv 异步 d2d（零 host 中转）+ flow x 设备驻留（ob→binds[0] d2d，只末步下载）+ 去 per-step sync（10 次→1 次） | **实测 −45~62ms**（flow 117→80、prefix 130→105-115；task0 model_ms 316→254.3） | 同流顺序链保证计算序不变——bit 恒等 | 已过验证梯：冒烟 A/B bit 同（max_diff 四位全同）+ task0 success 1.0；全量回归待下一轮 |
| **B** | ✅ **已落地（同上，与 A 同一开关）**：**styles 设备驻留**——legacy 110 槽被 10 步复用须逐步重传（1100 次 h2d/调用）；改为每步独立视图拼 2.25MB master 一次上传 ⇒ **帧内零拷贝** | 并入上项（flow −35~37ms 的主体） | styles 跨帧恒定 + DeviceBuffer::view_of 非拥有视图 | 低（同 A） |
| **C** | **in-process serving**（去 spool 轮询）：model_ms 325 vs bench 310 的 15ms 差 = 文件轮询 + 进程边界 | **−10~15ms** | 引擎注册链接入 apxinf-robo 主路径（Python 端直接调 E2eStage），同时是生产化必经 | 中：PyO3 绑定 + apxinf_robo engine 缝（阶段 1 已有 npu-torch 同构先例）；多桶 L 分派逻辑要在进程内重建 |
| **D** | **int8/w8a8 权重量化**（prefix/vision 大头）：310P int8 cube ~100 TOPS vs fp16 16 TFLOPS（6× 算力比）；prefix 116ms 里 MatMul 主导 | prefix **或 −30~60%** | CUDA 侧原仓有 int8/fp8 executor 先例；昇腾侧 MatMulV2 int8 支持待探（opp 注册表 + 单算 probe） | 高：数值校准（Gemma outlier）+ 全链行为复验；先做单算 probe 定可行性再立项 |
| **E** | **vision/prefix 图组织复查**（msprof 数据驱动）：vision 65ms vs 早期 55.9ms 的回归源；LN aux 输出、TransData 残余、attention 形态（manual vs PFA）复选 | 未知（5-15ms 级） | gate 修复后数值可信，可放心换算子形态对拍；DUMP_GE_GRAPH 查融合机会 | 低：纯实验性，逐项 golden 对拍守护 |
| **F** | **生产化配套**（非性能项）：动态 L 方案定形（预置桶集 vs padding+mask vs input_shape_range）、OM 懒加载/共享加载（3.7GB prefix 每桶 spawn ~1min）、M2 eager 路径补 gate、NORM32 归档决策 | 部署 TTFB/运维 | — | 低 |

**建议路线**：~~A+B 先做~~ **已完成（254.3ms task0 口径 = 0.68×，超预期）**。**主线改为引擎接入（2026-09-23 与用户对齐）= ④C in-process + ④F 生产化的合并施工**：执行器库化 → PyO3 → engine.py 路由 → 动态 L，全量 10/10 回归收口；D int8 probe / E msprof 降为顺路项。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_ada-gate-root-cause.md（M3 收官：ada-gate 缺失真凶 + 动作刑侦翻案 + 全量 eval 10/10 + 0.87×）
