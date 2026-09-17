# 2026-09-16（深夜）：两个异常的根因排查（全部结案）

> 用户指令：问题 1 查 device 占用否则插桩；问题 2 查清原因。三层标注按惯例。

## 问题 1：LIBERO 单步 1378ms vs bench 376ms —— ✅ 已解决

### 事实结果（排查路径）

1. device 占用排除：diag 四相实验（合成无仿真 / 真实 obs 变化 state / 真实 obs 固定 / 关仿真）全部 ~388-392ms，AICore 快照显示无邻居挤占
2. 插桩（`APXINF_NPU_TIMING=1` 逐次打印 model_ms）：**104 次调用中 103 次 ~380ms，首次 100,185ms**（TorchAir 图编译）
3. 真相：**(100185 + 103×381)/104 ≈ 1339ms ≈ 实测均值 1384ms** —— 平均值陷阱。eval 无 warmup，一次性编译被摊进均值。bench 有 warmup 所以只见 380
4. 修复：`NpuTorchPi05Policy.warmup()`（zeros obs 预热编译）+ eval-libero npu-torch 分支加载后调用
5. 验证：5 集 eval 的 per_call_ms **model_ms 374.9ms** ✓

### 推测（未严格证明）

无。数字直接闭合。

## 问题 2：LIBERO smoke success 0/1 —— ✅ 根因查清（非 harness bug）

### 事实结果（证据链，按排查顺序）

1. state 约定修复：官方 `LiberoProcessorStep` 是 `pos(3)+axis-angle(3)+双指qpos(2)` 8 维（不是 quat），已实现 `libero_state_lerobot` 并接入 eval。**修复后仍 0/5**
2. **输入字节级对照**（同帧，官方链 vs 我们链，过同一 preprocess）：图像×2 / state / tokens **全部完全一致**（中途发现自己对照脚本的图像翻转 bug，修正后全等）
3. **推理输出对拍**（同 policy 同帧同噪声，官方 select_action vs 我们 predict_action_chunk+postprocess）：前 6 维差 ≤1.1e-3（NPU ulp 级），gripper 差 8.8e-3（小量级）
4. 执行协议对照：replan=5（0/5 败）与 replan=50（0/2 败，官方 n_action_steps=50）都失败；use_delta 默认即 true（robosuite osc_pose.json `control_delta: true`）；init_states/settle 步/步数上限我们的 harness 本来就与官方一致
5. **决定性对照：官方 eval 链跑 libero_10 → 同样 0%**（多集全败）；而同链 libero_object 100%（此前对照）

### 结论

**`lerobot/pi05_libero_finetuned` 权重在 libero_10 上就是不行，官方链同样失败。** 我们的 npu-torch 链从输入（字节级）到输出（ulp 级）与官方完全对齐，阶段一工程正确。ModelZoo 精度声明只覆盖 libero_object（100%）；APXinf README 的 92.4% 是 openpi 的 `pi05_libero_base`（不同权重）。

### 后续可选（如果需要 libero_10 精度数字）

- 换 openpi 格式权重（走 pi05_openpi 路线 + jax→torch 转换）或找 HuggingFaceVLA/libero-10 微调版
- 或阶段一验收口径改为 libero_object（ModelZoo 同口径）

## 工程产物

- `npu_torch.py`：+`warmup()`、+`APXINF_NPU_TIMING` 插桩、state 宽度硬校验（明确报错取代错误转换）
- `envs/libero.py`：+`libero_state_lerobot`（8 维官方约定）
- `cli/eval_libero.py`：state 构造按 engine 分叉、npu-torch 加载后 warmup
- 诊断脚本（本地档）：`diag_slow.py`、`compare_inputs.py`、`compare_actions.py`

## 经验（踩坑追加）

- numpy 负 stride 视图（`[::-1,::-1]`）喂 torch 会炸/需 ascontiguousarray——修了两次才记住
- 评测均值会撒谎：无 warmup 的一次性编译（100s）摊进 104 次平均变成"每步慢 1 秒"的假象。看分布不看均值
- 对照实验要同任务：libero_object 的 100% 不能外推到 libero_10
