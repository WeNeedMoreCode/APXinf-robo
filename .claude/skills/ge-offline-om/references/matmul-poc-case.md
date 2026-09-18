# 案例：GE MatMul 链 POC（2026-09，Ascend 310P3）

> 快照自 APXinf 昇腾移植项目的 C 路线 POC。环境细节（服务器、容器、路径）是**案例现场记录**，非 skill 依赖——方法论部分见 SKILL.md，此处是它的一次完整落地。

## 背景与目的

项目推理引擎此前用 ACLGraph（aclmdlRI 捕获回放）消除 host 开销，但 msprof timeline 取证发现链内空隙 ~401ms/iter，81% 集中在 matmul task 前（~334-475µs/task）——ACLGraph 回放下 matmul task 有固定启动税，换入口（aclnnMm/Gemm/MatmulCommon）三档同分。POC 目标：**用 GE graph API 构建纯 matmul 链静态 OM，实测 task 调度是否零税**（对标同 shape 的 aclnn+ACLGraph）。

## 图结构与 shim 形态

```
x[m,k] ──► MatMul(w1[k,n]) ──► MatMul(w2[n,k]) ──► y[m,k]      × pairs 对
             ▲ w1(Data)           ▲ w2(Data)
```

权重走 Data 输入（运行时绑 device buffer，不烤进 OM）。

```cpp
// shim（C++ shared lib，Rust 侧 dlopen 亦可）
extern "C" int ge_poc_init(const char *soc_version);   // aclgrphBuildInitialize({ge.socVersion})
extern "C" int ge_poc_build(int32_t pairs, m, k, n);   // 构图 → aclgrphBuildModel → aclmdlLoadFromMem
extern "C" int ge_poc_run(void *x, void *w1, void *w2, void *y, void *stream);
extern "C" int ge_poc_fini();
```

驱动程序双模式：`verify`（64×512×256，对拍 host fp32 参考）与 `bench`（832×2048×32768×8 对，30 轮×10 连发取中位）。

## 修复链（五连，全部取证定位）

按踩坑顺序；症状→根因→修法的通用表述已入 SKILL.md 陷阱表，此处补取证细节：

1. **图装配报错**（"Inner graph has been inited" / "mm1_0 input 0 not linked"）。取证：读 GE 源码 `graph.cc` 的 `GraphImpl::SetInputs` → `CreateGraphFromOperator` → `GraphBuilderImpl::BuildGraph`——SetInputs 自己从 operator 双侧链接 BFS 物化整图；而 AddNodeByOp 走 SetValid() 初始化空内图，两条路互斥。修：删 AddNodeByOp，纯 operator 流。物化后 dump（GetAllNodes + 每节点 in-edge 来源 + desc dims）确认拓扑与 desc 正确。
2. **MatMulV2 infershape 拒绝**（"Matmul the first input dims is not 2 or 4"）。dump 证明 node input desc 是正确的 2-D [64,512]，补 SetOriginShape 也无效——插件读的不是所设 desc（机制未查明；推测中间有格式变换，NZ 类 4/5-D 表达）。经典 `MatMul`（transpose_a/b）无此门槛，同 kernel 族，改用它。**MatMulV2 路径当前条件下未走通，留开放。**
3. **空模型**（编译 SUCCESS、~10KB、IO dims 空、size=4）。读 GE 源码 `ge_ir_build.cc` 的 `Impl::SetInputs`：Data shape 从 `omg_context_.input_dims`（即 `input_shape` 选项）解析，Data 节点 desc 只是次优来源。修：build_options 传 `input_shape="x:64,512;..."` + `input_format=ND` → 46KB 真模型、IO 全对。
4. **输出全零**。执行无报错，OM strings 里发现 `te_cast` kernel——GE 给 IO 插了类型转换，说明 dtype 没对上。根因：Data 的**幽灵 input desc 0** 未设（`Impl::SetInputs` 从 `GetInputDescPtr(0)` 读 dtype）。修：`UpdateInputDesc(0U, fp16desc)` → Cast 消失、模型从 46KB 缩到 25KB、对拍 0.002075。回看第 3 步的 size=4：fp32 标量尺寸——dtype 缺省的铁证。
5. **GE init -1（CANN 9.0.1 容器）**。plog：`py_decouple "Launch dynamic-handle failed"`。strace `-f -e execve` 实锤：py_decouple 起 `sh -c "python3-config --prefix"`，该容器 python3.12 源码安装没带无版本号链接 → 退出 127 → dynamic-handle 死。修：`ln -sf .../python3.12-config .../python3-config`，一个符号链接修复。此前该容器被认为"GE 不可用、必须换 8.5.1 容器"——结论被推翻。

## bench 判定（同日同芯同 shape，16 连发 matmul，n=32768 k=2048）

| m | aclnn+ACLGraph (ms/matmul) | GE 静态 OM (ms/matmul) |
|---|---|---|
| 64 | 1.1210 | 1.1697 |
| 128 | 1.4295 | 1.4510 |
| 256 | 1.6202 | 1.7008 |
| 512 | 3.2928 | 3.1222 |
| 832 | 5.8123 | **4.7451**（另一次独立 run 5.3115） |

最小二乘拟合（注意：小 m 段 kernel 效率本身下降，线性模型混杂，看截距只作方向参考）：

- aclnn+ACLGraph：`5.86 µs/row + 555 µs/task`（与更早无 profiler 拟合的 475µs 同量级）
- GE 静态 OM：`4.71 µs/row`（截距被小 m 效率污染，但 m=832 单点 −18% 干净）

**结论：① GE 静态 OM 无 per-task 调度税（970 matmul task 量级的空隙来源被消除）；② 静态 shape 专属 tiling 比 aclnn 运行时 tiling 快 ~18%（m=832 时 23.5 TFLOPS）。** 小 m（≤256）两者打平——kernel 效率主导，调度差异被淹没。

## 案例环境快照（非 skill 依赖）

- 服务器：8×Ascend 310P3 共享机；任务用 `ASCEND_RT_VISIBLE_DEVICES=5` 挑空闲芯
- 双容器（共享 /data）：CANN 9.0.1 privileged 容器 = 编译+GE 全链（python3-config 修复后）；CANN 8.5.1 MindIE 容器 = torch_npu 基线。两容器的 GE 行为同症状同修（空模型/全零问题跨版本复现，python3-config 仅 9.0.1 容器缺）
- C++ 链接 CANN graph 库必须 `_GLIBCXX_USE_CXX11_ABI=0`（libgraph_base 是 pre-cxx11 string ABI）
- 产物：shim `.so` + standalone 可执行（驱动含 verify/bench 与手写 fp16↔fp32 位转换，无 half.h 依赖）
- 代码：`apxinf/crates/apxinf-ascend/ascendc/ge_poc/`（commit 28adf78），随上游仓漂移，以本快照为准

## 开放项

- **MatMulV2 infershape rank 门槛**：拓扑/desc/origin 全对仍拒。已试未通：经典 2-D desc、SetOriginShape/Format。未试：4-D desc 变体、bias input desc 显式设置、读 8.5.1 版 matrix_calculation_matmul.cc 源码（服务器无插件源码，本地开源仓版本不同）。当前用经典 MatMul 替代，功能等价。
