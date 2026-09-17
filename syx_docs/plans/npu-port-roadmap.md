# 昇腾 NPU 移植 roadmap（跨 session 计划）

> 路线决策见 [decisions/001](../decisions/001-hybrid-route-with-native-seam.md)：混合路线 + 预留原生接口，硬件锁定 310P3。

## 阶段 0：环境与基线（✅ 2026-09-16 完成）

- [x] 连接远程服务器（root@192.168.13.119，8×310P3，共享机）
- [x] 摸清容器/镜像资源（MindIE 3.0.0、CANN 8.3/9.0.1、vllm-ascend）
- [x] 读取 ModelZoo pi05_openpi 适配文档（torch_npu + TorchAir，FP16，378ms）
- [x] 选定路线：pi05_lerobot（权重在 ModelScope 国内直连，免去 openpi jax→torch 转换）；容器 `apxinf_npu`（复用 MindIE torch2.9 镜像，torch_npu 2.9.0.post1 + CANN 8.5.1）
- [x] π0.5 checkpoint 到位：`/data/apxinf/weights/pi05_libero_finetuned`（7.0G，LeRobot 格式）+ `paligemma-3b-pt-224`（11G）
- [x] ModelZoo NPU 补丁分析归档（references/modelzoo-pi05-npu-adaptation.md）
- [x] **基线复现：合成帧 smoke 测试 P50 = 375.8ms**（ModelZoo 官报 375ms，chip 5，FP16，chunk 50×7；加载 175s + TorchAir 首编 123s 均一次性）。日志 `/data/apxinf/smoke.log`，脚本 `smoke_pi05_npu.py`
- 过程中解决的坑（详见 setup.md「依赖安装坑」+「容器内 transformers 补丁」）：torch 钉版连锁降级、gh-proxy git+ 前缀、numpy 2.x 破坏 pandas、batch 维缺失、CHW 布局、gemma warning_once 破坏图编译

## 阶段 1：torch_npu 后端接入 apxinf_robo API（✅ 2026-09-16 全部完成）

- [x] 读透 `src/`（apxinf_robo Python 层）：`engine.py` 是全仓唯一引擎依赖点，`Policy` 是结构化 Protocol（鸭子类型）
- [x] 引擎缝实现：`load_policy(engine="npu-torch")` 单点路由（engine.py +14 行），`NpuTorchPi05Policy` 新模块（wire HWC→CHW 转换、空相机零填充、eval+gradient_checkpointing_disable、模型侧 feature 名自动发现）
- [x] **端到端验证**：`build_robot_policy("franka_libero", ckpt, engine="npu-torch")` → `infer(obs)` → `actions (50,7) float32`；稳态 model_ms 378 / total_ms 395（chip 5）。日志 `/data/apxinf/e2e.log`
- [x] **bench 接入**：`scripts/bench_pi05_npu.py`（独立脚本，不硬塞 Rust 引擎版；L2 语义 warmup/samples/P50/JSON）。实测 model_ms P50 376.4 / total_ms P50 383.8，P90 仅 +2ms。产物 `/data/apxinf/bench_npu.json`
- [x] **CLI `--engine` 暴露**：`serve`（npu-torch 分支跳过 Rust 引擎 preflight，fp16-only 校验，拒 random-weights）与 `eval-libero`（选项过滤）都支持 `--engine npu-torch`，`--precision` 增 fp16
- [x] **L3 websocket**：`apxinf-robo serve --engine npu-torch` 起服务（8199 端口），最小 msgpack 客户端验证 metadata 下发 + actions 回传；稳态 infer_ms 384 / policy_ms 409。坑：首请求触发编译期间服务端无法应答 ws ping → 客户端 `ping_interval=None`
- [x] **noise= 精确注入**：临时替换 `model.sample_noise`（零填充到模型内部 32 维 padded 动作空间），finally 恢复。验证：同 noise 两次 max diff = 2^-10（1 个 fp16 ulp，aclnn 算子调度非确定性——**不保证 bitwise**），异 noise 分岔 0.25；horizon 形状护栏生效
- [x] **LIBERO smoke**：`eval-libero --backend in-process --engine npu-torch` 全链路：EGL 离屏渲染 + 520 步回放 + 104 replan + summary JSON 落盘。**success=False（0/1，单次无统计意义）**；**model_ms 1378（bench 的 3.7 倍，异常）**
- [x] **状态约定适配**：LIBERO wire 7 维（pos+axisangle+grip，openpi 约定）↔ LeRobot checkpoint 8 维（pos+quat+grip）——包装层 `_axis_angle_to_quat` 展开
- [x] **transformers 兼容改猴子补丁**（本仓实现，不动容器文件）：`_SilentLogger` 替换 gemma/siglip 模块 logger，dynamo 可追踪；已还原容器文件并实测验证
- 容器供给清单（pip/apt/libero 配置/资产）见 setup.md「容器内追加安装清单」

### 成功率问题：全链结案（2026-09-17 同日）

演进：**0/10 →（empty_camera mask 修复）→ 4/10 →（跨集 action queue reset 修复）→ 9/10 = 官方 `lerobot_eval` 同日同协议实测 9/10**（我们失败 task 7、官方失败 task 5——失败集不同证明残余 1/10 为 flow 采样随机性，非实现差异；口径已对齐：同 init[0]、同判定源）。两个根因与修复细节见 summary/2026-09-17_empty-camera-mask-root-cause.md（含追记）。

### 遗留待查 → 已全部结案

1. ~~**LIBERO 单步 1378ms vs bench 376ms**~~ → **均值陷阱**（2026-09-16）：无 warmup，首次 TorchAir 编译 100s 摊进平均；修复 `warmup()`，per_call 374.9ms ✓
2. ~~LIBERO success 0/N~~ → **根因：图像 uint8 [0,255] 直喂 LeRobot 链（期望 [0,1] float）→ siglip 归一化后 [-1,509] OOD**（2026-09-17 凌晨，summary/2026-09-17_libero-object-success-hunt.md）。修复 `_to_frame` /255 后 **libero_object task 0 成功（217 步，1/3）**——阶段一验收达成
3. websocket 服务端单线程阻塞——warmup 后基本消解

### 新遗留（2026-09-17 统计更新后 → 同日根因结案）

**核心未结 → 已结案**：libero_object 0/10 vs 官方 9/10 的根因是 **empty_camera_0 零图填充**——`_to_frame` 给占位相机补了零图，使 `PI05Policy._preprocess_images` 走 present 路径（mask=1，黑图 siglip embedding 参与 cross-attention）而非官方 missing 路径（全 -1 占位 + mask=0，相机被剔除）。零图×2-1 数值上恰为全 -1，与官方占位图逐像素相同——**分岔只在 mask 位**，故此前所有逐字段对拍全绿。修复：`_to_frame` 不补 `_empty_features` 键。

**定位方法（零 NPU 最小化对拍，`translate_parity_zero_npu.py`）**：单帧评测帧（reset+settle 后 t=0）双路径构造 batch——官方链（`LiberoProcessorStep` + preprocess，mini_official.py 语义）vs 我们链（`libero_images`/`libero_state_lerobot`/`_to_frame` + preprocess），frame/batch 两层逐字段 diff。单次 ~40s、全程 CPU 无模型加载，取代整集 NPU 跑（3min 加载 + 编译 + 1min/集）。图像 0.0 差（翻转/归一化全对）、state 3e-8、tokens 0.0、task 字符串全同、**唯一分岔 = empty_camera_0 键存在性**。

**顺带排除的嫌疑**：图像 180° 翻转（两侧都有：官方 `LiberoProcessorStep` flip dims=[2,3]，我们 `libero_images` [::-1,::-1]）；env 初始化（两侧同为 reset → set_init_state → 10 步 settle[-1]、seed=7）；quat→axisangle（公式同、float64 vs float32 差 7e-9）；调度语义（两侧同为 `policy.select_action` 同一函数）。

**官方协议复测**（10 任务 × init[0]，replan=0，chip5，`/data/apxinf/mask_fix_eval.log` + `summary_mask_fix.json`）：**4/10**（task 0=143 步/1=123/5=175/8=276 成功），修复前 0/10——mask 根因坐实。**残余差距 4/10 vs 官方 9/10 待查**，下一步候选：核对官方 9/10 当次的确切条件（init/seed/成功判定——官方为视频帧数判定 vs 我们 env.check_success 接触判定；判定口径本身可能贡献差距）、flow steps/超参、以及失败集（2/3/4/6/7/9，全部 520 步打满）的行为 trace。

**其他待办 → 已收尾（2026-09-17 晚，阶段 1 全部完成）**：

- **replan 1/5/50 重测**（10 任务 × init[0]，chips 5/6/7 并行）：replan=0 → **9/10**（挂 task 7）；replan=1 → **8/10**（挂 task 4、9；每步重采样噪声暴露最大）；replan=5 → **9/10**（挂 task 6）；replan=50 → **10/10**。四种配置失败任务各不相同且 ≤2——与"残余失败为采样随机性"结论一致；旧注释"该 checkpoint 对 noise 重采样敏感"系污染数据误报，已从代码删除
- **bench 复测**：model_ms P50 376.0 / P90 378.3（修复前 376.4/378+）——不变，确认两处修复不动热路径；warmup 104.9s 单列未污染样本（`bench_npu_refix.json`）
- **websocket ping 生产化**：`serve --engine npu-torch` 加载后、监听前调 `warmup()`（编译前置）；实测日志顺序 `warming up` → 98s → `server listening`，客户端首请求 infer_ms **381**（稳态，非 100s+ 编译），loop 最长阻塞 ~0.4s << ping 超时，客户端无需再设 `ping_interval=None`

## 阶段 2：Rust 原生 apxinf-ascend（逐个过相异点）

- [x] **工具链 + FFI 地基验证（2026-09-17 晚，M2 第一腿）**：容器 `apt install cargo`（1.75.0，够用）；手写 ACL FFI 冒烟 crate `/data/apxinf/ascend_smoke/`（本地镜像 `syx_docs/dev_logs/ascend_smoke/`，**无 bindgen/clang 依赖**——签名直接抄 acl_rt.h）通过：`cargo build` 链接 `libascendcl.so`（build.rs 里 link-search=/usr/local/Ascend/ascend-toolkit/latest/lib64）+ aclInit→SetDevice→Malloc→H2D/D2H 往返（4096 字节 0 错）→Free→Finalize 全 ret=0。运行需 `LD_LIBRARY_PATH` 带 CANN lib64 + `ASCEND_RT_VISIBLE_DEVICES` 挑芯。分派缝形态已摸清（`apxinf-model/src/accelerator.rs`：`Device::Cuda(id)` + `#[cfg(feature)] mod`，ascend 同构接入）
- [ ] ACL FFI 骨架：context / stream / device memory（aclrt*）——冒烟已证核心 API，骨架做成 `apxinf-ascend` crate 正式化
- [ ] `Device::Ascend(usize)` 枚举 + `accelerator.rs` 分派缝扩展 + cargo feature `ascend`（**注意：动的是 apxinf/ 子模块=上游仓 infinigence/ApxInf，需定分支策略**）
- [ ] `Backend` trait 最小集：matmul（aclnnMatmul）、rms_norm、silu、add/mul/scale、embedding、rope
- [ ] sdpa（aclnnFusionAttention，310P3 覆盖验证）+ KV cache
- [ ] PI0.5 FP16 executor：CUDA 融合 kernel 先拆基础算子跑通，再热点融合
- [ ] graph capture 等价物（先 no-op + synchronize，后 host 录制回放）
- [ ] PyO3 绑定接入阶段一的引擎抽象缝
- [ ] 验收：random-weights bench → checkpoint bench → LIBERO（对标阶段一基线）

## 技术相异点清单（一个一个过）

| # | 相异点 | CUDA 侧 | NPU 侧候选 | 风险 |
|---|---|---|---|---|
| 1 | GEMM | cuBLAS/CUTLASS（bf16/fp8/w8a8） | aclnnMatmul + FRACTAL_NZ 权重布局 | NZ 转换时机（load 时 vs 首算） |
| 2 | Attention | FMHA/FA | aclnnFusionAttention | 310P3 支持的头数/head_dim 组合待验证 |
| 3 | 融合 kernel | ada_gate_residual_rms_norm / qkv_rope / euler_update 等 | 拆基础算子 → AscendC 自研 | 性能差距主要来源 |
| 4 | 图捕获 | CUDA Graph | 无直接等价 | host 录制回放的语义正确性 |
| 5 | 精度 | BF16/FP8/INT8 | FP16/INT8 | FP16 溢出风险（norm 前 probe） |
| 6 | RoPE | 自研 kernel | aclnnRotaryMul（= npu_rotary_mul） | qkv_rope 融合形态 |
| 7 | 采样/flow steps | device 侧 | 基础算子序列 | 延迟占比小，后置 |

## 里程碑与验收

- M1（阶段一完成）：`build_robot_policy(..., engine="npu-torch")` 可用，bench 出延迟数字，精度对齐 ModelZoo
- M2（阶段二最小）：`apxinf_py` 以 `--features ascend` 构建成功，random-weights bench 在 310P3 跑通
- M3：NPU-native 路径 LIBERO 成功率 ≥ torch_npu 路径 - 1pp，延迟目标对标 378ms 基线（争取显著优于此）
