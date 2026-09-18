# 昇腾 NPU 移植总体设计（living doc）

> 状态：路线已定（2026-09-16）——混合路线 + 预留原生接口，硬件锁定 310P3。见 [decisions/001](../decisions/001-hybrid-route-with-native-seam.md) 与 [plans/npu-port-roadmap.md](../plans/npu-port-roadmap.md)。

## 一、APXinf-robo 是什么（事实）

- Rust 实现的边缘推理引擎，无外部运行时依赖，CUDA-only
- 场景：具身智能 VLA 模型，首发支持 PI-0.5（π0.5）on Jetson Thor/Orin
- 精度：BF16 / FP8（Thor）/ INT8（W8A8）
- 仓库结构：外层 Python 包（`src/`，robot presets / policy API / websocket serving）+ `apxinf/` 子模块（Rust 引擎）

### 引擎 crate 结构

| Crate | 职责 | 规模 |
|---|---|---|
| `apxinf-core` | Tensor/Shape/DType/Storage/Device + `Backend` trait + CPU 后端 | 小 |
| `apxinf-cuda` | CUDA 后端：context/buffer/cublas/kernels/graph capture/KV cache | ~6k 行 kernel 代码 + GEMM 栈（CUTLASS bf16/fp8/w8a8） |
| `apxinf-loader` | safetensors 加载 | 小 |
| `apxinf-model` | 模型实现：llama / qwen3vl / pi05（~8.5k 行）/ vla | 中 |
| `apxinf-tokenizer` | HF tokenizer 封装 | 小 |
| `apxinf-py` | PyO3/maturin Python 绑定 | 小 |

### 后端抽象（移植的关键接缝）

`apxinf-core/src/backend.rs` 的 `Backend` trait 是后端无关接口：

- **原语算子**：rms_norm、silu、add、mul、scale、matmul、rope（+ mrope / vision_2d 变体）、layer_norm、gelu_tanh、add_bias、concat_2d、vision_sdpa、embedding
- **复合算子**：sdpa_decode、sdpa_prefill（结合 KV cache）
- **KV cache**：create_kv_cache、kv_append
- **执行控制**：synchronize、begin_capture/end_capture（CUDA Graph 等价物）
- **设备管理**：to_device / to_cpu / as_any

**关键事实**：PI0.5 热路径不走 trait。`apxinf-model/src/accelerator.rs` 有编译期分派缝（`create_backend`），且 PI0.5 executor 通过 `downcast` 拿具体 `CudaBackend` 调 CUDA 专属融合 kernel（`ada_gate_residual_rms_norm`、`qkv_rope`、`euler_update` 等）——注释明确说这是有意设计，统一 `dyn Backend` 只为加载入口。**因此只实现 `Backend` trait 拿不到全速 PI0.5，融合 kernel 需要逐个在目标后端重写或拆解。**

## 二、目标硬件约束（事实）

Ascend 310P3（Atlas 300I Duo，服务器 8 芯，每芯 ~44GB）：

- 支持精度：FP16 / INT8（**无 BF16、无 FP8**）→ APXinf 的 BF16 路径需转 FP16，FP8 路径在 310P3 上无意义（INT8 W8A8 可保留）
- 软件栈：CANN（服务器镜像有 8.3.rc1 / 9.0.1；ModelZoo π0.5 指导用 8.5.2）、torch_npu、TorchAir 图编译、MindIE
- `aclnn` 算子库是 C API，可被 Rust FFI 直接绑定

## 三、ModelZoo π0.5 已有适配（事实，重要参考）

位置：`vla/pi05_openpi`（openpi 路线）+ `vla/pi05_lerobot`。要点：

| 项 | 值 |
|---|---|
| 路线 | openpi PyTorch + torch_npu 2.7.1 + TorchAir 图编译 |
| 精度 | FP16 |
| 优化 | 权重 NZ（FRACTAL_NZ）格式转换、`torch_npu.npu_rotary_mul` 替换 RoPE、三个子图（embed_image / paligemma_with_expert.forward / denoise_step）TorchAir `dynamic=False, fullgraph=True` 编译、多图 embed 合并 batch |
| 性能 | 300I Duo 单芯 **378ms**/推理（10 flow steps），与 lerobot 版持平 |
| 镜像 | MindIE 3.0.0-300I-Duo-py311（服务器有 dev 版 torch2.9.0 变体） |

对照：APXinf CUDA 版 Jetson Thor FP8 41ms / BF16 72ms（同 10 flow steps）。**378ms 是 torch_npu+TorchAir 路线的实测基线**，Rust 引擎路线的性能目标应以此对标（而非直接对标 Thor）。

## 四、候选技术路线

### 路线 A：Rust 原生 ACL 后端（apxinf-ascend crate）

新增 `crates/apxinf-ascend`，CANN ACL C API（aclnn 算子库）实现 `Backend` trait + PI0.5 融合 kernel。

算子映射草案（待逐个验证 310P3 覆盖）：

| APXinf | ACL/aclnn 候选 |
|---|---|
| matmul | aclnnMatmul（含 NZ 布局） |
| rms_norm / layer_norm | aclnnRmsNorm / aclnnLayerNorm |
| silu / gelu_tanh | aclnnActivation 系列 |
| sdpa_prefill / vision_sdpa | aclnnFusionAttention（310P3 支持情况待验证） |
| rope / qkv_rope | aclnnRotaryMul（对应 npu_rotary_mul） |
| add / mul / scale / add_bias | aclnnAdd / aclnnMuls / aclnnBiasAdd 等二元/标量算子 |
| 融合 kernel（ada_gate_residual_rms_norm 等） | 拆成基础算子序列起步，热路径再融合 |
| graph capture | 无 cudaGraph 直接等价；先 no-op（synchronize 兜底），后续考虑 host 侧算子序列录制回放 |
| FP8 | 不适用（310P3 无 FP8）→ FP16；INT8 W8A8 可后置 |

- 优点：真正的「APXinf 引擎 NPU 版」；无 Python/torch_npu 逐层调度开销；架构对齐原作者设计（上游可能接收 PR）
- 缺点：工作量最大（Rust FFI 绑定层 + 算子验证 + 融合 kernel 重写）；调试链路长
- 里程碑判断（推测未严格证明）：核心链路（matmul+attention+norm 激活）打通后 random-weights bench 可先跑，LIBERO 精度对齐需全量算子

### 路线 B：Python API 兼容层 + torch_npu 后端

保留 `apxinf_robo` 的 L1/L2/L3 Python API（`build_robot_policy` / `load_policy` / websocket server），内部引擎换成 ModelZoo 的 openpi+torch_npu π0.5 实现。

- 优点：工作量最小；ModelZoo 已验证可用 + 378ms 基线；快速跑通 LIBERO 端到端
- 缺点：不是引擎移植，是 API 兼容层；性能上限被 torch_npu 逐层调度锁死；APXinf 的 Rust 代码全部弃用

### 路线 C：混合——B 先行验证，A 并行推进（推荐倾向）

1. 阶段一（路线 B）：torch_npu 后端接到 `apxinf_robo` API 下，跑通 LIBERO 精度对齐（对标 ModelZoo 精度）+ 建立 NPU 性能基线
2. 阶段二（路线 A）：`apxinf-ascend` crate 从 `Backend` trait + 基础算子起步，PI0.5 BF16→FP16 路径逐步迁移融合 kernel
3. 阶段三：用阶段一的精度/性能数据验收阶段二

- 优点：短期出可跑结果，长期对齐引擎架构；阶段一还能反向提供精度金标准
- 缺点：两套实现并行维护一段时期

## 五、已决策（2026-09-16，用户确认）

1. **技术路线**：混合路线（C），但**预留原生接口**——Python 层引擎抽象一步到位，torch_npu 是首个实现，Rust `apxinf-ascend` 后续接入同一缝；技术相异点一个一个过
2. **目标硬件**：锁定 310P3（BF16→FP16，无 FP8，INT8 后置）
3. **验收口径**：延迟对标 ModelZoo 378ms 基线；精度 LIBERO 对齐（PI0.5 reference 92.4%）

## 六、路线演进（阶段二，2026-09-19 增补）

路线 A 实施中的两处关键演进（细节数据见 plans/npu-port-roadmap.md，决策记录见 decisions/002）：

1. **graph capture 行 → 已落地并超越**：ACLGraph（aclmdlRI 捕获回放）先落地（depth 2/2/2 提速 3.46×）；后经 msprof 双边取证发现其 matmul task 有 ~475µs 架构级调度税（全深度 679.8ms 的 81% 空隙来源）→ 转 **GE 原生 OM**（graph API 构图 + aclgrphBuildModel 内存编译），POC 实测零调度税 + 大 m tiling 再快 18%；C1 全量垫脚石落地（ge_builder 通用构图 FFI + 单层全序 GE 化对拍 0.00000、**1.76× vs eager**），C2 三段 OM 全量施工中。
2. **matmul 行 → 转置路径定案**：ND 直连大矩阵有 MTE 越界/前序状态污染坑（见 roadmap「C 阶段核心卡点」五波排查），生产路径定为 host 转置 + transB stride 视图（NzCache）；GE OM 路线沿用该布局（transpose_x2）。

上文路线 A 算子映射表为阶段起点草案，落地实况（PFA 用 V3、RoPE 组合版、GeluV2、12 算子真机对拍等）以 roadmap 阶段 2 记录为准，不再回填本表。
