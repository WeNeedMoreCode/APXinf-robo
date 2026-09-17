# 阶段一：npu-torch 引擎接入 apxinf_robo（design，living doc）

## 目标

`build_robot_policy(robot, model_dir, engine="npu-torch")` 可用——上层（serve / eval-libero / bench）不感知引擎差异，内部走 LeRobot π0.5 + torch_npu。

## 事实：两侧的契约

### apxinf_robo 侧（要满足的）

`apxinf/policies/base.py` 的 `Policy` 是**结构化 Protocol（鸭子类型，runtime_checkable）**：

- `.metadata`: Mapping（server 在 connect 时推给客户端）
- `.action_dim` / `.action_horizon`: property → int
- `.infer(observation, *, noise=None) -> dict`：保证 `actions`（float32 `[H, dim]`，**非归一化域**）与 `timing`（至少 `model_ms` / `total_ms`）；pi05 家族惯例附 `normalized_actions`
- `.close()`
- 可选 `ComposablePolicy.with_adapter(before=, after=)`：robot 层的 pre/post 步骤包装（franka 的 EEF 转换等）

`apxinf_robo/engine.py` 是**全仓唯一 import apxinf 的模块**（docstring 明说"对特定引擎构建的依赖是单文件"）。`build_robot_policy` → preset.builder → `load_policy` → `apxinf.AutoPolicy.from_pretrained`。

### LeRobot 侧（要包装的）

ModelZoo pi05_lerobot 路线的调用形态（`infer.py`）：

```python
policy = PI05Policy.from_pretrained(path).to(device="npu").eval()
preprocess, postprocess = make_pre_post_processors(
    policy.config, model_id,
    preprocessor_overrides={"device_processor": {"device": "npu"},
                            "tokenizer_processor": {"tokenizer_name": tokenizer_path}})
batch = preprocess(frame)              # frame: lerobot 数据集样本 dict
pred = policy.select_action(batch)     # 归一化域 action chunk
actions = postprocess(pred)            # 非归一化域
```

NPU 优化在 lerobot_diff.patch（317 行，4 文件，主要 modeling_pi05.py）：FP16、NZ、npu_rotary_mul、TorchAir。另：`torch_npu.npu.set_compile_mode(jit_compile=False)`。

## 设计

### 新模块 `src/apxinf_robo/npu_torch.py`（唯一动引擎选择的地方）

```
build_robot_policy(..., engine="npu-torch")
        │
        ├─ engine="apxinf"（默认）→ 原 load_policy 路径（Rust 引擎，不动）
        └─ engine="npu-torch"    → NpuTorchPi05Policy(model_dir, wire_keys…)
```

`NpuTorchPi05Policy` 职责：

1. **加载**：`PI05Policy.from_pretrained` → `.to("npu", torch.float16).eval()`；`make_pre_post_processors`（tokenizer 路径参数化）
2. **键映射**：wire keys（`observation/image` 等，来自 preset/用户参数）→ checkpoint 的 input feature 名（权重 config 决定，加载后读取）。构造 lerobot 风格 frame dict
3. **infer**：frame → preprocess → `select_action` → postprocess → numpy float32；`model_ms` 计时包 `select_action`（NPU 同步后），`total_ms` 包全程
4. **metadata**：镜像 apxinf_pi05 的键（`image_keys`/`state_key`/`prompt_key`/`action_dim`/`action_horizon`…）+ `engine: "npu-torch"`
5. **close**：释放模型

### 与 with_adapter 的关系（阶段一先不做）

franka preset 的 robot steps 走 `ComposablePolicy.with_adapter`。若 LeRobot 包装不支持，franka_libero 的 LIBERO 键恰好直通（libero 微调权重的 feature 名与 wire 键一致），先覆盖直通场景；with_adapter 后补。

## 已知限制（阶段一）

- `noise=` 参数：LeRobot 策略内部自采样，精确注入暂不支持（parity 测试需要它，先跳过；记录到 roadmap）
- 精度：FP16（ModelZoo 同款）；`precision=` 参数接受 `fp16`/`auto`
- checkpoint 格式：LeRobot 格式（modelscope `lerobot/pi05_libero_finetuned`）；apxinf 原生支持的 openpi 格式走 jax→torch 转换，阶段一不做

## 已验证（2026-09-16 → 09-17 更新）

- 权重 config input features：`observation.images.image`(256²) + `image2`(256²) + `empty_camera_0`(224² 占位) + `observation.state`(8)；action 7 维、chunk_size 50
- lerobot_diff.patch 在 torch 2.9.0 + torch_npu 2.9.0.post1 + CANN 8.5.1 下**干净应用**（torch 钉版需改 lerobot pyproject，见 setup.md）
- **基线复现**：合成帧 P50 = 375.8ms（ModelZoo 官报 375ms）
- **端到端**：`build_robot_policy(engine="npu-torch")` → `infer(wire obs)` → `(50,7) float32`，稳态 model_ms 378 / total_ms 395
- 实测修正（已写进实现）：帧需 CHW+batch 维；加载后 `gradient_checkpointing_disable() + eval()`；transformers 修复分支的 `warning_once` 用本仓猴子补丁消音（`_SilentLogger`）

## 关键设计决策（2026-09-17 补）

1. **图像归一化域（血的教训）**：wire uint8 → 帧构造时必须 `/255` 转 float [0,1]（LeRobot 评测链语义；NPU 补丁的 `img*2-1` 假设此域）。uint8 直喂产生 [-1,509] OOD，形状全对但行为崩坏——所有对拍"等价"因两边同错而成立，骗过 8 小时排查
2. **两种执行语义**：`infer()`（返回整 chunk，replan 模式）与 `infer_step()`（官方 select_action 队列语义，每步一动作）——eval-libero 用 `--replan-steps 0` 选后者
3. **state 宽度硬校验**：8 维直通、7 维明确报错（不可恢复信息，不猜测转换）
4. **empty_camera 占位键必须缺省，不能补零图（2026-09-17 根因）**：`PI05Policy._preprocess_images` 对 missing visual 键生成全 -1 占位图 + **mask=0**（该相机从 cross-attention 中剔除——训练语义）；若喂显式零图则 **mask=1**，黑图的 siglip embedding 作为有效 token 污染每步 conditioning（数值上零图×2-1 恰好也是全 -1，故逐字段对拍全绿也发现不了——分岔只在 mask）。`_to_frame` 修复为不补 `_empty_features` 键，让模型走 missing 路径
5. **episode 边界必须 reset 策略内部队列（2026-09-17 根因 2）**：`select_action` 的 `_action_queue` 跨集存活，不 reset 则每集开头执行上集尾部最多 49 个陈旧动作。`NpuTorchPi05Policy.reset()` + `run_episode` 集开始处鸭子式调用；`warmup()` 走 `infer`/`predict_action_chunk` 不碰队列故无污染。两修复后 **9/10 = 官方 `lerobot_eval` 同日实测**

## 当前未结 → 已结案（2026-09-17）

~~libero_object 成功率 0/10 vs 官方 9/10~~ → 双根因修复（empty_camera mask + 跨集 queue reset，见关键设计决策 4/5）后 **9/10**，与官方 `lerobot_eval` 原样跑（同日 chip6）的 9/10 持平，失败集不同（我 task 7 / 官方 task 5）证明残余 1/10 为采样随机性。后续：replan 1/5/50 重测、阶段 2 启动。
