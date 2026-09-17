# 模型推理优化（设备无关）

> inference-delivery 的通用优化层：任何设备（CPU/NPU/GPU）通用的定位与优化模式。
> 设备特有的迁移与知识（当前为 NPU）在 [../backends/npu/README.md](../backends/npu/README.md)。

## 定位与边界

本层收**与加速器无关**的推理优化模式。设备特有的问题（算子缺失、图编译约束、
显存格式）→ [../backends/npu/README.md](../backends/npu/README.md)。

所有模式来自实测项目提炼（数字见 [references/diffusion-planner-case.md]），
不是理论清单——每个模式都有"什么时候不适用"。

---

## 模式 1：先分侧计时，再动手（最重要）

**为什么放第一**：加速器项目最常见的错觉是"瓶颈在模型 forward"。实测案例
（Diffusion-Planner，310P）：单步 615ms 中 NPU forward 仅 ~70ms，CPU 前后处理
（数据处理/地图查询/张量组装）占 500ms+。先优化哪一侧由数据决定，不由直觉决定。

**怎么做**：

1. **阶段计时**：在 pipeline 的天然边界（预处理 → 归一化 → forward → 后处理）插计时。
   异步设备（NPU/GPU）**必须先 synchronize 再读时钟**——否则读到的是上一次同步点，
   各阶段时间会互相串。
   ```python
   torch.npu.synchronize(); t0 = time.perf_counter()   # npu/cuda 同理
   ... stage A ...
   torch.npu.synchronize(); t1 = time.perf_counter()
   ```
2. **子块计时**：最大阶段内部再拆（环境变量开关控制打印，不改动逻辑）。
3. **CPU 侧火焰图**：段级定位之后往下拆函数级——采样命令、找 PID、speedscope.app
   三视图、离线聚合脚本与 self/total 读法见
   [references/profiling-pyspy.md](references/profiling-pyspy.md)
   （脚本在 [scripts/agg_speedscope.py](scripts/agg_speedscope.py)）。
4. **看 warm 中位，不看均值**：首步有编译/缓存冷启动（图编译可到分钟级），会污染
   均值；p90 看长尾是否与中位同源。

**陷阱**：
- 异步设备不同步就计时 → 数字无意义（方向性错误）
- 只看均值 → 冷启动掩盖真实稳态
- CPU 侧热点是"每次几微秒 × 上千次"的调度开销型（见模式 4 的识别方法），
  单看某个函数都很小，火焰图聚合才看得见

---

## 模式 2：循环不变量外提

**识别**：采样/自回归/滑窗循环体里，**不依赖循环变量**的任何计算。典型：attention
mask、context 编码、位置编码、系数表。

**案例数字**：DiT 采样循环内每步重算 RouteEncoder（~3.5ms × 10 步）和 attention
mask 构造，外提到循环前只算一次。

**做法**：把循环体收敛成"循环变量输入 → 输出"的纯函数，剩下的一切在循环外构造好
传进去。等价性是平凡的（同样的值从每步重算变成算一次），不需要对拍——但如果不变量
的构造本身依赖输入数据（如 mask），确认它整轮真不变（数据流上无循环内更新路径）。

---

## 模式 3：扩散采样器系数预计算 + 包装互逆消除

适用：DPM-Solver / DPM-Solver++ / DDIM 系采样循环，**采样超参固定**（steps、order、
skip_type、noise schedule）的部署场景。

**两个独立的优化点**：

### 3a. schedule 标量全部与输入无关 → 预计算

`marginal_lambda / marginal_std / expm1 / alpha_t` 这些标量只依赖 schedule 常量
（如 linear schedule 的 β₀ β₁）和步号——**与模型输入零关系**。通用实现每步在设备上
用小张量重算它们（~30 个小算子/步），全是调度开销。

做法：进程首次调用时**用上游的 NoiseScheduleVP 类在 CPU 上跑一遍同公式链**（保证
公式逐条同源，不是自己重抄），把 timesteps 和每步线性组合系数摘成 Python float
缓存。运行时循环只剩：一次线性组合（几个大张量 op）+ 约束 + 模型调用。

### 3b. 包装函数数学互逆 → 直接消掉

`model_type == "x_start"` + `algorithm_type == "dpmsolver++"` 时，dpm_solver 的
noise_pred → data_pred 双重包装在**数学上精确互逆**（代入可证恒等），但浮点上不抵消：
往返两次除法/乘法的舍入被 `1/α(t)` 放大——t 大时 α(t)≈0.004，放大约 240 倍。
消掉包装既省 op 又**更精确**。

**对拍预期**：新旧采样器固定 seed 对拍，diff 落在 1e-4 相对量级（系数结合顺序不同 +
上游包装的放大舍入），不是 ulp 级。若 diff 到 O(1) 说明公式抄错（两条路径解的是
不同 ODE）。

**前置条件**：guidance 必须是 uncond（classifier-free/classifier 路径没有上述互逆）；
steps/order/skip_type 改了要重预计算（cache key 里带上）。

---

## 模式 4：热路径常量张量缓存

**识别**：profile 里成串的小拷贝/小算子；代码里推理循环内的 `constant.to(device)`、
`torch.tensor([...])`、CPU 常量的重复构造。每个 `.to(device)` 是一次宿主→设备同步
拷贝（~几十微秒），常量每步搬一次纯属浪费。

**做法**：按 device 缓存搬运结果：
```python
def _stats_for(self, device):
    cached = self._device_cache.get(device)
    if cached is None:
        cached = build_on(device)          # 一次性搬运/构造
        self._device_cache[device] = cached
    return cached
```

同类问题更大的一层：**小数组 × 高频调用**（CPU 侧）。单个算子几微秒的调度开销与
数组大小无关，几百次小调用就是几毫秒起步——批量化成少数大数组调用（一次
searchsorted 服务所有线、fancy scatter 替代逐行赋值）。等价性靠"每元素数学同式"
论证 + 对拍。

---

## 模式 5：等价性对拍（每轮优化的安全网）

任何"数学等价"的重写，**先对拍再上端到端**。三层验证：

1. **固定 seed 对拍**：同输入（最好用真实捕获的输入，不用随机合成）、同 seed
   （让随机起点一致），新旧实现输出逐位比。
   - 判定分层：bit-exact（最强，如静态化重写）→ ulp 级（结合顺序变化）→
     1e-4 相对级（如采样器重写，见模式 3）
   - diff 超预期时**归因要落到机制**（如"上游包装被 1/α 放大"），不能停在"差值
     可接受"——不落机制的差值无法判断是等价路径的舍入还是公式错误
2. **端到端指标锚点**：固定小场景集跑 score/精度，与优化前锚点比。数值差的容忍度
   以端到端为准：实测图编译单步 3e-2 差端到端无回归，比它小的重写差基本安全。
3. **变体覆盖**：对拍输入要覆盖边界情况（全零行/空集/退化输入），只拿典型输入对拍
   会漏掉无效输入路径的错误。

---

## 何时不用这个 skill

- **训练吞吐**优化（梯度累积/并行/混希是另一套知识）
- 设备特有故障（算子缺失报错、图编译失败 → 本 skill 的 backends/npu）
- 还没跑通的项目（先迁移，再优化——顺序反了会同时面对两类问题）

## 实测案例

- [references/diffusion-planner-case.md](references/diffusion-planner-case.md) —
  闭环仿真推理五轮优化 615→86.6ms（-85.9%）全链路：每轮改了什么、数字、精度无回归
  的验证方式。本 skill 各模式的出处。
