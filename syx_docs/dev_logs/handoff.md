# Handoff（2026-09-19 GE POC 中断点，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**GE 原生 OM POC 的完整知识链**（C 路线：GE 是纯 C++ 原生库无需 torch；性能根因=ACLGraph 每 matmul task ~475µs 启动税 vs GE 静态 OM 零税（torch 17.3ms/iter vs 我们 401ms 空隙）；POC 已打通编译链+GE init，卡点=图装配顺序）；**POC 硬知识**（CANN libgraph_base 是 pre-cxx11 ABI 需 `_GLIBCXX_USE_CXX11_ABI=0`；GE 只能跑 apxinf_npu 容器（TeFusion 需 python/tbe，rust 容器不行），需 LD_LIBRARY_PATH=ge_poc/build+CANN lib64 + PYTHONPATH=CANN site-packages；算子必须 OperatorFactory::CreateOperator，裸 Operator(name,type) 是无 IR 空壳；MatMulV2: 输入 x1/x2 输出 y 属性 transpose_x1/x2；**SetInputs 必须在 AddNodeByOp 之前**（graph.cc:56 锁内图），operator SetInput 连接不保留需 GNode 级 AddDataEdge）；文件位置（本地 apxinf/crates/apxinf-ascend/ascendc/ge_poc/，服务器 /data/apxinf/ascendc/ge_poc，产物 build/）；服务器三件套；异步生命期纪律；子模块双仓两步提交（push 用 fork）。丢弃：本轮 POC 编译报错逐轮过程（commit 1ed06e2 信息 + roadmap 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **GE 原生 OM POC**（goal：完成 POC；子模块 1ed06e2，代码在 apxinf/crates/apxinf-ascend/ascendc/ge_poc/）。第一动作：修 ge_matmul_poc.cpp 的 ge_poc_build 图装配顺序——`graph.SetInputs({x_op,w1_op,w2_op})` 移到所有 AddNodeByOp **之前**，AddNodeByOp 后用 `graph.GetAllNodes()`/按名找 GNode，GNode 级 `AddDataEdge(src,0,dst,port)` 连边（x→mm1_i.port0、w1→mm1_i.port1、mm1→mm2.port0、w2→mm2.port1），最后 `SetOutputs`。同步服务器（rust 容器编译：cd /data/apxinf/ascendc/ge_poc && find . -name "*.cpp" | xargs touch && cd build && make），在 **apxinf_npu 容器**跑（env：LD_LIBRARY_PATH=build+CANN lib64、PYTHONPATH=CANN site-packages、ASCEND_RT_VISIBLE_DEVICES=5）：`./ge_poc_main verify`（64×512×256 对拍 host fp32）→ 过后 `./ge_poc_main bench`（832×2048×32768×16 matmul 连发，判定 GE task 零税 vs aclnn 5.86ms/matmul）。bench 数字出来即 POC 结论：零税 → C 路线收益坐实可全量投入；有税 → 回决策点。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_perf-wave2-ge-poc.md（新文件：空隙取证闭环 + 验收线决策 + GE POC 开工）
