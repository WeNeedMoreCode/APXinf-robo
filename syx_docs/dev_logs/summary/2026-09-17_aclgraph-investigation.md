# 2026-09-17：ACLGraph 调研——310P3 图捕获的原理与本机可用性

## 背景

roadmap 技术相异点 #4（图捕获）：CUDA Graph 在昇腾侧无直接等价？用户指出 310P3 未支持 ACLGraph 更像"缺人开发"而非硬件原因，发起调研。调研当日收到消息：**310P3 官方已宣布支持 ACLGraph**（新驱动线）。目标随之升级为"完全对齐 apxinf"。

## ACLGraph 原理（结论）

ACLGraph 就是 CUDA Graph 的昇腾同构物，底层是 `libascendcl.so` 的 **`aclmdlRI*` C API**（RI = model Runtime Instance）：

```
aclmdlRICaptureBegin(stream, mode)   ↔ cuStreamBeginCapture   开捕获
  <stream 上正常下发算子>            ↔ 捕获期间 kernel 被记录
aclmdlRICaptureEnd(stream, &ri)      ↔ cudaStreamEndCapture   产出图句柄 modelRI
aclmdlRIExecuteAsync(ri, stream)     ↔ cudaGraphLaunch        整图重放
aclmdlRICaptureTaskUpdateBegin/End   ↔ cudaGraphExecUpdate    图参数更新
aclmdlRICaptureTaskGrpBegin/End      ↔ （昇腾特有）task 分组
aclmdlRIDestroy / RIAbort / RIDebugJsonPrint   生命周期/诊断
```

capture mode 三种：GLOBAL / THREAD_LOCAL / RELAXED。上游用户：vLLM-Ascend（默认图路径，`torch.npu.NPUGraph` 即其 torch 层封装）、SGLang。torch_npu 的 `NPUGraph` C++ 层就是调这套。

## 本机实测（证据链，三轮迭代后修正归因）

| 层 | 结果 |
|---|---|
| CANN 8.5.1 `libascendcl.so` 符号 | **21 个 aclmdlRI\* 全套存在**；`acl_rt.h:338-3900` 有类型与声明 |
| CANN 8.5.1 直连探针（三模式全试） | `aclmdlRICaptureBegin` 一律 **207000**（干净拒绝） |
| **CANN 9.0.1 容器（同宿主同驱动 26.0.rc1）探针 v3** | **三种 capture 模式全通**：Begin ret=0 → memsetAsync 被捕获 → End → ExecuteAsync → replay 后设备内存验证到 pattern，`ACLGRAPH_ROUNDTRIP_OK` |

**最终归因（修正初判）**：闸门是 **CANN 8.5.1 runtime 未激活**（符号预埋、文档化支持 9.0 起步），**不是宿主驱动**——同驱动下 9.0.1 全通。初判被"driver and firmware packages do not match"的 torch_npu WARN 带偏（那是 CANN 内部对版本组合的通用告警，非本次根因）。

**结论：无需升级宿主驱动、无需停机**。方案 = 双容器：`apxinf_npu`（CANN 8.5.1，torch_npu/阶段 1 基线不动）+ 新建 CANN 9.0.1 容器（Rust `apxinf-ascend` 开发地，ACLGraph 直接可用）。probe：`dev_logs/aclgraph_probe/acl_ri_probe{,_v2,_v3}.c`（服务器 `/data/apxinf/`，v3 在 9.0.1 容器验证全绿）。

## 对齐 apxinf 的行动项

1. 新建 CANN 9.0.1 工作容器（Rust 工具链 + apxinf_engine 副本迁入）
2. `apxinf-ascend` 增加 `aclmdlRI*` FFI + `graph.rs`（capture/replay 已在真芯验证可行）
3. 主线算子绑定（aclnnMatmul 等）在任一容器均可推进

## 方法论

判断"硬件不支持"还是"缺人开发/版本未到"的证据顺序：so 导出符号 → 头文件声明 → 上游生产用户（vLLM/SGLang）→ 本机裸 C 探针（绕开框架断言层拿干净错误码）。本案四层证据全部指向"版本问题非硅片问题"。
