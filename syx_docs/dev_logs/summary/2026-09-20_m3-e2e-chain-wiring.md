# M3 第二步：三段 OM 接入真实推理链（GEB_SEG=e2e）

日期：2026-09-20　子模块 commit：`c8ca41b`（fork/ascend-port）　前置：真权重 OM 三件套（[2026-09-20_m3-real-weights-into-om](2026-09-20_m3-real-weights-into-om.md)）

## 一句话

**ge_model_probe 新增 e2e 模式：vision→prefix→flow 10 步进程内链式（host 中转）——x0 真嵌入组装（vision_out ‖ token 查表）、styles 真值（time_mlp→style→1+s0）、pk/pv = prefix OM 36 输出直连，chip6 bring-up 全通（GE_E2E_PROBE_OK，|x|max 89.9→34.6 单调收敛）。golden 对拍与 LIBERO 归下一步。**

## 接线口径（全部对齐 ascend_runtime = M2 eager 全链 = CUDA 镜像同源）

- **x0** = `cat(vision_out [768,2048], token_embedding[ids] [64,2048])`——视觉前、语言后；**state 不进 prefix**：π0.5 走 state 离散化进 prompt 文本（`pi05_prompt`/`discretize_state`，math.rs），随语言 token 查表
- **styles**：`t = flow_start·(1-step/N)` → `sinusoidal_time_embedding(t, AW=1024, 4e-3, 4.0)` → cond = silu 两层 time_mlp [32] → 每层 style 投影 [32,3AW] → **ascl=1+s0 / ash=s1**（executor L714-719 切分 [0:w]/[w:2w]，第三段引擎未消费）；host f32 算，每步 h2d 覆写（qkv3 布局：ascl/ash=base+0/+1，mscl/msh=base+10/+11，尾 fsc/fsh）
- **pk/pv**：prefix OM 36 输出（k0,v0,k1,v1,...）host 中转进 flow 输入（~30MB 一次性，设备直连是后置优化）
- **10 步循环**：state=x 每步 h2d 换绑（euler 已在图内，x'=0.9x-0.1v）
- **golden 钩子**：`GEB_E2E_GOLDEN=<safetensors>`（键 patches[768,588]/token_ids[N]/noise[50,32]/actions[50,32]，f32 存储）；缺省合成 bring-up（占位 token ids——真 tokenizer 随 golden 落地）
- OM 从 `GEB_OM_DIR`（默认 /data/apxinf/om_cache）读 `{seg}_real.om`；须配 GEB_CKPT + 四件套（ATTN=manual/QKV3/ROPEFLAT/WCONST——与 OM 构建配置一致，输入序才对）

## bring-up 结果（chip6，合成 patches/noise + 占位 token ids）

- vision_out |max|=178 / prefix kv×36 |max|=14.5 / flow |x|max **89.9→80.9→...→34.6 单调衰减**（euler 收敛行为 ✓）/ actions 全有限
- 各段一次性墙钟：vision 10s / prefix 77s（含 2.1GB 嵌入 f32 物化）/ flow 9.5s——含 OM 加载与 host 组装，**非稳态延迟**（稳态口径仍为 bench 55.86+124.61+10×7.89 ≈ 259ms）
- 坑：vision OM 绑 108 个 LN aux 输出（trap #17 必须绑），e2e 取 idx0 为主输出

## 遗留 / 下一步

1. **golden 对拍**：npu 容器产一帧 golden（patches/token_ids/noise/actions safetensors——用 stage-1 `noise=` 精确注入同噪声）→ probe 对拍；**同时裁决 prefix 100% 漂移的实际影响与 euler/视图数语义**（⚠ 开放矛盾：引擎 VT=768 三视图 vs stage-1 mask 修复后官方链疑似 2 视图——golden 形状见分晓；prompt token 数须 16 倍数对齐，可在 golden 侧 pad 任务文本）
2. LIBERO 对标（9/10 基线）→ 真实 e2e 延迟 bench（host 中转/61s 加载/占位 tokenizer 一并工程化）
3. 后置：pk/pv 设备直连（免 host 中转）、checkpoint 按段懒加载、真 tokenizer 进 Rust

## 环境速记

```bash
GEB_SEG=e2e GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
[GEB_E2E_GOLDEN=/data/apxinf/golden/frame.safetensors] \
./target/release/examples/ge_model_probe
```
