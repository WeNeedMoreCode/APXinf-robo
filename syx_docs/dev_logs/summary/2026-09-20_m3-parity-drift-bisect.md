# M3 对拍偏差定位：段边界 bisect 全链裁决（314% → 三层拆解）

日期：2026-09-20（晚班）　子模块：ge_model_probe 大改（bisect 工具链 + rope 修复）　前置：[M3 e2e 接线](2026-09-20_m3-e2e-chain-wiring.md)

## 一句话

**首帧 314% 漂移拆解成三层：① rope f16-inv_freq 语义差（已修，l0 k 12.6%→0.4%）；② 引擎语义/权重/attention/MLP 全部洗清（教科书复刻 0.03-0.14%）；③ 剩余偏差钉到 GE OM 图内——同一算子链在 x0 输入上 0.4%、在真实幅值 h1 输入上 18.7%，数值级（f16 累加/范围）嫌疑最大。**

## bisect 工具链（本轮新建，probe + golden 两侧）

- probe（`ge_model_probe.rs`）：`E2eStage.golden_mid` 可选中间量逐段对拍（`[e2e] BISECT` 前缀，含 argmax）；golden 键 `vision_out/x0/kvk_l{0..17}/m0/h1/step0_x1`
- golden（`golden_gen.py` v2）：
  - x0 = layer0 `input_layernorm` hook（⚠ 模块树真路径带 `.model.`：`paligemma.model.language_model...`；而代码经别名 `paligemma.language_model` **直接 .forward() 调用绕过 __call__，模块 hook 不触发**）
  - prefix k/v cache 18 层 = **手工重放** prefix pass（同 x0/权重/全开 4D 零 mask——`GemmaModel.forward` 对 None mask 会 `create_causal_mask`，必须显式传）
  - step0_x1 = 手工重放 denoise_step（embed_suffix → expert 分支 → action_out_proj → x+dt·v）
  - m0/h1 = pre-hook（o_proj 输入 / layers[1] 输入）；q0i/k0i/v0i = infer 侧投影输出
- 分析脚本（服务器 /data/apxinf/，本地镜像 syx_docs/dev_logs/）：`l0_bisect.py`（norm/proj/rope 分级）、`rope_probe.py`（rope 约定枚举）、`attn_scale_probe.py`、`attn_l0_h1.py`（层 0 全块复刻）、`weights_cmp.py`（引擎加载 vs torch 权重）、`m0_variants.py`（attention/MLP 错误变体枚举）、`stage_cmp.py`（图内槽位判读）

## 裁决链（全部实测）

| # | 结论 | 证据 |
|---|---|---|
| 1 | **vision 段干净** | BISECT vision_out rel=0.3%（patch 行序/预处理/SigLIP 27 层/projector 全洗清） |
| 2 | **x0 组装干净** | rel=0.1%（cat 序、lang×√2048、查表） |
| 3 | **rope f16-inv_freq 是第一根因（已修）** | torch `.to(f16)` 连 `rotary_emb.inv_freq` buffer 一起量化，HF 用 f16 频率回 f32 算角；引擎 f64 全精度 → 高位置相位差 O(0.1 rad)。`rope_probe.py` 枚举实证：f16-inv 复刻 rel=0.08%，全精度 12.64%。修 `rope_flat_const`/`rope_rank2_const`（`rope_angle()`：inv_freq 先量化 f16）+ t200 OM 重烤 → **kvk_l0 12.6%→0.4%** |
| 4 | **权重加载干净** | weights_cmp.py：q/k/v/o/gate/up/down 折叠后 vs torch 0.000% |
| 5 | **attention 语义/实现干净** | attn_l0_h1.py：教科书复刻 o_proj 输出 0.03%；GE 图 m0 槽值 vs 复刻 0.52%；q/k/v infer↔replay 逐位 0.00% |
| 6 | **层 0 全块（attn+残差+MLP）语义干净** | 复刻 x+attn+mlp vs golden 层输出 0.03%；GE 自身 m0 → 教科书链 → k_l1 vs golden kvk_l1 **0.14%** |
| 7 | **manual GQA 链（TileD/bmm/softmax/headsplit）无罪** | PFA 版 prefix OM 的 k_l1 与 manual 版完全同值（4.29004 vs 4.29199） |
| 8 | **GE 图实际 k_l1 偏 41%（d18/d2 稳定）/ 23.7%（DBG_FULL 图）/ 18.7%（golden h1 直入 + L1 权重）** | 同一算子链：x0 输入 0.4%，h1 输入（\|max\| 1562）18.7% —— **数据依赖的数值级偏差**，非结构错 |
| 9 | 附带发现：GE 静态 OM **中间量输出槽可被图内复用覆写** | res 槽实测返回 norm2 的值（526/rms≈44 量级吻合）；加输出 tap 会改变 k_l1 值（41%↔23.7%）= 内存计划敏感；用户输出 buffer 间插 1MB dummy 无变化（非用户侧 OOB） |

## 已排除（本轮证伪的假设）

- suffix att_masks `[1]+[0]*49`：cumsum 后 50×50 全可见，等效全开 mask——引擎无 mask 语义等价 ✓
- attention scaling：golden 实测 `scaling = head_dim^-0.5 = 0.0625` 与引擎一致（非 hidden_size）
- denoise_step 结构：suffix 联合 attention 拼接 [prefix;suffix] kv + position 968..1017 + cache k 已 rope——引擎 `kcat/vcat ConcatD` + `rope_flat_const(HOR,·,p)` 动态 offset 全对齐
- (1+w) 折叠 / gate/up 交换 / gelu 近似模式 / RMS_EPS / 位置 / GemmaAdaLayerNorm chunk 序：逐项核过 ✓

## 剩余问题（下一步）

**GE prefix OM 在真实幅值输入下 norm→k_proj→rope 链数值偏差 ~19%**（golden h1 直入 + L1 权重实测），逐层复合后至 l17 85%、e2e 终态 314%。x0 输入同链 0.4%——嫌疑集中在 f16 数值路径：
1. **AddRmsNorm 的 f16 方差/累加行为**在大动态范围输入（h1 \|max\|=1562 vs x0 526）下的精度——optest 单算子级复测（真权重真输入）
2. **WCONST（mm 权重 Const 入图 + NZ 转换）与 Data 权重版的数值差**——同图关 WCONST 重烤对比
3. mm（MatMul f16 cube）在 2048 宽 K 维的累加精度——GE vs aclnn eager 对拍
4. 中间量输出槽复用覆写：出图时对需观测节点插防复用手段（或全部走 kv 主输出）

修到 ≤5% 后接：e2e 全链复测 → 延迟 bench → LIBERO（9/10 基线）。

## 环境速记（bisect 运行模板）

```bash
# golden 重产（npu 容器 chip7）
ASCEND_RT_VISIBLE_DEVICES=7 python3 /data/apxinf/golden_gen.py   # frame0.safetensors 含全部中间量
# e2e bisect（rust 容器 chip6）
GEB_SEG=e2e GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
GEB_CKPT=... GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t200 \
GEB_E2E_GOLDEN=/data/apxinf/golden/frame0.safetensors ge_model_probe
# 分段旋钮（本轮新增）：GEB_DEPTH_VISION/GEB_DEPTH_PREFIX 分段深度、
# GEB_ATTN_PREFIX 分段 attention、GEB_E2E_STOP=prefix 截断、GEB_LAYER_OFFSET
# 权重层偏移、GEB_E2E_X0_KEY=h1 输入直换、GEB_DBG_MID/GEB_DBG_FULL 图内
# 调试输出、GEB_E2E_DUMP_MID 槽位落盘、GEB_OUT_PAD 占位取证
```
