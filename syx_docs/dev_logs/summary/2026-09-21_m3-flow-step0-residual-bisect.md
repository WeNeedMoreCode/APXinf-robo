# M3 flow step0 残差 bisect 结案：输入源全洗清，残差定位于 flow 段执行语义（fp16 vs torch 混合精度）

日期：2026-09-21（下午班）　前置：[addrms 融合根因终结](2026-09-21_inplace-addrms-fusion-root-cause.md)（step0_x1 11.8% 与 addrms 无关，修复前后同量级）

## 一句话

**step0_x1 11.8% 的三个候选输入源两腿正交全部洗清**：pk/pv 替入 golden（kvk/kvv 真值）→ 12.4% 不动；cond 替入 golden（styles 上游真值）→ 11.8% 与基线全等，且 host-vs-golden cond 差仅 0.0004-0.012（fp16 量化级，te+mlp 链语义正确）⇒ **残差在 flow 段执行本身：我们 fp16 全链 vs torch 混合精度**（Gemma RMSNorm 在 torch 里 fp32 上浮算方差再 cast 回，我们 AddRmsNorm fp16 直算；叠加 kernel 融合/累加序差）。绝对量视角：step0 abs 0.35（分母 2.95）vs prefix l17 abs 1.6（分母 42）——flow 实际比 prefix 干净，rel% 是小分母假象。

## 实验设计（正交替入）

flow 段的输入 = {x0=noise（已 golden）、pk/pv（prefix 产物）、styles（host f32 算）}。新增两旋钮 + golden v3b：

| 腿 | 替入 | step0_x1 | 裁决 |
|---|---|---|---|
| 基线（addrms 修复后） | — | 11.8% | 参照 |
| PK_GOLD | pk/pv ← golden kvk_l*/kvv_l*（36 张量全真值） | **12.4%** | prefix k/v 残差（0.4-4.8%）不是主因 |
| STYLE_GOLD | cond ← golden cond_s{step}（te+mlp 后真值，styles 由 host 投影重算） | **11.8%（全等）** | cond 链不是主因 |

两腿都不动 ⇒ 残差在执行内部。与 flow 段 eager parity 4.4%（GE vs 我们 eager，同 fp16 语义）自洽：GE 与 eager 共享 ~11.8% 的对 torch 公共模差（fp16 语义），两者互差只剩 4.4%。

## 顺带战果

1. **kvv 对拍曲线补全**（此前只对拍 k 侧）：v 残差 1.1%→4.8%（l0→l17），与 k 侧 0.3→3.8% 同形——fp16 累积曲线对称确认。
2. **cond 精度直接实测**：host f32 链 vs golden f16 链（torch 在 mlp 前就把 te cast 成 f16——`time_emb.to(timestep.dtype)`，timestep 本身 f16）差仅 0.0004-0.012。**结论：te/cond 的 f16-vs-f32 语义差不值得追**（对 x1 影响 <0.1% 量级，含在 11.8% 不动里）。
3. golden v3b = v3 ∪ cond_s{0..9}[1024]（97MB，/data/apxinf/golden/frame0_v3b.safetensors；生成脚本 golden_gen_v3b.py，time 调度实证 = `1.0 + step·dt`，dt=-1/N）。v3 键原样保留。
4. probe 新旋钮：`GEB_E2E_PK_GOLD=1`（pk/pv 喂 golden）、`GEB_E2E_STYLE_GOLD=1`（cond 喂 golden，须配 v3b）。

## actions ~360% 的定性

abs max_diff=3.8（|max|=1.055）。两层放大：① 小分母（actions O(1)）；② **轨迹混沌放大**——x 链式反馈 10 步，每步 ~0.35 abs 的 fp16 级差被 denoiser 递归放大（同 checkpoint 对 noise 重采样敏感的 stage-1 结论 replan=1→8/10 同源）。这不是"实现错"的证据，也不是"没问题"的证据——**M3 裁判是 LIBERO 成功率**（验收线 ≥ 9/10 − 1pp）。

## 下一步（M3 剩余，优先级序）

1. **真实 e2e 稳态延迟 bench**（现 bring-up 计时含 OM 加载/对拍开销；host glue 是已知大头——styles 每步 host 算 + h2d、pk/pv host 中转）
2. **LIBERO 对标**（parity 残差是否伤行为的最终判定）
3. （可选深挖，LIBERO 不达标才做）RMSNorm fp32 上浮对齐：flow OM 的 AddRmsNorm 换 fp32 方差路径（LayerNormV4 类），预期 step0 parity 明显收敛
4. 后置：pk/pv 设备直连、懒加载、真 tokenizer

## 教训

1. **rel% 要带分母读**：11.8%（分母 2.95）abs 0.35 < prefix 3.8%（分母 42）abs 1.6——"flow 比 prefix 脏 3 倍"是小分母错觉。
2. **正交替入是最快的输入源排除法**：两腿实验（各 ~3.5 min）钉死三个候选，比逐个深挖 host styles 数学快一个数量级。
3. 对拍链里的"共同模差"要单列：GE-vs-eager 4.4% 不代表离真值 4.4%——两边共享的语义差（fp16 vs torch 混合精度）只在 vs golden 显形。
