# M3 真根因：empty_camera 视图语义（314% 漂移定位终结 + 修复）

日期：2026-09-21（夜班）　前置：[M3 对拍偏差定位](2026-09-20_m3-parity-drift-bisect.md)（当晚结论"GE OM 图内数值级"**部分推翻**）

## 一句话

**e2e 314% 的真根因是 empty_camera 视图语义：golden_gen 按 LIBERO 9/10 语义只喂 2 真实视图，empty_camera 走 missing 路径（-1 pad 图进 SigLIP 但 pad_mask=0）——make_att_2d_masks 的 pad_2d 把这 256 个 key 对所有人遮蔽、position_ids=cumsum(pad)-1 使文本位置塌缩到 512..711；引擎（和 golden v2 的 replay）都把它们当一等公民（可见 key + 占位 512..767）。修复 = x0 组装剔除该视图行（968→712），数学等价（theory_check 实证 h1 0.128%）。修复后 x0_vis 0.1% / kvk_l0 0.3% / step0_x1 10.1%；剩余漂移精确定位到引擎 MLP 段（m0 0.52% → h1 35.5%）。**

## 定位链（当晚五步裁决，全部实测）

1. **n1_prec_probe.py**（零 NPU 模拟）：f64 教科书链在 f16(golden h1) 上偏 kvk_l1 **18.71%——与 GE 图 18.7% 完全一致** → GE 图无罪，golden 数据内部不自洽（AddRmsNorm 饱和/累加、f16 量化、WCONST、mm 全部排除——所有变体都复现不出该签名）
2. **m0_world_probe.py**（四方矩阵）：m0_gold 偏全开世界 35.31%、偏 causal 94.31%——**属于第三语义世界**；kvk_l1 与全开世界链一致（0.11%）
3. **mask_recover_probe.py**（行画像）：m0_gold 偏全开的分岔集中在**图像行**（8-24%），文本行干净（2%）——排除 mask 结构/f16 数值/尖锐度赢家翻转
4. **golden_gen.py 源码**：`pol.image_keys = tuple(pol._image_features[:2])`（9/10 语义强制 2 视图）→ missing 路径 pad=0 → 遮蔽 + 位置塌缩 = 第三世界；v2 的 m0/h1/q0i（infer 抓）与 kvk（968 全开 replay 重放）**混世界**
5. **theory_check.py**（等价性证明）：712 可见 token 全开 + arange(712) 的 replay vs infer 真值 h1 对应行 **0.128%** ≡ 修复方案

## 修复（ge_model_probe.rs，GEB_PREFIX_DROP_EMPTY=256）

- `p = VT + tokens - drop_v`（prefix/flow 两段）；x0 组装只取 vision_out 前 (VT-drop_v) 行（视图主序，empty 在尾）
- golden v3（golden_gen_v3.py → frame0_v3.safetensors）：infer 侧键（patches/token_ids/noise/actions/vision_out/x0/m0/h1/q0i/k0i/v0i）原样搬运 + 712 语义重放键（x0_vis/m0_vis/h1_vis/kvk_l*/kvv_l*/prefix_hidden_vis/step0_x1）——自洽性实证 0.03-0.12%
- t712 OM 三件套（/data/apxinf/om_cache/t712/，vision 复用 t200）

## 修复后 e2e（golden v3 对拍）

| 指标 | 值 | 判读 |
|---|---|---|
| vision_out | 0.3% | 不变 ✓ |
| x0_vis | **0.1%** | 剔除语义正确 ✓ |
| kvk_l0 | **0.3%** | 输入链完美 ✓ |
| kvk_l1 | 45.2%（净图）/ 24.7%（dbg 图） | **剩余 = 引擎图层 0 块内 f16 数值**（图形状敏感） |
| kvk_l17 | 84% | 逐层复合 |
| step0_x1 | **10.1%** | 语义修复大幅收敛（旧口径终态 314%） |
| final actions | 323.7% | 10 步 euler 复合 v_t 误差（prefix kv 漂移所致）——修 MLP 后应收敛 |

## 剩余问题（已精确定位）

**引擎 MLP 段 f16 数值**（slot_cmp712.py 槽位判读，t712dbg 图 + DUMP_MID）：

| 级 | rel vs golden v3 真值 |
|---|---|
| m0_vis（attention 合并输出） | **0.52%** ✓ attention 无罪 |
| norm2 | 2.82% |
| h1（层 0 完整输出） | **35.53%** ← gate/up(K=2048,N=16384) → gelu → mul → **down(K=16384)** 段把 2.8% 放大到 35.5% |

下一步（嫌疑序）：① down_proj 单算对拍（真权重真 act 输入：GE mm vs aclnn eager vs f64——K=16384 f16 累加序/outlier 放大）；② gate/up mm 同测；③ gelu·mul 中间幅值检查（|act| 分布，可能溢出 f16 精度区）；④ 修复候选：split-K down（2×8192 mm + add）/ act 尺度预除 / 关 WCONST 对比。修到 kvk_l1 ≤5% → 全层复测 → e2e 终态 → LIBERO。

## 性能（t712，零回归且更快）

prefix **115.62ms**@712（was 138.81@968，-17%）/ flow **7.64ms**/步（was 8.12）/ vision 55.86 不变 → **稳态 e2e ≈ 55.86+115.62+10×7.64 ≈ 248ms = CUDA 378 线 0.66×**。剔除死 token 白赚性能。

## 环境速记

```bash
# golden v3（npu 容器 chip7）
ASCEND_RT_VISIBLE_DEVICES=7 PYTHONPATH=... python3 /data/apxinf/golden_gen_v3.py
# e2e（rust 容器 chip6）
GEB_SEG=e2e GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712 \
GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors ge_model_probe
# 槽位判读（dbg 图）：OM_DIR=t712dbg + GEB_DBG_MID=1 GEB_DBG_FULL=1 \
GEB_E2E_STOP=prefix GEB_E2E_DUMP_MID=<dir>；分析 python3 slot_cmp712.py
```

新分析脚本（本地 syx_docs/dev_logs/ 镜像 + 服务器 /data/apxinf/）：n1_prec_probe / m0_world_probe / mask_recover_probe / attn_impl_probe / infer_mask_probe / theory_check / golden_gen_v3 / slot_cmp712。

## 教训（对拍方法论）

**golden 与被测路径必须同一 forward 语义**：v2 的 infer-hook 键（m0/h1/x0/qkv）与手工 replay 键（kvk/step0）来自不同 mask/position 世界，造出"引擎 18.7-41% 漂移"假象，浪费了一整晚的 GE 数值嫌疑排查（AddRmsNorm/WCONST/mm/槽位复用全部排除）。判据：**先证 golden 自洽（torch 内部链 0.03-0.12% 级），再怪引擎**；golden 键间出现"同链不同世界"签名（小输入干净、大输入爆）优先查数据源而非算子。
