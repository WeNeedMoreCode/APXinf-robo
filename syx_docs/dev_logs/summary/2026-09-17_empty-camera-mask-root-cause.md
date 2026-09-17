# 2026-09-17：libero_object 0/10 根因结案——empty_camera 零图填充污染 cross-attention

## 问题

修复图像归一化 bug 后，输入链/单帧推理对拍全绿，但闭环成功率仍 0/10（官方同日 9/10，协议：10 任务 × init[0]）。

## 定位方法：零 NPU 最小化双路径对拍（用户指定方向）

不再整集跑 NPU（3min 模型加载 + 100s 编译 + 1min/集），改单帧双路径对拍：

- 脚本：`translate_parity_zero_npu.py`（本地镜像 `syx_docs/dev_logs/`）
- 一帧真实评测帧（reset → set_init_state(init0) → 10 步 settle，seed=7）
- 路径 OFFICIAL：`off_obs → LiberoProcessorStep._process_observation → preprocess`（mini_official.py = lerobot 官方 eval 语义）
- 路径 OURS：`libero_images + libero_state_lerobot → NpuTorchPi05Policy._to_frame → preprocess`（eval_libero.py 实际链路；实例用 `object.__new__` 绕过权重加载，config 走 `PreTrainedConfig.from_pretrained`）
- frame / batch 两层逐字段 diff，~40s/次，全程 CPU

## 根因

`_to_frame` 给占位相机（`empty_camera_0`，checkpoint 声明但无 wire 键）补了**零图**。`PI05Policy._preprocess_images`（lerobot `modeling_pi05.py` ~1180）的语义：

- **missing 键（官方链）**：占位图 = 全 -1（"Padded with -1 for SigLIP"），**mask = 0** → 该相机的 embedding token 在 attention 掩码中被剔除——训练语义
- **present 键（我们链）**：正常编码，**mask = 1**

零图 ×2-1 后恰好也是全 -1——**图像数值与官方占位逐像素相同，分岔只在 mask 位**。mask=1 时黑图的 siglip embedding 作为有效 token 进入 PaliGemma cross-attention，每步推理的 conditioning 都被污染 → 系统性行为偏移 → 0/10。同时解释了为何所有逐字段对拍全绿：两边喂给模型的张量数值一致，行为差异藏在 mask 这个"非数值字段"里。

## 修复

`src/apxinf_robo/npu_torch.py` `_to_frame`：删除 `_empty_features` 零图填充（`frame[feature] = np.zeros_like(first)` 段），batch 故意缺键，走模型 missing 路径。docstring 记录原因。

## 验证

1. 零 NPU 对拍复跑：batch 键集一致，全字段 0 差（图像 0.0、state 2.98e-8、tokens 0.0、task 字符串全同）✓
2. 官方协议闭环复测（10 任务 × init[0]，replan=0，chip5，`/data/apxinf/mask_fix_eval.log` + `summary_mask_fix.json`）：**4/10**（成功集 task 0=143 步 / 1=123 / 5=175 / 8=276；失败集 2/3/4/6/7/9 全部 520 步打满），修复前 0/10——根因坐实

## 追记：残余 4/10 差距同日结案——跨集 action queue 污染

mask 修复后 4/10 vs 官方 9/10，继续对拍失败集（2/3/4/6/7/9），第二处实现 bug：

**根因 2**：`select_action` 的内部 `_action_queue` 挂在 policy 实例上、跨集存活（`modeling_pi05.py:1236-1241` 只在队列耗尽时重规划）；官方 eval 每集 `policy.reset()`（1145-1147 清队列），我们 `run_episode` 从不调 → 每集开头执行上一集尾部最多 49 个陈旧动作。旁证：reset 修复前成功恰是 task 0（首集队列干净）/1（前集 143 步结束仅残留 ~7 动作）。

**修复**：`NpuTorchPi05Policy.reset()` 新方法 + `run_episode` 集开始处鸭子式调用（`getattr(backend, "_step_policy")`，无 reset 的后端跳过）。`warmup()` 走 `infer`（`predict_action_chunk`）不碰队列，无污染。

**终局对拍（同日双链）**：

| 链路 | 成功率 | 失败任务 |
|---|---|---|
| 我们（mask+reset 修复后，chip5，25min） | **9/10** | task 7 |
| 官方 `lerobot.scripts.lerobot_eval` 原样（chip6，15min，`official_eval.log` + `official_eval_out/`） | **9/10**（pc_success=90.0） | **task 5** |

三嫌疑结案：**口径已对齐**（同 init[0]、同判定源 env reward/check_success）；**实现等价**（9=9，且双方失败集不同）；**残余 1/10 = 随机性**（flow 噪声采样非确定，官方链同样随机挂一个）。ModelZoo 声明 100% 可视为运气好的一次（p=0.9 单集时 10 连过概率 ~35%）。

演进全景：0/10 →（empty_camera mask 修复）→ 4/10 →（跨集 queue reset 修复）→ **9/10 = 官方同日实测**。

## 遗留（下一轮）

- 修复后的 replan 1/5/50 重测（旧数据全部作废）
- bench 复测（预计不变：两处修复都不动热路径）
- 成功率验收已达成，阶段 2（Rust apxinf-ascend）可启动

## 顺带排除的嫌疑（都是"看起来可疑但对拍排除"）

| 嫌疑 | 结论 |
|---|---|
| 图像 180° 翻转 | 两侧都有（官方 `flip dims=[2,3]` = 我们 `[::-1,::-1]`），归一后 maxdiff 0.0 |
| env 初始化序列 | 两侧同为 reset → set_init_state → 10 步 settle[-1]、seed=7 |
| quat→axisangle | 公式相同，float64 vs float32 差 7e-9 |
| 调度语义 | 两侧最终都调 `policy.select_action`（同一函数，同一队列逻辑） |

## 方法论沉淀

1. **对拍要拍"非数值字段"**：键存在性、mask、dtype——数值全等 ≠ 行为等价（本例分岔在一个 bool）
2. **对拍基准必须是被复刻链路的真实代码**（LiberoProcessorStep），不是"看起来等价"的另一条路（此前用数据集帧对拍 = 数据集域，漏掉了 env 域特有语义）
3. **零 NPU 单帧对拍**是翻译层的正确工具：40s 换一次全字段对照，比整集 NPU 快两个量级——"提前准备输入、最小化实验"的标准做法
