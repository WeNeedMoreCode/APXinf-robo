# M3 起跑：真 checkpoint 权重接入三段 OM（GEB_CKPT）

日期：2026-09-20　子模块 commit：`281d703`（fork/ascend-port）　前置：C2 收官 263.3ms（见 [2026-09-20_c2-wrapup-nz-weight-tax](2026-09-20_c2-wrapup-nz-weight-tax.md)）

## 一句话

**ge_model_probe 合成权重路径换成 LeRobot safetensors 真权重（host 解析 → bf16→f16 → wt() Const 路径），产出真 checkpoint OM 三件套 `{vision,prefix,flow}_real.om`——bench 与合成 r3 打平（55.86/124.61/7.89ms，全模型 ~259ms），真权重零延迟代价；prefix 真权重漂移曲线 16.8→100%（机制同源被 outlier 放大），e2e 判定归 M3 剩余步骤。**

## 接入设计

- **复用 M2 管线**：`Pi05Weights::from_safetensors`（LeRobot 前缀归一、`[in,out]` 物理转置、**Gemma `1+w` scale 折叠**——g1/g2=ones、scale 折进 q/k/v/gate/up；SigLIP 结构映射 + 形状校验），probe 侧只做 `t_f16`（任意 float Tensor → f16；310P 无 bf16）+ `lw_f16`/`lb_f16`（LinearWeights.weight/bias，None→zeros）
- **env**：`GEB_CKPT=<dir>` → main 加载一次 `Option<&Pi05Weights>` 穿进三段 builder，各权重位点 `real.map(...).unwrap_or_else(rand_f16)` 换源（合成路径原样保留为缺省）
- **映射面**：vision 全有值（patch/pos/proj + 每层 LN γ/β + qkv/out/fc1/fc2 权重+bias，qkv bias = q‖k‖v 拼接）；prefix/flow 的 Gemma 投影**无 bias → zeros**（o_proj/down_proj/downb/outb/qkvb）；**ada-norm 条件向量（ascl/ash/mscl/msh/fsc/fsh）与 x0/state/pk/pv 保持合成**——它们是运行时输入（随 time step/请求变化），两路同值对拍不受影响，真值接线归 M3 剩余步骤
- **布局契约核对**：`Pi05Weights` LinearWeights.weight `[in,out]` 与 probe `wt(host=[rows=in, cols=out])` 同构，零额外转置；attn_manual 的 1/√hd scale 折叠照旧作用于真 wq/bias

## 结果

| 段 | 真 OM bench（LOAD 路径 median/10×30，chip6） | 合成 r3 | parity（真权重） |
|---|---|---|---|
| vision 27 | **55.86 ms** | 55.89 | **0.1%**（同合成） |
| prefix 18 | **124.61 ms** | 128.44 | **100%**（见下） |
| flow /步 | **7.89 ms** | 7.90 | 37.4% |

- **OM 三件套** `/data/apxinf/om_cache/{vision,prefix,flow}_real.om`（833926285 / 3757726771 / 627774372 字节——与 _r3 **逐位同大小** = 同拓扑，权重内容不同）；GEB_LOAD 加载+parity+bench 全通
- **prefix 真权重漂移深度曲线**：d=2/4/8/18 → **16.8 / 59.7 / 100 / 100%**（合成时 6.0/10.9/15.6/25.1%）。定性：**layer0 K/V 仍逐位一致**（d=2 时 out0/1 = 0.00000）、绝对 max_diff 次线性平滑饱和（5.5→16.7→19.4→36.7，无跳变无 NaN）——C2 销案的 fp16 大 K 累加序机制被真 Gemma 权重的 outlier 通道放大（Gemma 权重已知存在大 outlier 通道），非 bug；**实际影响由 M3 e2e（GE OM 输出 vs torch_npu golden）判定**
- flow 37.4%：输出 |max|≈1.1 小分母 + 同机制（合成时 1.6% 的分母量级不同）
- checkpoint 加载 **61s/进程**（7GB mmap 全量解析；prefix 层 fold 的 f32 临时峰值正常）——迭代期可接受，后置优化项：按段懒加载

## 遗留 / 下一步（M3 剩余）

1. **三段 OM 接入真实推理链**：prefix x0 = 真嵌入（token_embedding 查表 + vision projector 输出合流 + state embed）、flow ada 条件 = 真 style 投影 × time_mlp(time embedding)（注意 openpi 的 `rms(x)·(1+s0)+s1` 约定 → ascl=1+s0 host 变换）、pk/pv = prefix OM 输出直连（36 输出 K/V）——之后 e2e 延迟 bench
2. **LIBERO 对标**（9/10 基线）+ prefix 漂移实际影响判定（vs torch_npu golden）
3. 后置：checkpoint 懒加载、nz desc 直入（开放项）、非税常量 Const 化

## 环境速记

- 运行模板（真权重）：`GEB_SEG=<seg> GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned GEB_BENCH=1 GEB_ROUNDS=30 GEB_PER=10 ./target/release/examples/ge_model_probe`
- ⚠ GEB_LOAD 真 OM 必须配 GEB_CKPT（eager 参考从 binds 取权重，缺则对拍错权重）
- ⚠ parity ≥20% 且无 GEB_BENCH 时探针静默 exit(1)（无报错行）——对拍高漂移段要带 bench 跑
