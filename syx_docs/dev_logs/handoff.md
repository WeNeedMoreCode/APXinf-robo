# Handoff（2026-09-23 M3 收官 10/10 → 下一轮性能优化 / 压缩用）

## 状态一句话

**M3 达成——全量 LIBERO eval 10/10（success_rate 1.0，超越 torch 基线 9/10）+ 延迟 model_ms P50 325ms = 基线 376ms 的 0.87×**。闭环 0/10 真凶 = **ada-norm gate 通路整体缺失**（openpi `_gated_residual` 的 dense(cond) 第三段 gate 被引擎丢弃，36 处分支输出未门控）+ 残差基错用归一化值——修复在子模块 **ff42d2f**/外层 **e547717**，golden e2e step0_x1 13.8%→0.0%、actions 409%→0.9%，task0 132 步、全量 10 任务 122-163 步全成功。破案靠 replay 动作刑侦（std≈1.00 噪声分布推翻"norm 天花板"误诊）+ 源码对读；完整战报 summary/2026-09-23_ada-gate-missing-root-cause.md。serve 系统已停（芯片回基线；下次起 serve 前清 serve/tl*/ready+pid+shutdown，并核对桶内三件 OM 新鲜度——tl148 曾带 pre-gate 陈旧 flow 被误 spawn）。**M3 剩余为可选后置项**：ascend_executor M2 eager 路径补 gate、NORM32 系重估（n32 桶 flow 旧 + rms32 v2 l17 ssum 饱和 29.5%）、生产化（动态 L 分桶/引擎注册链接入 apxinf-robo 主路径）。**下一轮 = 性能优化（目标 ≈0.70×/255-275ms，方向清单与优先级见 ④：A 段间设备直连 + B styles 设备化为主攻，C in-process serving 随生产化，D int8 单算 probe 定生死，E msprof 数据驱动顺路）**。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**M3 终局数字**（eval_gateall：10/10、122-163 步、model_ms P50 325.3ms=0.87×、task0 单测 132 步 eval_gatet0b；golden：step0_x1 0.0%/actions 0.9%）；**gate 修复形态**（e2e_style_pair 三元组、每层 l{i}_agate/mgate [1,AW] Data（qkv3 位 16/17）、gatew=TileD dim0+Mul 两处、残差基 xstream 双轨、四处绑定 6-stride b+16/b+17、aops::gate_mul_fp16；torch 语义 = dense(cond) chunk3 + _gated_residual residual+branch·gate 两处 + suffix 全双向）；**刑侦方法论**（动作每维 std≈1.00=噪声分布 ⇒ flow 未收敛数据流形；镜像参考系同 bug 时组件 parity 全绿是假阴性；多源合流的"原理性"结论前先做分布刑侦）；**serve 运维坑**（stale ready/pid 让 client 撞死桶；清桶须连 OM 三件套新鲜度一起查；eval 的 L 漂移 lazy bake 每新桶 ~4-5min 串行）。丢弃：supervisor 僵尸清理细节、预烤引号翻车过程、中间 golden 数字。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU（**M3 已收官：10/10 + 0.87×；本轮 = 性能优化，方向清单见 ④**）。第一动作：**msprof 三段基线采集**（ascend-msprof skill；GEB_E2E_BENCH=10 + tl144 桶，缩规模纪律 GEB_ROUNDS/GEB_PER）→ 按④优先级 A（段间设备直连）开工。验证梯（性能改动防行为回归，现在是关键——10/10 是回归基线）：golden step0_x1/actions（4min，须 ≤0.1%/≤2%）→ replay dump+forensics corr（5min，须 >0.9）→ task0（~15min）→ 全量（25-40min，只在大改后跑）。⚠ 复现 eval 前置：起 serve 前清 serve/tl*/ready+pid+shutdown + 核对桶内三件 OM 新鲜度；⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/kill 用 pgrep+方括号/长命令带 date/验证档位梯/服务器脚本"本地写 → cat > 远端 → nohup 文件"三步）。

## ④ 性能优化方向清单（2026-09-23 收集，按优先级）

现状锚点：**eval 口径 model_ms P50 = 325.3ms**（含 serve spool 轮询）＝376ms 基线的 0.87×；纯引擎稳态 310.3ms（0.82×）。逐段（serve 实测/调用）：**vision 65-68 / prefix 127-136 / flow 100-118ms**（flow = 10 步欧拉 ≈ 10ms/步 + 每步 x d2h + styles h2d；bench 口径 flow 段内 7.6ms/步）。理论裸算力下限（mm 已 ~20 TFLOPS≈峰值）：粗估 ~200-220ms，**剩余 ~90-120ms 是 host glue + 调度 + 段间往返**——大头不在算子。

| # | 方向 | 预期收益 | 机制 | 风险/前置 |
|---|---|---|---|---|
| **A** | **段间设备直连**：prefix 36 路 kv（13MB/调用 d2h+h2d host 中转）→ 同进程 d2d/设备 buffer 复用；flow 10 步 x 逐步 d2h→h2d 改设备驻留（只末步下载）；vision aux 输出免下载 | **−25~45ms** | E2eStage 三段本就同进程（serve 单桶内）——aclmdlExecute 的输出 buffer 直接绑为下一段输入，零 host 往返 | 低-中：需改 E2eStage 绑定生命周期（输出 buffer 被 GE 复用的坑 #33 类，须按值快照/ownership 转移） |
| **B** | **styles 批量化/设备化**：10 步 styles（37×2 向量×10 步 = 740 次 h2d/调用）→ 一次性上传 10 步全量或设备端预计算 | **−10~15ms** | styles 跨调用不变（time 调度固定）——进程内常驻；图侧把 per-step 换绑改成一次大 buffer + 步内偏移读取（Data 不变则免绑） | 低：host 侧预计算已缓存（2.06s/进程），只差传输组织 |
| **C** | **in-process serving**（去 spool 轮询）：model_ms 325 vs bench 310 的 15ms 差 = 文件轮询 + 进程边界 | **−10~15ms** | 引擎注册链接入 apxinf-robo 主路径（Python 端直接调 E2eStage），同时是生产化必经 | 中：PyO3 绑定 + apxinf_robo engine 缝（阶段 1 已有 npu-torch 同构先例）；多桶 L 分派逻辑要在进程内重建 |
| **D** | **int8/w8a8 权重量化**（prefix/vision 大头）：310P int8 cube ~100 TOPS vs fp16 16 TFLOPS（6× 算力比）；prefix 116ms 里 MatMul 主导 | prefix **或 −30~60%** | CUDA 侧原仓有 int8/fp8 executor 先例；昇腾侧 MatMulV2 int8 支持待探（opp 注册表 + 单算 probe） | 高：数值校准（Gemma outlier）+ 全链行为复验；先做单算 probe 定可行性再立项 |
| **E** | **vision/prefix 图组织复查**（msprof 数据驱动）：vision 65ms vs 早期 55.9ms 的回归源；LN aux 输出、TransData 残余、attention 形态（manual vs PFA）复选 | 未知（5-15ms 级） | gate 修复后数值可信，可放心换算子形态对拍；DUMP_GE_GRAPH 查融合机会 | 低：纯实验性，逐项 golden 对拍守护 |
| **F** | **生产化配套**（非性能项）：动态 L 方案定形（预置桶集 vs padding+mask vs input_shape_range）、OM 懒加载/共享加载（3.7GB prefix 每桶 spawn ~1min）、M2 eager 路径补 gate、NORM32 归档决策 | 部署 TTFB/运维 | — | 低 |

**建议路线**：A+B 先做（同属"消灭 host 往返"，合计预期 −35~60ms → **~255-275ms ≈ 0.70×**，改动集中在 probe 的 E2eStage，风险低且有 10/10 回归网）；C 随生产化排期；D 立单算 probe（1-2 天定生死）；E 用每次 msprof 的数据顺路做。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_ada-gate-root-cause.md（M3 收官：ada-gate 缺失真凶 + 动作刑侦翻案 + 全量 eval 10/10 + 0.87×）
