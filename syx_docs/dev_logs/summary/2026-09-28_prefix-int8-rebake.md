# C2 生产化：prefix OM int8 重烤全梯通过（2026-09-28）

## 终局一行

prefix 7 投影（q/k/v/o/gate/up/down × 18 层）全部换 `QuantMatmulDequant`（smooth W8A8 + 算子原生 smooth_scale），**验收梯 4/4 通过**：量化对拍金标准 ALL_OK → e2e golden parity（L0 单层 1.6-1.8%，actions 13.3%）→ task0 success 1.0 → **全量 10/10**。**终版（Const + bias 砍除）独立全量复验 10/10 @ model_ms P50 238.9**（f16 同口径 256.3 = **-17.4ms**），直调 sum **228.5ms = 0.607×**；prefix **105→87ms**。env 开关 `GEB_PREFIX_INT8=1`，f16 回退 = 不设。**M2 eager 补 gate 同日闭环**（残差裸加 → `branch·gate` 两处，与 GE gatew 同源；bench finite 1600/1600）。

## 实现面（子模块 ascend_ge.rs）

- `Seg::qmd`（算子 helper）+ `reg_i8`（量化注册）+ `mm_or_qmd`（int8/f16 统一投影）+ `quant_w8`（W8 行量化，分块转置 + ties-even round，与 int8_bake_weights.py 逐位同数学）
- 算子契约（全部 probe 实证）：x f16 / quantized_weight int8 ND [n,k]（transpose_weight=true）/ weight_scale f32 [n] / **smooth_scale f16 [k] = 1/s（乘法约定！NSM=3 定案，s 直入 = x·s @ w·s = s² 放大）** / x_quant_mode="pertoken"；attr 必须显式设
- **bias 输入（int32）编译被拒**（aclgrphBuildModel rc=-7）——legacy 算子 bias 分支不可用；改为 int8 路径直接砍 bias op（Gemma 投影 bias≡0，int8 已 assert 真权重，语义零损失）
- `GEB_INT8_PROJS` 子集分阶段开关 / `GEB_INT8_DUMP` 对拍落盘 / `GEB_INT8_NATIVE=0` 回退 TileD+Mul 行预乘 / `GEB_INT8_WCONST`（默认随 GEB_WCONST）int8 权重 Const 烤入

## 方案演化：为什么是 "(1+g) 回图" 而不是引擎域因子

- **v1（纯引擎域 s_eff = s_npz/(1+g)）爆雷**：L00 input_layernorm 有 193 通道 (1+g)≈0（26 个负值）→ s_eff ±e7，f16 smooth 行不可表示；这些通道贡献占 9-31% 不可钳（diag_fold_extremes.py 取证）
- **v2（g 回图）**：int8 层的 AddRmsNorm gamma 直接用 (1+g) 真值（loader fold 的替代源，safetensors 转换脚本供给）——norm 输出 = torch 域激活 h，**零新增算子**；权重侧照旧 w'·s_eff = w·s_npz（npz bit 级锚点不动）；smooth 行 = 1/s_npz ∈ [0.006, 0.956] f16 安全
- 组内留在 f16 的成员（PROJS 子集）由 `lin_f16_unfold` 除回 fold（双计防护）；残差流两域本就相同，层内语义恒等
- 转换脚本 `convert_smooth_engine.py`（npz → 引擎 safetensors，键 prefix/L{nn}/{proj}/s_eff|smooth|inv + L{nn}/g1|g2）

## 三只 bug 的取证链（本轮最大产出）

1. **GE fusion 离线导出腐蚀**：含 QuantMatmulDequant（ops_legacy 预编译二进制）的大图，默认 fusion pass 烤出的 OM **重载后全 65504 饱和，活图逐位干净**。定罪路径：单投影阶梯（gate/down 同炸）→ probe N2/N3 布局桥（干净，洗清 op-to-op 接线）→ 活图 vs 重载直比（12.51 → 65504 实锤）→ 单算 OM 往返（无损，洗清 legacy 序列化）→ **fusion off 后活图=重载逐位一致**。修复：烤 OM 必须 `GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（supervisor 生产配置本来就有——**手烤命令漏带 env 的坑**；bash 不认带点变量名的前缀赋值，须 `env GEB_INIT_OPT_ge.xxx=... ` 包裹）
2. **转换脚本丢 --invert**：v2 重写时 invert 分支被删、参数静默忽略 → smooth 行 = s 正向 → 乘法约定算子拿到 x·s @ w·s = s² 放大 ~1300×（kvk_l0 max_diff=13379 的量级指纹）。修复后 L0 = 1.8%。教训：**打印实际产出值**（现打印 smooth ∈ [min,max] 并断言域）
3. **n=256 嫌疑洗清**：生产 k-only 复现 1300× 后曾怀疑 KVD=256 的 kernel 分支——probe `GEB_QMD_N=256` 合成链 0.527% 干净，方向转回 smooth 值本身（顺带把 GEB_QMD_N/M 旋钮留给后人）

## 验收梯数字

| 阶 | 结果 |
|---|---|
| 量化对拍 int8_weights_v1.npz | **ALL_OK**：119 矩阵，wq 翻转 878/24 亿（全 ±1 LSB，fold 结合律 ulp），scale rel ≤2.2e-7；q 投影 scale 比值 = 1/√256（pscale 折入，比值钉死） |
| e2e golden（tl200_i8） | kvk_l0 1.8% / kvv_l0 1.6%（单层量化误差健康）；18 层线性累积 L17 31.5-41.6%（残差流叠加预期形态，f16 基线自身 L17 3.8-4.8%）；actions rel **13.3%**（f16 基线 0.9%） |
| Const 数值面 | 与 Data 版**逐位一致**（同 idx 同 max_diff）——Const 只是权重布局编译期定型 |
| task0 | **success 1.0**（steps=134, replans=27；终版 bias 砍除 Const 复验 1/1，steps=196 replans=40） |
| 全量 10 任务（libero_object） | **10/10 rate 1.0**（Data 版口径 model_ms P50 281）——flow 10 步欧拉对 13% actions 漂移鲁棒，C2 立项时的行为残余风险**销案** |
| perf（spool 直调，tl144 帧对拍） | f16：vision 60/prefix 104-108/flow 81，sum 243-249；int8-Data：prefix **129.5**（ND→NZ 每执行税 ~25ms ≈ 2GB/63GB/s，吃光算子 1.5× 收益）；int8-Const：prefix **87.3**，sum **228.2-228.7 = 0.607×**，帧漂移 0.1997（|nact|max 2.555）；bias 砍除版 prefix 87.1-87.7 **持平**（TileD+Add 对本就廉价；砍除保留，图更简） |

## 遗留与下一步

- **~28ms 到 0.53× 预算的缺口分解**：vision 60（C1 后残余）+ prefix 87（bias 砍除 perf 持平 87.1-87.7）+ flow 81（本轮不碰——下一杠杆：flow 侧 int8 或段间进一步融合；smooth_calib_v1.npz 已含 flow/* 因子）
- bias 砍除终版：perf 持平但图更简（保留）；**Const 终版全量独立复验 10/10 @ 238.9**（混合口径 objection 闭合）
- **M2 eager 补 gate 已闭环**（同日，子模块 e768fb2）：action_layer 两处残差 `branch·gate`（attention_style/mlp_style 第三段，gate_mats 缓存）；ascend_random_bench finite 1600/1600
- **libero_spatial 尝试两次均挂 harness init**（横幅后无输出 30min+，chip 3/7 无关；主进程 do_wait 子进程已死——multiprocessing init 谜题，须独立取证轮；与引擎无关，object 套件全程正常）——B 动态 L 定形的泛化验收下轮带此情报重试
- 校准 v2（逐层真激活替换单帧包络）：L0 1.6-1.8% 的下一压缩杠杆；权重面 per-group 量化同列
- qmd 的 bias 输入（int32）与 x_scale/x_offset 输入在 310P 编译不可用/未探明——留档
- **每任务 L 谱系确认 140-148**（9 桶）；eval 客户端 `APXINF_GE_SERVE_ROOT` 可指隔离根——本轮 int8 全量 eval 即用 `serve_i8` 隔离桶跑（mini_sup_i8.sh 复刻 supervisor 语义 + int8 env，未触碰共享 supervisor/tl 桶）
- PyO3 inproc 直调 int8 open 挂（AclError -2 warmup 首帧，f16 同环境正常）——未定案，inproc 非生产路径（spool 正常），留档

## 服务器状态

- 隔离桶 `/data/apxinf/serve_i8/`（tl140-148 int8 spool + mini_sup_i8.sh）与 `/data/apxinf/om_cache/tl{140-148,200}_i8/`（Const+砍 bias 版 OM）
- 共享 supervisor/serve/tl* 与 f16 桶**全程未动**（supervisor 两进程一直在跑，9 个 f16 桶死活状态未变）
- 器材：probe NSM 1-6 模式（smooth 约定/shape/布局桥/单算 OM 往返）、GEB_INT8_RUN（活图 vs 重载直比）、GEB_QMD_N/M（形状旋钮）
