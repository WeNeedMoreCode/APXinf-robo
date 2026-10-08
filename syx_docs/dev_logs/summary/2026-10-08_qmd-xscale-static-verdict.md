# goal ① qmd x_scale 静态化探明（2026-10-08）

## 终局一行

**原始问题判决：静态 x_scale 在 310P 无实现**——QuantMatmulDequant 的 x_scale/x_offset 可选输入在注册表里存在（idx4/5），但唯一预编译 kernel 只实现 pertoken（pertensor attr 编译过、执行 bit 级同 pertoken = 输入被忽略；perchannel/pertokenScale 直接编译拒）。**探明的意外收获是完整路线图**：w8a16（WeightQuantBatchMatmulV2）数值最优（eager 实测 rel 0.066%）但被 310P 模板墙挡死（arch35 AscendC 模板族无 310P 项）；**分解式 w8a8（DynamicQuantV2 → TransQuantParamV2 → QuantBatchMatmulV3）三算子链 310P 离线 build 通过**——0.53× 剩余缺口的量化侧唯一存续路线（数值面 = 现行 w8a8 同数学，行为面风险不变，依赖校准 v3）。

## 判决表

| 路线 | 数值 | 310P GE 离线 | 判决 |
|---|---|---|---|
| qmd 静态 x_scale（perchannel / pertensor / pertokenScale） | — | perchannel（[k] 与 [1,k] 两种 desc）拒；pertokenScale [m] 拒；pertensor [1] 编译过但 **X-vs-Q max_diff=0.0000**（N=8192 与 N=256 双形状）+ X/Q=0.97-1.02× | ✗ **310P bin 只实现 pertoken**——simplifiedKey 不含 mode，attr 过校验后仍匹配同一个 pertoken binary |
| w8a16 WeightQuantBatchMatmulV2 | **eager（8.5.1）实测 rel 0.066%**（weight-only per-out-channel，零激活量化误差） | tiling 拒：`Do op tiling failed, no valid template is found`（slog 取证；源码 `impl/ops_nn/ascendc/.../arch35/` = 新芯片向模板族） | ✗ 引擎内不可用。**kernel 本体在 310P 是活的**（eager 证明）——死在 9.0.1 离线的 AscendC 模板 tiling 机制，非算子缺失 |
| 分解式 w8a8：DynamicQuantV2 + TransQuantParamV2 + QuantBatchMatmulV3 | 未验（目标 = 现行 w8a8 同数学） | **BUILD OK**（M=50 K=2048 N=256 三算子链；QBMV3 须显式 dtype=1，u64 packed scale 走 op-to-op） | ✓ 唯一存续。契约/坑全数探明（见下） |
| norm+量化融合 add_rms_norm_dynamic_quant | — | 310P 无注册 | ✗ |

## 关键契约与坑（全部实测）

- **qmd attr 校验在位**：垃圾值 banana 编译拒 → "pertensor 能编"是真实枚举成员（libopapi strings: pertoken/pertensor/perchannel/pertokenScale；后者报错原文要求 x_scale 首维=x 的 MDim）。⚠ 自造对照实验污染教训：run() 助手把 `GEB_QMD_XSO=0` 传进去，`env::var().is_ok()` 仍真（设了就算）——b/d 变体全被强加 x_offset，一轮数据作废
- **WQBMV2 eager 契约**（torch_npu 2.9/op_plugin，真实 op 名 `npu_weight_quant_batchmatmul`，从 libtorch_npu.so strings 挖出）：weight **[k,n] 连续** + scale [n] + 无 transpose attr（布局由张量形态推）；[n,k] 被 host check 拒（报错 "The k of x and weight should be equal"——weight_k_dim 读 shape[0]）。GE 离线 [k,n] 同样被模板墙拒（非布局问题）
- **QBMV3**：infer 函数硬要求显式 `dtype` attr（OP_PROTO 报 "GetOpAttr out_dtype failed!"；注册表 json 的 dtype:1 是 bin 烤入值非图级默认）；x2 要 FRACTAL_NZ（ND desc 建 [n,k]+transpose_x2=true 通过）；packed scale u64
- **TransQuantParamV2**：f32 scale [n] → u64 [n]；输出 desc **不可显式设**（[n] desc rc=-3 冲突，走算子推断）
- **ge_builder FFI 补 uint64**（"uint64"→ge::DT_UINT64，C++ ParseDtype + Rust Dtype 枚举两处）；⚠ **双源副本坑**：cmake 构建源在 `/data/apxinf/ascendc/ge_builder/`，引擎目录 .cpp/.so 是 staged 副本——cargo/make 都不侦测引擎侧改动，改完必须 cp 过去 make 再 cp .so 回来（曾因此误判 uint64 不支持）
- **ops 家族分类学**（310P 离线可用性的第一判据）：`ops_legacy`（老式 TBE）离线稳；`ops_nn/dynamic`（新代 AscendC 模板）逐算子看脸——DynamicQuantV2/TransQuantParamV2/QBMV3 可建、WQBMV2 不可建。已回填 ge-offline-om skill（陷阱 #40-43 + 速查表）

## perf 前景（诚实外推，未实测）

分解路线把 flow 每步 126 次 in-op 量化流水换成 4 个输入点/层 × 18 层 = 72 次独立 DynamicQuantV2（q/k/v/gate/up 共享 norm 后量化；o、down 各自独占）——量化开销省 ~43%，上界 ~10-15ms/全调用（相对 int8 位 75.6ms flow）。**到不了 -30ms 带宽模型的全部**（那是 w8a16/w8a8 真正砍掉激活侧开销才能兑现的量级，w8a16 已死、分解式只省调度不省数学）。可达终点估 ~215ms（0.57×）一线，前提是校准 v3 修好行为面。**0.53×（200ms）在量化侧无可达路径**——结构下限证据链本轮补全。

## 探针资产（引擎 50024cb 之后新增，全 env 门控、零生产路径改动）

- `GEB_QMD_XS`（链 X：静态 x_scale 三模式 + 垃圾值透传）+ `GEB_QMD_XSD`（[1,k] 变体）+ `GEB_QMD_XSO`（x_offset）
- `GEB_QMD_WQ`（链 W：w8a16 WQBMV2，=3 走 [k,n] 契约）+ `GEB_QMD_WA`（dtype/group attr）
- `GEB_QMD_Z=<OpName>`（链 Z：单算子 build-only 冒烟）
- `GEB_QMD_Z2=1`（链 Z2：DQ+TQP+QBMV3 三算子生产拓扑 build 冒烟）
- 脚本：`pyo3_check/wq_eager_test.py`（eager 判决：schema 打印 + 布局变体 + 数值对拍）、`pyo3_check/wq_cap_check.py`（opp wrapper 直调复现——check_op_cap/compile 入口）
- 取证工具链：`ASCEND_SLOG_PRINT_TO_STDOUT=1`（FE/tiling 报错现形——本轮决定性）、opp 注册表 json 三层读取（config/impl py/AscendC 源码头）、libopapi/libop_plugin strings 枚举挖掘

## 下一步（分解路线要做的事，下轮菜单）

1. **Z2 链数值对拍**：wire run 路径（DQ 多输出 y/scale 绑 QBMV3 x1/pertoken_scale）+ host 双参考——packed scale 语义解码（TransQuantParamV2 的 u64 打包格式，跑一对已知输入读位型）
2. **五形状单算 bench + 全图 A/B**：DQ@M=50 开销 vs qmd in-op 流水（上表 43% 假设的实测检验）
3. 引擎接线（GEB_FLOW_INT8_DECOMP 类 env + 新 OM 烤制）→ golden → 行为梯（与校准 v3 合流）
