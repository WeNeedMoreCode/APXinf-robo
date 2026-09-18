# 002: 阶段二执行图技术转 GE 原生 OM

日期：2026-09-19　状态：已接受（POC 验证通过）

## 决策

阶段二（Rust 原生引擎）的执行图技术从 ACLGraph（aclmdlRI 捕获回放）转向 **GE 原生 OM**：GE graph API 在 C++ shim 中构图、`aclgrphBuildModel` 内存编译为静态 OM、`aclmdlExecuteAsync` 执行。模型定义留在 Rust（executor 逻辑不搬家），shim 为薄通用构图层（ge_builder FFI）。ACLGraph 路径保留为回退。

## 背景与证据链

- **验收线判定（2026-09-19，插桩三轮闭环）**：ACLGraph 回放全深度 679.8ms，链内空隙 ~401ms 的 81% 集中在 matmul task 前（~334-475µs/task）；无 profiler 拟合 `time = 6.1µs/row + 475µs/task`；torch_npu 同口径空隙仅 17.3ms/iter。结论：ACLGraph 捕获模型的 matmul task 调度税是**架构级**的，aclnn 层无解（换入口 Mm/Gemm/MatmulCommon 三档同分；op 融合三次实验不动——图内设备时间由带宽决定）。
- **POC（同日）**：16 连发 matmul 静态 OM 实测 m=832 时 **4.745 vs aclnn+ACLGraph 5.812 ms/matmul（−18%，23.5 TFLOPS）**；拟合固定税 555µs/task→0，斜率再降 20%（静态 shape 专属 tiling 优于 aclnn 运行时 tiling）。外推全模型 ~370-390ms ≈ 验收线 378ms。
- **代价与约束**：shape 编译期固定（OM 按 shape 签名 + 引擎版本缓存落盘）；构图依赖 TeFusion python 栈（环境要求与坑见 setup.md「双容器分工」+ ge-offline-om skill；CANN 9.0.1 容器在 python3-config 修复后可用）。

## 备选与理由

- **A 接受 679.8ms 进 M3**：被否——与 378ms 基线差 80%，"部署形态换延迟"溢价过高
- **B 310P3 定位为验证芯片、性能目标移至下一代硬件**：保留为回退；POC 数据支持 C 时放弃太早
- **C GE 原生 OM（选定）**：零调度税 + tiling 增益实证；工程代价（构图 FFI + OM 缓存 + 三段式施工）可承受
- 附注：MatMulV2 infershape rank 门槛未走通，当前以经典 MatMul 替代（同 kernel 族），开放项见 ge-offline-om skill 案例

## 施工计划

三段式：C1 垫脚石（ge_builder FFI / transpose_x2 权重布局实验 / 单层 GE 化双路径对拍）→ C2 三段 OM 全量 + 缓存 → C3 验收线判定 + M3。详见 `plans/npu-port-roadmap.md` C 路线节。

**执行进展**：C1 四项已完成（2026-09-19，1691df9/7de49c7）——单层 GE 化对拍 eager **0.00000**、**1.76×**（10.28 vs 18.06 ms/layer @ m=832），外推全模型 ~380ms ≈ 验收线，决策证据链得到全层强化。构图陷阱（多输出算子 link 静默失败 / PFA rank-3 / RmsNorm 动态变体）沉淀于 ge-offline-om skill 陷阱表 #8-11。
