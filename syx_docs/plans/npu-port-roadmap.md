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
- [x] **ACL FFI 骨架（2026-09-17，commit 1c76783 @ fork/ascend-port）**：`apxinf-ascend` crate 正式化——手写 aclrt FFI（acl_base/acl_rt，无 bindgen）+ `AscendContext` RAII（OnceLock 幂等 aclInit + SetDevice/CreateContext/Drop 清理）+ `DeviceBuffer` RAII + h2d/d2h/synchronize。rlib 不最终链接 libascendcl（非 Ascend 机器可编译），example 真芯冒烟通过
- [x] **`Device::Ascend(usize)` 枚举 + 分派缝（同 commit）**：core 枚举/is_gpu/Display，model 分派缝 + auto + llama 全部穷举点带 "not wired yet" 臂，py 的 parse_device("ascend[:N]")。cargo feature `ascend` 的元包链待第一个 Backend 算子时挂
- [x] 子模块分支策略已定：fork `WeNeedMoreCode/ApxInf` 的 `ascend-port` 分支（外层 .gitmodules 已指向 fork），引擎改动两步走（子模块 push + 外层 bump gitlink，CLAUDE.md 有纪律）
- [x] 工具链（服务器）：Rust 1.85.0 @ /data/apxinf/rust（本地代理下载+传输；apt 1.75 是死路：lock v4 + MSRV）；crates.io 走 rsproxy sparse。详见 setup.md「Rust 工具链」
- [x] **CANN 9.0.1 工作容器 `apxinf_rust`（2026-09-17）**：ACLGraph 激活环境（8.5.1 拒 207000），privileged + driver 挂载 + /data 共享（Rust/引擎副本零迁移）；共享 CARGO_HOME=/data/apxinf/cargo + `source /data/apxinf/rust_env.sh`
- [x] **graph.rs：ACLGraph capture/replay（53ec764）**：aclmdlRI* FFI + `AscendStream`/`AscendGraph` RAII + abort；graph_smoke 三模式（GLOBAL/THREAD_LOCAL/RELAXED）真芯验证 replay 回写 pattern
- [x] **tensor.rs + 第一个计算算子 aclnnMatmul（5804a92）**：`AclTensor` ND 描述符 RAII（fp16/fp32）；matmul_fp16 两段式 + workspace；对拍 CPU fp32 参考误差 4.8e-4。链接面：aclnn 在 **libopapi.so**（非 libascendcl）+ 传递依赖 libnnopbase.so
- [x] **元素/融合算子组（450f801）**：add（aclScalar alpha RAII）、silu、add_rms_norm（融合三输出，rstd 隐藏分配）+ `two_stage` 共享 runner；误差 2e-4~1e-3。踩坑：rstdOut 必须 2-D [rows,1]，1-D 报误导性 561103（NULLPTR 名不副实）
- [x] **PFA attention（a925b9a）**：`aclnnPromptFlashAttentionV3`（老版 2026-12 弃用，直接绑 V3）；全量无 mask BNSD，quant 槽位 null；对拍 CPU softmax-attention 1.4e-3
- [x] **AscendBackend 实现 Backend trait（9d82b6c）**：matmul/add/mul/scale/silu/rms_norm（融合 add_rms_norm + 零 buffer 复用）/synchronize/**begin/end_capture（ACLGraph 走通 Box\<dyn Graph\>）**/to_device/to_cpu（f32↔f16，ModelZoo 语义）。Storage 复用 Gpu 槽位（Arc\<DeviceBuffer\> 塞 _prevent_leak，downcast_ref 借回）。rope/embedding/kv-cache/sampling 为显式 "queued" 错误臂。backend_smoke：matmul 0.0 / silu 7.9e-4 / rms_norm 9.3e-4 / capture-replay ✓
- [x] **feature 挂接 + M2 构建半（06f2b60）**：`ascend` feature 贯通元包/apxinf-py（cuda 同构）；9.0.1 容器验证 `cargo check --features ascend`、`check -p apxinf-py --features ascend`、**`build --release -p apxinf-py --features ascend`（cdylib）** 全过
- [ ] **下一章：PI0.5 executor（M2 运行半 + M3 的主体）——结构侦察完成（含一次认知修正，2026-09-17）**：
  - **⚠ 认知修正**：初判"bf16_runtime 设备无关可零改动复用"**错误**——它深绑 cuda（`use super::backend::{kernels, transfers, CudaBuffer, RuntimeBackend}`，计算直调 `gemm::bf16(ctx,..)` / `elementwise::*` 等 cuda kernel 门面，中间量全是 CudaBuffer）。正确结构：vla_runtime → bf16_runtime → pi05/backend.rs(kernels 门面) → apxinf-cuda
  - **结论：executor = 镜像移植**（对照写 ascend 版：kernel 调用层用我们的 ops 替换 gemm/elementwise 调用 + runtime 层把 CudaBuffer/ctx 换 AscendBackend/DeviceBuffer，约 1000+ 行新代码）。**全部为新增文件，不动 cuda 活代码 → 无 CUDA 回归需求**（用户有 CUDA 机器兜底，动 cuda 代码时写最小验证脚本由用户手动跑）
  - **真正可复用（已核实）**：`bf16_weights.rs`（权重上传走 `backend.to_device` trait，BF16→F16 免费转换）+ `config.rs` + `static_weights.rs` 系（host 侧权重解析）+ `fp8.rs` 的量化数学（host）
  - `create_normal_generator` **已完成（4ea8249）**：flow noise 用 core Philox + h2d；rope/embedding/sdpa/kv_cache 不在 pi05 路径（后置）
  - **镜像施工图（2026-09-17 终版，零探索成本可开工）**——依赖链 `vla_runtime(1013) → bf16_runtime(690) → bf16_executor(228) → kernels`，全部新增文件不动 cuda：
    - **待补 op（映射表）**：~~gather/gelu~~ **已完成（37140a4）**：gather → aclnnGatherV2（embedding 通路 bit-exact）；gelu → **aclnnGeluV2**（正向定位战果：aclnnGelu/FastGelu 在 310P3 算子包空缺——core dump / 161002 支持列表为空，跨 8.5.1/9.0.1；torch_npu 真实分发即 V2，tanh/erf 双模式真机验证，误差 4.8e-4）。**连带修复 cat 的 TensorList double-destroy**（aclDestroyTensorList 连带释放子描述符，RAII 二次销毁污染注册表致后续算子 plan segfault——二分定位）。两坑已入 skill runtime_pitfalls 第 13 章。`attention::mha/mqa` → `prompt_flash_attention_fp16`（KV buffer：预分配 + offset 视图）；~~`rope`~~ **已完成（96521c2）**：融合入口双双拒绝 π0.5 的 head_dim（ApplyRotaryPosEmb ∈{64,128}、RotaryPositionEmbedding ∈{32,64,96,128}，π0.5 用 256/72）→ **组合版主路径**（gather 通道重排 bit-exact + mul×2 + add，sign 折进 host sin 表——mul 拒绝零步长广播而 add 接受），真实 D=256 验证 3.9e-3；V2 变体留作单算子优化项；`norm::layer` → aclnnAddLayerNorm(x, zeros) 或组合；`fused::*` → add_rms_norm/bias_add/add 组合；`split_qkv` → AclTensor offset 视图。**ops 待办队列已清零——下一步直接进 B（ascend_executor 层函数镜像）**。**B 的全部建材亦就绪（44b1a2a）**：layer_norm（fused AddLayerNorm+zeros，2e-3）、row_replicate（gather 广播替代，bit-exact）、take_rows（D2D 行切分，QKV split 用；aclTensor offset 视图语义不可靠已移除并留禁用注记）。ops_smoke 12/12 全绿。层函数镜像可直接复用 bf16_weights 的 Tensor 容器（dtype F16 由 to_device 转换）
    - **施工顺序**：A. ~~补 ops~~ ✓ → B. ~~executor 层函数镜像~~ ✓（含真权重路径冒烟：权重上传/输入上设备/层内前 3 个算子全部真机跑通）→ C. **卡点：大 matmul（详见下）** → D/E/F 待续
    - **⚠ C 阶段核心卡点——大矩阵 matmul 在 310P3 的可行路径（2026-09-18 排查现场）**：
      - **已证伪两条路**：① `aclnnMatmul` ND 路径大矩阵崩——kernel `MatMulV2_NZ_ND_FP16` 对 [8,2048]×[2048,2560] 触发 aicore 异常 `MTE DDR address out of range`（小矩阵如 64×128×96 正常；日志铁证）；② `aclnnMatmulWeightNz` **310P 不支持**（日志原文 `Weight NZ is unsupported by the current SOC version [Ascend310P]`——A2/910 系专属）
      - **已废一条路**：`aclnnNpuFormatCast`（ND→NZ 设备转换）desc 要求无法从公开 `aclCreateTensor` 满足（ori_shape 语义，参数看似全对仍 161002）；已改 **host 侧 NZ 重排**（`host_nz_reorder`：CPU 16×16 分块 W-major + 上传，语义自控，代码已在库）
      - **2026-09-18 深夜第二波实验（新证据，改写排查图景）**：`matmul_layout_probe`（独立进程、生产 shape [8,2048]×[2048,2560]）：① plain b row-major **隔离跑不崩且数值对**（4.9e-4）——推翻"大 shape 必崩"；② 前置一个 AddRmsNorm 后：plain b **数值错 0.79**（不崩但读错数据）→ **AddRmsNorm 污染后续 ND-matmul 状态**（cat TensorList 同款类）；③ **转置 b（[N,K] 物理 + [1,K] 转置 stride 视图，torch w.t() 布局）在前置 rms 后仍数值正确**——aq::matmul 已切此路径（NzCache 改 host 转置缓存 + `matmul_b_t_fp16`）；④ **ascend_layer_smoke 全序列仍 507015 崩**，kernel 变为 `MatMulV2_NZ_ND_FP16_false_true`（转置变体）——**存在第二层差异**
      - **第三波（深夜收口）**：smoke 崩点精确定位在**第 25 个 op（down proj matmul，K=8192）**——前 24 个 op（含 2 次 K=2048 matmul、AddRmsNorm、GeluV2、Mul）全过，转置路径已生效；**K 阶梯 probe（4096/8192/16384 转置）隔离全 OK**——K 非独立因素，**纯序列污染**（probe 复刻 smoke 序列才能逼出污染步）
      - **下一轮主战场**：把 smoke 的层序列逐段搬进 probe（候选污染步：from_host 上传 / zeros 缓存 / rope pos-gather×2 + rope 组合 / PFA（BSH 大 S）/ kv_bias d2h-h2d 往返 / gate_up 的 take_rows 大切片），每加一段跑 down-matmul 探针；并行 torch_npu 日志 desc 对照
      - 冒烟脚本已就位：`apxinf-model/examples/ascend_layer_smoke.rs`（随机权重走真实 from_host 路径 → language 层前向，当前 panic 在第一个大 matmul；bias 切片 bug 已修）
      - **C 剩余**（matmul 通后）：ascend_runtime.rs 镜像（权重/前缀 KV/denoise 循环/ACLGraph 捕获）→ D vla 镜像 → E 注册 → F bench = M2 运行半
    - 已完成前置：kernel 面_ops 层（matmul/add/mul/silu/rms_norm/pfa/cat/bias/euler，全部真机对拍）；normal_generator；feature 挂接；M2 构建半
  - 完成后 checkpoint bench → LIBERO 对标（M3）
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
| 4 | 图捕获 | CUDA Graph | **ACLGraph（`aclmdlRI*`）** | **已真芯验证**（2026-09-17：CANN 9.0.1 容器 + 现有宿主驱动，三模式 capture→replay 全绿；8.5.1 runtime 未激活返回 207000——闸门是 CANN 版本非驱动，双容器策略无需停机） |
| 5 | 精度 | BF16/FP8/INT8 | FP16/INT8 | FP16 溢出风险（norm 前 probe） |
| 6 | RoPE | 自研 kernel | aclnnRotaryMul（= npu_rotary_mul） | qkv_rope 融合形态 |
| 7 | 采样/flow steps | device 侧 | 基础算子序列 | 延迟占比小，后置 |

## 里程碑与验收

- M1（阶段一完成）：`build_robot_policy(..., engine="npu-torch")` 可用，bench 出延迟数字，精度对齐 ModelZoo
- M2（阶段二最小）：`apxinf_py` 以 `--features ascend` 构建成功，random-weights bench 在 310P3 跑通
- M3：NPU-native 路径 LIBERO 成功率 ≥ torch_npu 路径 - 1pp，延迟目标对标 378ms 基线（争取显著优于此）
