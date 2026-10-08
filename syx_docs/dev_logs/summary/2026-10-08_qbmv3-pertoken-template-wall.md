# 分解式 w8a8 落地判决：per-token 模板墙 + 性能双杀出局（2026-10-08 晚）

## 终局一行

**分解式 w8a8（DynamicQuantV2 + TransQuantParamV2 + QuantBatchMatmulV3）在 310P 出局**——per-token 语义在 kernel 模板实例化清单里不存在（源码级铁证），唯一可建形态是静态 x scale-only（运行确认），且三算子链在 flow 形状比现行 qmd 慢 2×（性能前提同死）。**qmd per-token（现行生产形态）就是 310P 量化侧的终点形态**；0.53× 无路径的结论加固（上轮战报的"唯一存续路线"判断被本轮运行阶段证伪——build 过 ≠ 语义在）。

## 证据链（三重）

### ① 模板墙：core 200 的实例化清单只有 2 条

- `quant_batch_matmul_v3_tiling_key.h`（opp impl 源码自带）模板清单按 `__CCE_AICORE__` 分支：
  - **core 200（310P3，platform_config.ini: AIC_version=AIC-M-200）**：仅 `B_TRANS + TBE + NOT_PERTOKEN` ×2 条（OPTION_ATTRS NONE/ATOMICLEAN），**且只在 u64-scale 条件下**——f32-scale 在 core 200 零模板（NZ_NZ f32 binary 完全不可用）
  - **IS_PERTOKEN 全家族（TBE/OPT/BASIC × 4 trans）全在 core 220 分支**（新芯片）
- 运行时复现：接上 pertoken_scale → tiling 选 key **21**（6bit 高→低 = needClean, pertoken, opt, basic, transX1, transX2；21 = basic+pertoken+B_TRANS）→ `get_op_tiling.py:1346 KeyError: '21'`（tiling_struct_expr_map 无此键 = binary 的 tiling 注册表没有）→ task_distribute 崩。与 WQBMV2 同款 arch35 模板墙，本次拿到源码+运行时双证据。

### ② no-pertoken 唯一形态的语义解码（Z3 mode 3 运行确认）

- 图：x → DQ → x1 int8；wq int8 [n,k] ND Data（GE 自动插 TransData→NZ，图 dump 实证 Input(1)=trans_TransData_4）；TQP(ws f32) → u64 packed scale op-to-op；**不接 pertoken_scale** → build+run 全通
- 对拍：`y = sw[n]·Σ xq·wq` 假设 max_diff=2.33（|y|max≈8700，0.027% = int 累加序+f16 舍入噪声）vs 带 sx 公式 max_diff=8143 → **确认无激活 scale 通道**。数学上要求 s_x 静态折进 packed scale（s'_w[n]=s_w[n]·s_x）——即 goal ① 原始梦想的"静态 x"借尸还魂，但：
  - f16 值域陷阱：不折 s_x 的裸 `sw·Σ` 输出 |y|≈8700 贴近 65504 上限（真实权重 k=8192 时必然溢出）——行后补 rescale 的 workaround 数值上不可行
  - 静态 per-tensor scale 对 Gemma 激活 outlier 的精度风险（L2 已证朴素 per-token 都 12.7%，静态更差；smoothquant 缓解但 flow 逐步 x 不可预知）

### ③ 性能 kill-shot：三算子链 2× 慢于 qmd @ flow 形状

- m=50 k=2048 n=256：**Z3 链（DQ+TQP+QBMV3）0.119ms vs Q（qmd）0.059ms**（Q/Z3=0.49×）；同形状 int8/f16 = 0.96×（m=50 int8 本身无收益，与上轮"小 M 收益被 per-op 开销吃掉"一致）
- 即使共享 DQ（q/k/v 三算一 DQ 的生产 cell 算术），3 kernel 固定成本 > qmd 融合单算的 in-op 量化流水——**"量化开销省 43%"的上轮估算被证伪**

## 顺带解码（probe 副产物）

- **DQ 默认语义**：scale[0..4] 同值 = **per-tensor**（非 per-row），除数≈128（非 127），offset 非零 = **asymmetric 默认**；y vs 对称 round 参考 mismatch 62%（asymmetric 所致，语义未细挖——消费者已死，moot）
- **TQP 打包**：非 f32-bits 直排（low32/high32 对照 0/256）——位型未解码（静态折叠路线死后无需求）
- QBMV3 图组织事实：x2 ND Data + transpose_x2=true → GE 自动插 TransData→FRACTAL_NZ（无需 host int8 NZ 重排）；多输出图输出按 size 对号（陷阱 #32 复用）

## probe 资产

- `GEB_QMD_Z3`（ascend_ge.rs，链 Z3）：=1 全链（pertoken 接线，310P 模板墙复现器）/ =2 DQ 单算 / =3 no-pertoken 语义解码（本轮判决用）
- 取证路径沉淀：`platform_config/<SoC>.ini` 的 AIC_version 判 core 代际（200=310P / 220=新芯片）→ `impl/**/op_kernel/*_tiling_key.h` 模板清单判该 SoC 实际实例化哪些形态（比"注册表 json 存在"更强的判据——json 的 simplifiedKey 有 p=1 条目但 kernel 无模板 = 假门）

## 战略图景（量化侧全线收束）

| 路线 | 判决 | 证据轮 |
|---|---|---|
| qmd 静态 x_scale | ✗ bin 忽略输入 | 2026-10-08 早 |
| w8a16 WQBMV2 | ✗ 模板墙 | 同上（eager 证 kernel 活） |
| 分解式 per-token | ✗ **模板墙（本轮，源码级）** | 2026-10-08 晚 |
| 分解式 static-x | ✗ 语义可行但 perf 2× 慢 + 精度风险（本轮） | 同上 |
| **qmd per-token（现行）** | ✓ **终点形态** | 生产 10/10 |

剩余可动杠杆只剩行为面/生产面：**② 校准 v3**（flow int8 行为修复 = 回收 -5.4ms 的唯一路径）与 **③ task7 取证 + 扩桶**。
