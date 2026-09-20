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

### 语义侦察（2026-09-20 追记，lerobot modeling_pi05.py 取证，golden 对拍前置）

- **已对齐两处**（子模块 d960a9b）：① lang 查表行 **× √2048**（embed_language_tokens L695，gemma embed scale；vision 段无缩放）② euler 换绑 **c1=1.0/c2=-0.1**（sample_actions L894 积分式 x'=x+dt·v；OM 缺省 0.9/-0.1 是 openpi x1-预测式——两官方实现本身不同源）——c1/c2 是 flow OM 的 Data 输入（binds 尾两位），h2d 覆写即可
- **state 无通路（确证）**：pi05 LeRobot 显式跳过 state_proj（L1129）、suffix = 50 纯 action tokens（time 只进 ada-norm cond 不进 token 流）——**Rust 引擎无缺输入通路**；此前"state 走 suffix/prompt"两说均不成立
- **视图数矛盾解除**：缺失相机 = -1 pad 图占位 + mask=0（_preprocess_images）→ 模型仍消费 **768 patches/3 视图**，与引擎 VT=768 一致（mask 只影响 attention 侧，prefix OM 无 mask 的差异待 golden 裁决量级）
- **待 golden 裁决**：suffix att_masks `[1]+[0]*49`（make_att_2d_masks 语义——action tokens 间互相可见性 vs 引擎 cross-attn 全拼 kv）；prefix 漂移 100% 实际影响；patch 行序 (c,kh,kw)（引擎与 F.unfold 同构，按构造应一致但从未被真图验证）
- time_mlp/te 维度 ✓ 一致（te=1024=min AW、min/max period 同 config）；position_ids=cumsum-1 → suffix 从 832 续 ✓ 与引擎 flow rope offset=832 一致

1. **golden 一帧已产出**（2026-09-20 晚，`/data/apxinf/golden/frame0.safetensors`，脚本 `syx_docs/dev_logs/golden_gen.py` ↔ 服务器 `/data/apxinf/golden_gen.py`；npu 容器跑法 `export PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH` **追加勿覆盖** + `ASCEND_RT_VISIBLE_DEVICES=N`）。侦察实锤四条：
   - pixel_values **(3,3,224,224)** min=-1.0——三视图 + empty 相机 -1 pad 实锤，VT=768 无矛盾
   - patches (768,588) F.unfold 构造正合（行 (c,kh,kw)）
   - **input_ids len=200**（tokenizer pad 到 max_length；~50 真 token + 150 pad，pad mask=0 不参与 attention/position）→ **真实 prefix = 768+200=968，且 968 非 16 倍数 = 对齐死结**：候选解法 a) GE 静态 OM 直接编 M=968 试一把（非 16 倍 M 崩是 eager aclnn 经验，GE 未必）+ golden 任务文本填满 200 全真 token（pad token 引擎侧无 mask，必须消 pad）b) 引擎图内/host pad 到 976（GEB_TOKENS=208）但 torch 侧 200 上限锁死 → 两路输入不一致，不可行 → **先试 a**
   - **actions (50,7)**：predict_action_chunk 返回已切 deployable 维——probe 对拍须取 e2e 输出前 7 列（golden 键 actions 即 (50,7)，probe 侧比较代码要适配）
2. **对拍执行**（token 对齐解开后）：`GEB_E2E_GOLDEN=/data/apxinf/golden/frame0.safetensors GEB_TOKENS=<对齐值> GEB_SEG=e2e 四件套 GEB_CKPT=...`；⚠ prefix/flow OM 需按新 P 重建（GEB_SAVE 重烤，分钟级）
3. LIBERO 对标（9/10 基线）→ 真实 e2e 延迟 bench（host 中转/61s 加载/占位 tokenizer 一并工程化）
4. 后置：pk/pv 设备直连（免 host 中转）、checkpoint 按段懒加载、真 tokenizer 进 Rust

## 环境速记

```bash
GEB_SEG=e2e GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
[GEB_E2E_GOLDEN=/data/apxinf/golden/frame.safetensors] \
./target/release/examples/ge_model_probe
```
