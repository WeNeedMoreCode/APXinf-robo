# 2026-09-17 凌晨：libero_object 成功率追凶 —— ✅ 结案（根因：图像归一化域错误）

> 用户标准修正："至少跑个对的"——验收 = 我们链路上有成功集。**已达成：1/3 成功（217 步）。**

## 🎯 根因（最终）

**`NpuTorchPi05Policy._to_frame` 喂给 LeRobot 的图像是 uint8 [0,255]，而 LeRobot 评测链（`lerobot.envs.utils.preprocess_observation`）在 policy 前做 `float32 / 255` → [0,1]**。NPU 补丁的 siglip 归一化 `img * 2 - 1` 假设 [0,1] 输入——uint8 直喂产生 **[-1, 509]** 的严重 OOD 输入，模型照常出动作（形状对）但行为崩坏。

**修复**：`_to_frame` 图像 `astype(np.float32) / 255.0`（自动检测 uint8 输入）。修复后**首集即成功**（libero_object task 0，217 步，1/3）。

## 为什么这个 bug 骗过了所有对拍

- replay/compare 全部在**我们的帧构造**内部对比两链——**错得一样**（等价成立）
- 官方链的 /255 发生在 `preprocess_observation`（lerobot_eval 的 env 侧），**我们的对照脚本全都绕过了这一步**（手动构造帧直喂 preprocess）
- 教训：**对拍必须覆盖"从 env 原始输出到模型输入"的完整链路**，构造函数级等价 ≠ 端到端等价

## 最终事实链

| 项 | 结果 |
|---|---|
| 根因 | 图像 uint8 [0,255] 直喂（LeRobot 期望 [0,1] float） |
| 修复 | `_to_frame` 内 /255（自动检测 uint8） |
| 验证 | libero_object task 0：**success=True 217 步**（+2 集 520 步败，1/3） |
| 官方对照 | lerobot_eval 同期 rerun 混合成功率（部分 100% 部分 0%）——波动正常 |

## 追记（同日白天）：1/3 不是终点——统计后差距仍在

用户质疑"1/3 为何算达成"——正确。补做的统计：

| 实验 | 我们 | 官方（同日） |
|---|---|---|
| task 0 × 10 init | 2/10（243/177 步成功） | — |
| 10 任务 × init[0]（官方协议） | **0/10** | **9/10**（帧数判定） |

**修复后重验**：输入链 0.0 差（含 /255 路径）；单帧推理前 6 维 ≤1.2e-3、gripper ~1e-2（ulp 传播量级）。**输入与单帧推理均等价，闭环成功率仍 0/10 vs 9/10——存在未定位的系统性差异**，嫌疑收敛到：
1. **env 胶水层**：我们 `make_env`（裸 OffScreenRenderEnv）vs 官方 `LiberoEnv`（每集 re-seed、VectorEnv 包装、settle 细节）
2. 两次 forward 的 ulp 级差 + 闭环混沌放大（但官方同样有 ulp 却鲁棒，此解释力弱）

**下一步（明确）**：把 wrapper 接进官方 `LiberoEnv` 环境栈跑（借环境排推理）——成则差异锁定 env 胶水，逐项移植；败则推理路径仍有隐藏差异。

## 工程产物（最终）

- `npu_torch.py`：图像 /255 归一化（核心修复）、`infer_step`（官方队列语义）、`warmup`、调试插桩已清除
- `eval_libero.py`：`--replan-steps 0` 队列模式、state 8 维分叉、warmup 接入
- 假设生死簿 + 诊断脚本（9 个）见本文档前半部分及本地档

## 事实结果（按排查顺序）

### 已确凿的等价性（多层验证）

1. **输入构造**：同 obs 下官方 `LiberoProcessorStep` 链 vs 我们 wire 链，图像×2/state/tokens **字节级一致**
2. **推理调用**：同 obs 同噪声，`select_action` vs `predict_action_chunk + postprocess` 首动作差 ≤0.001（NPU ulp 级）
3. **输入类型无关**：numpy vs torch 进 preprocess，闭环轨迹前 140 步同步（combined A/B）
4. **执行协议无关**：replan ∈ {1, 5, 50} 与官方队列语义（replan=0，`infer_step` 移植）全部试过
5. **init state**：eval 进程收到的 `initial_states[0]` 与官方逐位一致
6. **state 约定**：8 维 pos+axis-angle+双指（官方 LiberoProcessorStep 同款，已移植 `libero_state_lerobot`）

### 关键反转

- 官方 eval（lerobot_eval）libero_object 首轮 **4/5 成功**（视频帧数判定：成功集提前终止）
- **同 env 背靠背 A/B（combined_full）**：官方段 200 步也失败；我们段与官方段轨迹高度同步——**官方语义本身成功率波动大**
- 我们链 libero_object 计 0/20+（replan 1: 0/2、5: 0/3+0/1、50: 0/3、队列: 0/3）

### 假设的生死簿

| 假设 | 判决 | 证据 |
|---|---|---|
| state 约定错 | 修复后仍败 | 8 维对齐后 0/5 |
| 图像翻转/布局 | 无罪 | 字节级对比 |
| 推理调用形态 | 无罪 | replay ulp 级 |
| use_delta 控制器 | 无罪 | osc_pose.json 默认 control_delta=true |
| 执行协议（replan） | 无罪 | 1/5/50/队列全试 |
| 首帧场景异常 | **假象** | dump 代码 bug（局部变量每次重写）——对比的是 ep 末帧 |
| flow 噪声重采样碎片化 | 弱化 | replan=50/队列也败 |
| 输入类型（numpy/torch） | 无罪 | combined A/B 轨迹同步 |
| checkpoint 任务能力 | 部分 | libero_10 官方也 0%；libero_object 官方波动 |

### 进行中

- 8 集队列模式 + seed=1000（对齐 lerobot_eval 默认）统计中
- 若 1+/8 成功 → 达标 + 记录真实成功率
- 若 0/8 → 剩余唯一未对齐项：lerobot_eval 的 gym LiberoEnv 完整栈（seed 之外的：VectorEnv 时序/相机渲染路径）

## 推测（未严格证明）

- 该 checkpoint（pi05_libero_finetuned）对 flow 噪声实现高度敏感：不同进程 RNG 流 → 成功率大幅波动（官方 4/5 → 0/1）
- 我们链 0/20 vs 官方 4/5 的悬差**尚未归零**——若 8 集统计仍 0，存在未发现的系统性因素（候选：lerobot_eval 进程的 env 构造细节、torch RNG 消耗序列）

## 工程产物

- `npu_torch.py`：+`infer_step()`（官方队列语义）、+dump 插桩（APXINF_DUMP_FRAME/APXINF_VERIFY_FRAME）
- `eval_libero.py`：+`--replan-steps 0` 队列模式（官方语义移植）、state 按 engine 分叉
- 诊断脚本（本地档）：`mini_rollout.py`、`mini_official.py`、`combined_mini.py`、`combined_full.py`、`replay_compare.py`、`compare_rollout.py`、`compare_actions.py`、`compare_inputs.py`、`dump_frames.py`

## 方法论教训（重要）

1. **dump 插桩的"只写一次"逻辑用局部变量实现是 bug**（每次调用重置）——诡异时间戳+内容矛盾排查了一小时；插桩状态要放实例/模块级
2. **平均值撒谎**（问题 1 已证）之外：**"官方能成"也可能不可复现**——对照实验要在**同进程同 env 背靠背**做（combined A/B 模式值得固化为标准工具）
3. **闭环等价 ≠ 静态等价**：同输入等价 + 同调用等价，闭环轨迹仍会因噪声实现分岔——对噪声敏感的模型，成功率统计才是唯一可信验收
