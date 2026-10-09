# 动态分档调研定案 + goal 新任务集泛化 + OM 冷启动分解（2026-10-10 轮）

## 终局一行（待 ③ 收口后补全）

① **动态 L 分桶生产化路线定案 = GE 动态分档（dynamic gear），310P 实证全绿**（spike：编译过 + 权重零重复（双档 OM 仅 +42KB）+ 档位真分发 + 数值 0.23% + 性能零税）——单 OM 替代 20 桶家族、单 serve 服务全谱系、22 档 ≪ 100 上限；② **OM 冷启动 125.6s 分解定案**（ckpt 全量解析 63.7s（e2e serve 实际只需嵌入表+time_mlp 子集）+ vision 11.9s + prefix 41.2s（含 2.1GB 嵌入查表）+ flow 8.8s）——lazy 施工与 gear 生产化同轮做（当前架构上做 lazy = 给将被替换的路径镀金）；③ goal 泛化轮（录制 → golden → sweep transfer 判定 → eval，数字见下）。

## goal ① 动态 L 分桶生产化——调研定案

**需求数据（谱系实测）**：object 138-148 + 157；spatial 非截断支 149-156 + 截断支 200；goal 录制任务 0-2 全 200（截断支）。当前预置 138-157+200 已覆盖历史全部观测，lazy-bake 兜底新 L（冷烤 ~6min = 2×63.7s ckpt + 编译 + spawn）。

**GE 动态分档机制（docs/zh/design/features/dynamic_gear.md）**：编译期枚举档位集（≤100 档），每档独立**静态优化子图**（保住静态 tiling = 性能零税来源），运行时 `aclmdlSetInputDynamicDims` 选档执行；根图 Const 权重单份共享（`CreateRootGraph` 拷 OpDesc 接 Case 参数 + `ChangeConstToData` 把分支 Const 变异为 Data 再克隆——N 档零权重重复）；hybrid 模式（`ge.dynamicNodeType=1`+`ge.compileHybridMode=1`）可同时编档位图+动态 shape 图，档外输入自动降级。

**spike 实测（`probe_dyn/dyn_gear_probe.c`，310P3，MatMulV2 transpose_x2 + 32MB Const，档 650/712 = L138/L200 的 P 值）**：

| 生死题 | 结果 |
|---|---|
| Q1 ge_builder/aclgrphBuildModel 路径编译 | ✅（`input_shape="x:-1,2048"` + `ge.dynamicDims="650;712"`，选项键名混用：短名 input_shape + 前缀名 ge.dynamicDims） |
| Q2 权重是否按档重复 | ✅ **零重复**：gear2 OM 33,618,683B vs static650 33,576,132B，delta 仅 42,551B（32MB Const 单份） |
| Q3 双档执行 + 数值 + 分发 | ✅ `SetInputDynamicDims` rc=0、两档 rel 0.2278%（f16 累加正常量级）、`GetCurOutputDims` 各返 650/712（档位真分发） |
| 性能 | ✅ 零税：dyn 6.04ms ≈ static 5.57ms（差值在 SetDims+sync 口径内） |

**运行侧坑（已回填 skill ge-offline-om）**：动态 OM 输入数 +1（`ascend_mbatch_shape_data` gear-info 输入，4 字节）——dataset 必须覆盖全部输入 buffer，缺了报 500002；根 Data buffer = 最大档尺寸；小档只填前 p 行。

**生产化施工面（下轮）**：prefix/flow 图 Data 加 -1 维 + ge.dynamicDims 选项（档集 = 观测谱系 138-157+200，约 22 档）→ GeServe run 路径加 SetInputDynamicDims + per-gear 输出尺寸 → 单 serve 多 L 派发（spool 寻址改造：谱系桶命名或单桶多目录监听）→ supervisor 每芯一只常驻 serve（不再按 L spawn）→ 冷 spawn/冷烤问题整体消解。vision 段 L 无关保持静态。

## goal ② OM 懒加载 + 引擎注册链——分解定案

**冷 spawn 125.6s 分解（tl139 实测，GEB_SERVE_TIMING）**：
| 段 | 耗时 | 构成 |
|---|---|---|
| GEB_CKPT 解析 | 63.7s | 全量 7GB safetensors host 解析；**e2e serve 实际只需嵌入表（2.1GB 查表源）+ time_mlp/style 投影（小）**——~90% 白 parse（权重已烤 OM） |
| vision 段 | 11.9s | 834MB OM 加载 + 首跑 |
| prefix 段 | 41.2s | 1883MB OM 加载 + 2.1GB 嵌入查表构建 |
| flow 段 | 8.8s | 402MB OM 加载 + styles 预计算 + 10 步 |

**判决**：lazy 优化（ckpt 选择性读取 −54s + 三段 OM 并行加载 −20s → ~50s 可达）**与 gear 生产化同轮施工**——单 serve 常驻后冷 spawn 从"每 L 一次"变"每芯一次"（4 芯一次性 8.5min），当前每 L 架构上做 lazy 是给将被替换的路径镀金。"引擎注册链入主路径"（eval 全链 inproc）前置已就绪（npu_ge.py `_TRANSPORT=inproc` 分支 + GIL 修复），剩余 = apxinf_npu 容器供给 9.0.1 libs（/data 共享 + LD_LIBRARY_PATH）且 eval 客户端不 import torch_npu——spool 轮询 ~15ms/call 可再省。

## goal ③ libero_goal 新任务集泛化——数值面闭环，行为面 eval 中

**管线全参数化一条龙实跑**（record_rollout 换 SUITE → golden → sweep v3o 对照 → 免烤直评）：

- 录制：replay_g{0..3}（torch golden 40 帧/任务，chip1，~10min/任务）——**goal 谱系全 200 截断**（4 任务全 40/40 帧 L=200）；g2 首编译病理性 ~40min 后自愈（torchair fx→GE 转换偶发慢，非死锁——py-spy 确认推进后放行）
- golden：calib_v3_goal.safetensors 2.3GB（4 任务帧 × SigLIP eager + per-step 包络，~4.7min chip3）
- **sweep transfer 判定（第三谱系）**：

| 候选（goal 真激活 sim） | prefix rms | flow late2x |
|---|---|---|
| v2 单帧基线 | 2.278% | 1.874% |
| **v3o（object 因子直接用）** | **2.089%** | **0.879%** |
| v3 goal 专属拟合胜者 | 1.960%（α0.5） | 0.769%（late α0.6） |

**transfer 成立**：v3o 距 goal 专属拟合 prefix 6.6% / flow 14.2% 相对差（flow 已吃到 v2→v3 修复的 2.13× 主体）；**最优超参第三次跨谱系复现**（prefix α0.5 / flow late α0.6，object/spatial/goal 三连）→ **单一因子集三谱系覆盖，免重烤**。产物留档：calib_v3_goal.safetensors / smooth_calib_v3_goal{,_flow}.npz / sweep_v3_goal.json。
- 行为面 eval（生产根 v3 位，timeout 1800，逐任务独立进程）：跑中，结果回填下节。

## 运维事件：119 上行断流（新坑，已入 memory）

同日 ssh exec 正常但**上行数据 >~700B（约一个 TCP 段）即 RST**（下行不受限；600B stdin OK / 1500B RST；scp 双协议全死）。workaround = gzip + 480B 分块 base64 append + md5 对验（11KB 源码 ~15s 传完）。本轮全部上传走此通路。
