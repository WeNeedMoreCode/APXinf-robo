# 实测案例：Diffusion-Planner 闭环仿真五轮优化（615 → 86.6ms）

> 环境：华为 310P3 NPU，torchair 7.2 / CANN 8.3RC1 / torch 2.1.0，nuPlan 闭环仿真
> （one_continuous_log，5 场景，单线程独占卡，warm 中位，745 步/轮）。
> 项目背景：DiT 扩散规划模型（10 步 DPM-Solver++ 采样）+ nuPlan-devkit 数据管线。
> 本文件是 SKILL.md 各模式的出处与证据，按时间顺序。

## 全链路总账

| 轮次 | 改动 | total (ms) | 单轮收益 | 累计 |
|---|---|---|---|---|
| 起点 | 闭环跑通形态 | 615 | — | — |
| R1 | jit 编译窗口关闭 | 552 | -63 | -10.2% |
| R2 | CPU 地图处理向量化 | 417 | -135 | -32.2% |
| R3 | route 编码外提 + DiT body TorchAir 图化 | 267.6 | -149 | -56.5% |
| R4 | CPU 侧缓存 + 向量化（折线缓存/批量插值/agents） | 141.1 | -126.5 | -77.1% |
| R5 | fast 采样器 + encoder 图化 + cache_compile | 86.6 | -54.5 | -85.9% |

精度：5 场景 final_score 全程 0.9941~0.994266（波动 ≤0.0002），无回归。

## 关键结构事实

- **瓶颈分侧**（模式 1 出处）：起点 615ms 中 NPU forward 仅 ~70ms，CPU 前后处理
  ~500ms。R1~R4 优化 CPU 侧（-474ms），R5 才轮到 NPU 侧（-54.5ms）。
- **异步计时**：NPU 上不同步就读时钟，各阶段时间互相串——阶段计时必须
  `torch.npu.synchronize()` 包住。

## 各轮要点

### R2/R4：CPU 侧（模式 4 出处）

- **小数组×高频调用**：270 次单线插值（每次 ~15 个 numpy 算子，~几 μs 调度开销/
  算子与数组大小无关）→ ragged 批量（3 次大数组调用，span 偏移保持全局单调，
  一次 searchsorted 服务所有线）。mapproc 82→9.6ms。
- **纯函数缓存**：地图折线（`discrete_path` 是地图不变量）按 key 缓存转换结果。
  严格等价（纯函数同 key 同值）。mapquery 60→14.6ms，p90 550→19.1ms（长尾消灭）。
- **对象属性访问 floor**：CPU 侧最后剩 18.8ms 是 devkit 对象 `__slots__` 属性读取
  （11 帧 × ~50 agent × 7 字段），不重写上游库压不动——知道何时停手也是结论。

### R3：TorchAir 图化 + 外提（模式 2 出处，图侧细节见本 skill 的 NPU 后端 backends/npu）

- DiT body（静态 shape 主体）torchair 编译：fwd 176→71ms（单进程首编 ~31s）。
- RouteEncoder（含布尔散回，图不支持）外提到采样循环外：每步省 10 次重算
  （~3.5ms × 10）。

### R5：fast 采样器（模式 3 出处）

- 系数预计算：dpm_solver 每步 ~30 个设备小标量算子 × 11 NFE → CPU 一次预计算
  Python float。用上游 NoiseScheduleVP 类跑同公式链（不自己重抄公式）。
- 包装互逆消除：x_start + dpmsolver++ 的 noise_pred→data_pred 包装数学恒等抵消；
  浮点往返被 1/α(t≈1)≈240 放大，消掉更精确。
- attn_mask（循环不变量）预构造（模式 2）。
- 实测 fwd 70.2→43.0ms（-27.2，超出预估 ~15ms——通用实现的包装 op 比火焰图
  可见的更多）。
- 对拍：固定 seed 同 xT，4 个真实输入，max 相对 diff 1.7e-4~9.0e-4；归因落到
  1/α 放大机制（若公式错 diff 会是 O(1)）；端到端 score 无回归。

### R5：encoder 静态化（NPU 后端 backends/npu 的"全量计算+mask 置零"模式出处）

- 三个子编码器的 `x[valid_indices]` 布尔散回（动态 shape，图不支持）→ 全量静态
  计算 + 输出乘 valid mask 置零。行独立模块 → 有效行 bit-exact；对拍 4 输入全部
  逐位相同（20544/20544）。
- fwd 43.0→22.4ms（-20.6）。E2E score 无回归。

### R5：cache_compile（NPU 后端 backends/npu 出处）

- `torchair.inference.cache_compile` 替代 `torch.compile`：编译产物落盘，多 worker
  共享；首步 74s→35s；意外收获 warm 每步 fwd 22.4→18.5ms（无 dynamo guard）。

## 验证体系（模式 5 出处）

每轮三件套：固定 seed 对拍（分层判定 + 机制归因）→ 5 场景 score 锚点 → 阶段计时
对照。E2E 数值容忍度锚：图编译单步差 3e-2 端到端无回归（R3 实测）——比它小的重写
差基本安全。
