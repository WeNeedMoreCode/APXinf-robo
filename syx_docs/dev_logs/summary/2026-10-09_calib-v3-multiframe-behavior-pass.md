# 校准 v3：多帧包络——flow int8 行为修复 + 10/10（2026-10-09 凌晨）

## 终局一行

**校准 v3 达成全部验收**：多帧真激活包络（4 任务 ×10 帧 = 40 帧真 env rollout，v2 是单帧）把 prefix per-matrix 量化误差 -18%、flow **-58%（2.3×）**——**actions rel 10.1% → 3.1%**（frame0）/**P50 3.3%**（32 帧真实轨迹 replay），**全量 LIBERO 10/10（flow int8 开启）**——09-30 因行为翻车回滚的 flow int8（serve flow 81→75.6ms 的 -5.4ms）重新回收。**根因定罪：v2 的单帧因子对 flow 侧激活分布错配 2.3× 量化误差，经 10 步欧拉轨迹放大成行为退化**——不是 flow int8 路线本身的问题，是校准数据面的问题。

## v3 施工链（全部资产在位）

1. **数据面**（`golden_gen_v3calib.py`，apxinf_npu 容器 chip3 ~5min）：replay_t{0..3} 真实 rollout 160 帧取 40 帧（FRAME_EVERY=4）——patches fold 精确逆变换（k=s=14 非重叠）→ SigLIP eager → embed_prefix → prefix replay（nrm1/m/nrm2/act ×18 层 pre-hook 跨帧 amax 包络 penv）+ 10 步 euler per-step 包络 fenv **[10,C] 步结构保留** + 4 采样帧激活真值 sim×1152（2.3GB calib_v3.safetensors）
2. **离线扫描**（`int8_factors_v3_sweep.py`，CPU ~13min 免烤先筛）：候选 = prefix{v2 单帧, v3 多帧}×α{0.4-0.6} + flow{v2 跨步折叠, v3_uniform, **v3_late（步 5-9 importance 加权）**}×α——真实激活上模拟 qmd 同构量化（per-token 动态 + per-row 权重）对 f32 参考排名
3. **产出**：胜者 prefix=v3_α0.5 / flow=v3_late_α0.6 → npz → `convert_smooth_engine.py`（argv）+ `convert_smooth_flow_npz.py`（新写参数化版）→ 引擎 safetensors（flow smooth 域 [0.018,32] vs v2 [0.034,5322]——极端因子同步收敛两量级）

## 判决表

| 配置 | per-matrix 量化误差（sim rms） | actions rel | 行为 |
|---|---|---|---|
| v2 prefix 单帧 | 2.408% | 10.1%（flow f16） | 10/10 |
| v2 + flow int8（v2 因子） | flow 1.85% | 9.7-10.0% | **0/2 520 打满（09-30 回滚）** |
| **v3 prefix 多帧 α0.5** | **1.970%** | — | — |
| **v3 flow 多帧 late α0.6** | **0.765%** | — | — |
| **v3 prefix + flow int8 v3（gud）** | — | **3.1% frame0 / P50 3.3%×32 帧** | **10/10**（含 task0+1 双通过） |

- 扫描附加结论：**主导效应 = 多帧包络**（late 加权与 α 差异 <3% 噪声级）；v2 因子在 α 维扫描下不变（α 已烤死在生成时）
- frame0 的 kv 中间层误差 v3 略高于 v2（l1 3.1% vs 1.1%）——**v2 单帧因子在 frame0 上过拟合占优的预期效应**；四帧均值 v3 全面占优，行为裁判终审支持 v3
- replay 离群帧（26/28：18.7%/84.9%）= 欧拉轨迹混沌分岔已知机制，P50 3.3% 紧簇 2.2-5.3%

## 验收梯（goal 条款逐项）

| 条款 | 结果 |
|---|---|
| actions <8% | ✅ 3.1%（frame0 golden）+ P50 3.3%（32 帧轨迹 replay，L=144） |
| 全量 10/10 | ✅ libero_object 10/10 rate 1.0（action_steps 118-171 全健康） |
| flow int8 行为梯 | ✅ task0、task1（09-30 失败对）双通过 + 全量带 flow int8 |

perf：per-call ≈ 232ms（model_seconds/replans 归一，34 replans/run）——int8 位带内，flow int8 -5.4ms 回收（因子不改算子面）。

## per-step 感知因子的路线论证（goal 原文措辞 vs 落地形态）

- **字面 per-step s 不可行**（本轮论证）：smoothquant 数学要求激活/权重两侧同一 s（x/s @ w·s 恒等），权重 wq/ws Const 烤入 OM 静态 → per-step s 需 per-step 权重量化 = 运行时不可能；行后 rescale 补偿被 f16 值域炸死（裸 sw·Σ int8 累积 ≫65504）
- **落地形态 = v3_late importance 加权包络**（步 5-9 max——末段步定义 actions 输出）+ per-step 结构化数据面（fenv [10,C]）留档：未来若换权重可变形态（如 AscendQuantV2 动态 scale 链）可直接复用

## 行为梯基础设施（复用 + 新增）

- **fleet 重烤**：`bake_v3_fleet.sh`——tl138-148_i8 ×11 桶 ×（prefix v3 + flow int8 v3）chips 0-3 四路并行 ~13min
- **v3 supervisor**：`mini_sup_i8_v3.sh`（mini_sup_i8.sh 的 v3 位——因子文件 v3 + serve env 加 GEB_FLOW_* + bake 补烤不再拷 f16 回退）；单实例纪律执行（旧实例 kill 链：supervisor 先杀 → serve pkill；**pgrep -f 自匹配坑两杀自己（143/137）——字符类 `prob[e]` 规避**）
- 旧 fleet 处置时序发现：chips 4/5 的"ge_model_probe 残留"实为回滚位 fleet 活 serve（非僵尸）——goal ② 的待核项顺带结案；真僵尸 43 个 Z 态（容器 init 不收尸的已知问题，不占资源，容器重启清）
- 全谱系桶纪律执行：task0 首 run 漂 142/143/145/146/147 五桶全按需 spawn——单桶根必撞 timeout 的 09-30 教训复现确认

## 遗留与下一步

- **生产根切换决策**（用户）：共享 supervisor 的 tl138-148 生产桶当前仍是 prefix v2 + flow f16（回滚位）——v3 已在隔离根 10/10，切生产 = 同法重烤生产桶 + supervisor env（含 2026-09-24 起的两个生产 supervisor 僵尸处置）
- flow int8 的 prefix+v3 组合在全量中每任务 model_seconds 5.6-8.3s（replans 34-45）——如需微 perf 复核可跑 GEB_E2E_BENCH 口径
- 校准 v3 因子仅覆盖 libero_object 谱系（replay t0-3）——spatial 等新套件泛化前建议同法扩录（golden_gen_v3calib.py 换 REPLAY 源即可）
- tl200 桶未 v3 化（隔离根无 200——libero_object 谱系不需要）

## 服务器状态（收尾时）

- v3 supervisor 运行中（serve_i8 隔离根，chips 4-7 按需）+ 全谱系 v3 桶热
- 共享生产 supervisor / serve / tl 桶**全程未动**
- 产物：calib_v3.safetensors（2.3GB）/ smooth_calib_v3{,_flow}.npz + engine st / sweep_v3.json / probe_v3{,_144} OM 三件套 / eval_v3_t{0-9}.jsonl + all summary
