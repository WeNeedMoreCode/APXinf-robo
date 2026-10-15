# 2026-10-15 I10 预检与可行性判决：vision int8 真实收益 −6~7ms，建议不立项

立项前提（handoff ④ I10 行）：MatMulV2 30.8ms = vision f16 mm，M=768 大段同 prefix 机制，「prefix 已证 2.41×/−18ms」→ 预期 −18ms；**先做权重谱预检再决定投入**。

## 预检四步（全部完成）

**① 权重谱 ✅ 过关**（probe_dyn/int8_weight_errspec_vision.py，per-row int8 与 C2 同数学，补上当年 regex 漏掉的 q/k/v）：

| 组 | rel_rms med | worst_row max |
|---|---|---|
| vision 总体（162 矩阵） | **0.893%**（p90 1.15%） | 18.4%（L01.fc1 单行） |
| prefix 对照（先例，行为过关） | 0.895% | 11.2% |

q/k/v/o 全干净（0.83-0.91%、worst_row ≤5%）；mmproj 0.855%。**权重侧与 prefix 同水平，无障碍。**

**② 激活谱 ✅ 温和、dump 就位**（probe_dyn/golden_gen_visioncalib.py → /data/apxinf/golden/calib_vision_v1.safetensors，267MB）：
replay_t0-3 真帧 40 帧（FRAME_EVERY=4）× SigLIP 塔 hook（27 层 × q/k/v/o/fc1/fc2 + mmproj 输入；**空视图 -1 pad 行在 768 行里天然进包络**）。per-channel amax：塔内各站 ≤15（Gemma 当年 559）、mmproj 输入 48.6；通道动态范围 med→max ~30-300× → smooth 有意义但幅度温和。工程坑（已记）：embed_image 被实例级 torchair fullgraph 包裹 → del 实例属性恢复类级 eager（v3 同款手法）。

**③ L2-lite 离线模拟**（probe_dyn/int8_vision_sim.py，qmd+smooth 数学镜像 × sim 采样帧）：

| proj | α=0 med/max | α=0.5 med/max |
|---|---|---|
| vq/vk/vv | 2.2/2.5% → | **1.36-1.56% / ≤1.87%** |
| vo | 1.20% → | 1.07% |
| vfc1 | 1.19% → | **0.80%** |
| vm | 0.92% → | 0.50% |
| **vfc2** | 2.19% → | **1.86% / 4.12%（超先例带 0.66-1.42%）** |
| 总体 | med 2.08% | med 1.32% / p90 1.80% |

- **α=0.5 定案**（α 细扫 0.75/0.9 全面恶化——vision 是权重侧瓶颈，把更多范围压进权重有害；与 Gemma 相反）。
- **vfc2 三旋钮全救不动**：α（1.86% 地板）、权重行 clip（99.9% 即爆炸至 med 5.8%/max 32%——smooth 折过的权重行重尾，amax 是唯一安全 scale）、s 下限 floor（0.02-0.2 全无差异——死通道放大假说证伪）。**结构性地板 = gelu 输出（全段唯一无归一化站）+ 权重行 outlier（errspec 里 vfc2 权重 rel_rms 0.997% 也是 vision 最高）。**

**④ 收益重估（判决核心）**：
「2.41×/−18ms」引用的是 C2 合成形状（m832/n8192）的虚高数——**C2 当年已自我修正为真实形状 1.49-1.56×**（handoff I10 行沿用了旧数）。按实数重估：
- 全量 int8（含 fc2 风险）：30.8ms @1.5× → **−10.3ms**，但 fc2 1.86/4.1% 超先例带，27 层堆叠 + 条件链放大，行为风险不可控（v3 教训：分布错配翻行为）。
- **mixed（fc2 留 f16，q/k/v/o/fc1/mmproj int8 α=0.5）**：int8 覆盖 ~67.5% 的 vision mm 时间 → 20.8ms @1.4-1.55× → **−6~7ms**（246.9 → ~240），误差带 med ≤1.56% 全部回到先例带内。

## 判决

**建议不立项**（降级 backlog）：
- 代价 = prefix int8 战役整套重打：引擎 vision 图 builder int8 发射（Rust 子模块改动）+ 校准因子链 + 烤桶 + 对拍梯 L2-L4 + 行为全量验收。
- 收益 = **−6~7ms（model 246.9 的 2.5-3%）**，且 mixed 方案（fc2 f16）是数值安全的前提。
- 若未来要榨最后一段：全部前置已留档（校准数据 267MB + 三脚本，fc2 处置选项=留 f16 或 outlier 行拆分 f16 补偿 mm——后者图复杂度不值）。
- 量化域至此**到头**：prefix 全 int8 ✓ / flow gate-up-down int8 ✓（小 M 判不值） / vision 判不立项（fc2 结构地板）——mm 域再无未开垦地。

## 工具与产物

- probe_dyn/：`int8_weight_errspec_vision.py`（权重谱，q/k/v 补全）、`golden_gen_visioncalib.py`（激活 dump，eager 绕编译手法）、`int8_vision_sim.py`（qmd+smooth 模拟器，α/clip/floor 三消融）
- 服务器：`/data/apxinf/golden/calib_vision_v1.safetensors`（venv 163 键 + sim 326 键，40 帧）
- 战报数字全部可复算（脚本直读 ckpt + calib 产物）
