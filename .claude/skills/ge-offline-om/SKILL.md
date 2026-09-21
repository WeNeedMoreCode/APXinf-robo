---
name: ge-offline-om
description: 昇腾 GE 静态 OM（离线模型）构建实战知识库——不依赖 torch/atc，用 GE graph API（OperatorFactory/SetInputs）构图、aclgrphBuildModel 内存编译、aclmdlExecute 执行。每当你要构建静态 OM/离线模型、用 C++ 直接构图、排查 aclgrphBuildInitialize 或 aclgrphBuildModel 报错、TeFusion/py_decouple 初始化失败、OM 编译成功却是空模型、执行成功但输出全零、或想消除逐算子调度的启动税（ACLGraph per-task tax / 零调度税部署）时，使用本 skill。
---

# GE 静态 OM 构建实战知识库

基于 CANN 8.5.1 / 9.0.1 + Ascend 310P3 实测（2026-09 GE MatMul 链 POC 全链跑通 + 零调度税判定）。所有结论均有实验证据；未验证的归因明确标注"推测"。完整案例见 [references/matmul-poc-case.md](references/matmul-poc-case.md)。

## 路由：你要做什么？

| 场景 | 读取 |
|------|------|
| 第一次构建 OM（环境→构图→编译→执行全流程） | 全文按序读 |
| 遇到报错/异常产物（init 失败、空模型、全零、infershape 拒绝） | [陷阱表](#陷阱表) |
| 环境诊断（TeFusion / py_decouple / 容器） | [环境与自检](#环境与自检) |
| 定位手段（plog / OM 落盘 / strace / IO dump） | [取证工具箱](#取证工具箱) |
| 完整案例（MatMul 链 POC：修复链、代码形态、bench 数据） | [references/matmul-poc-case.md](references/matmul-poc-case.md) |

## 何时选 GE 静态 OM 路线

三条路的实测调度开销（同一 shape 背靠背 16 个 matmul，m=832 k=2048 n=32768）：

| 路线 | 每任务固定开销 | 备注 |
|---|---|---|
| aclnn 逐算子（eager） | 高（每 op host 调用） | 灵活，调试用 |
| ACLGraph 捕获回放 | ~0.5 ms/task（拟合截距） | matmul task 前有明显 gap；task 数多时空隙成为主导成本 |
| **GE 静态 OM** | **≈0（拟合截距归零）** | 静态 shape 专属 tiling，实测大 m 下比 aclnn runtime tiling 快 ~18% |

GE OM 的代价：shape 必须编译期固定（动态 shape 走 input_shape_range，超出本 skill 经验范围）；编译依赖完整 python/tbe 工具链（见环境节）。

## 构图五要素

1. **算子来自工厂**：`OperatorFactory::CreateOperator(name, "MatMul")`。裸 `Operator(name, type)` 是无 IR 空壳——desc/attr 操作全部静默无效，这是首个该查的嫌疑。
2. **连线**：`dst.SetInput("输入名", src_op)`。链接登记在 OperatorImpl 双侧（dst 的 input_link_ + src 的 output_links_），复制 Operator 共享 impl，拷贝后连线仍然有效。
3. **图输入**：`graph.SetInputs({data_ops...})`。这一步**自己从 operator 连线物化整张 ComputeGraph**（内部 BFS 双向遍历）——不需要也不应该手动加节点。输入必须是 Data/Variable 类算子。
4. **图输出**：`graph.SetOutputs({op})`，按算子名在已物化图中找节点。
5. **编译**：`aclgrphBuildModel(graph, build_options, buf)` → `aclmdlLoadFromMem` → `aclmdlExecuteAsync`/`aclmdlExecute`。

**关键约束：AddNodeByOp 与 SetInputs 互斥。** AddNodeByOp 会先初始化一张空内图，锁死 SetInputs（报 "Inner graph has been inited"），且它创建的节点不携带 operator 级连接（报 "xxx input 0 not linked"）。需要 GNode 级操作（重命名、补边）时，在 SetInputs 之后用 `GetAllNodes()` / `FindNodeByName()` 拿节点再做。

**返回值可查性（CANN 9.0.1 operator.h 实测）**：`UpdateInputDesc` / `UpdateOutputDesc` 返回 **graphStatus（可查错）**；`SetAttr` / `Operator::SetInput` / `Graph::SetInputs` / `Graph::SetOutputs` 返回链式引用（**不可查错**）。SetInput/SetAttr 的字符串重载吃 `std::string`/`const char*`（AscendString 反而不匹配）。desc 落没落、边挂没挂，物化后 dump 仍是 ground truth（见取证工具箱）。

## 编译选项（必传）

```cpp
std::map<ge::AscendString, ge::AscendString> opts;
opts.emplace("input_format", "ND");
opts.emplace("input_shape", "x:64,512;w1:512,256;w2:256,512");  // atc --input_shape 语义
```

不传 `input_shape` 的后果：编译返回 SUCCESS，但产物是 ~10KB 的空模型（无 kernel），模型 IO dims 全空、size=4。shape 解析优先级：选项 map > Data 节点 desc。

## Data 节点的两个必设项

```cpp
auto op = OperatorFactory::CreateOperator(name, "Data");
op.UpdateInputDesc(0U, desc);   // ① 幽灵 input desc 0
op.UpdateOutputDesc("y", desc);
op.SetAttr("index", i);          // ② 模型输入顺序
```

1. **幽灵 input desc 0 决定模型 IO dtype**：GE 内部从 Data 节点的 `GetInputDescPtr(0)` 读 dtype。不设 → dtype 缺省 → OM 按 fp32 语义读你的 buffer 并插入 Cast kernel → 典型症状是**执行成功但输出全零**。
2. **index attr 决定输入序号**，与 dataset 组装顺序对齐。
3. 照官方范例对每个 desc 补 `SetOriginShape` + `SetOriginFormat`（EsGraphBuilder 的行为；实测对下述陷阱无副作用）。

## 加载与执行

- `aclmdlLoadFromMem` 在 `aclrtSetDevice` 之后调用（绑当前 context）。
- dataset 绑定用 `aclmdlGetInputSizeByIndex`/`GetOutputSizeByIndex` 取大小（勿自算，模型可能对齐），`aclCreateDataBuffer(你的 device 指针, 模型报告的大小)`。
- `aclmdlExecuteAsync(model_id, in, out, stream)` + `aclrtSynchronizeStream(stream)`；同步版 `aclmdlExecute` 可作排障二分变体（两种语义都正常时应优先怀疑数据/dtype 而非调度）。
- 读回必须在 stream sync 之后（同步 memcpy 不等待异步 kernel 是老坑）。

## 陷阱表（症状 → 根因 → 修法）

| # | 症状 | 根因 | 修法 |
|---|------|------|------|
| 1 | `aclgrphBuildInitialize` 返回 -1；plog 见 `py_decouple "Launch dynamic-handle failed"` | py_decouple 用 `sh -c "python3-config --prefix"` 探测 python 前缀，环境缺该命令退出 127 | 容器内补 `python3-config`（如 `ln -s python3.12-config python3-config`）；strace 确认（见取证工具箱 #5） |
| 2 | "Inner graph has been inited" 或 "input N not linked" | AddNodeByOp 与 SetInputs 混用 | 纯 operator 流：连线 → SetInputs → SetOutputs，全程不调 AddNodeByOp |
| 3 | 编译 SUCCESS 但模型 ~10KB、无 kernel、IO dims 空、size=4 | build_options 缺 `input_shape` | 传 `input_shape` + `input_format=ND` |
| 4 | 执行成功但输出全零；OM strings 里有 `te_cast` kernel | Data 幽灵 input desc 未设 → dtype 错 → Cast 插入 | `UpdateInputDesc(0U, 正确dtype的desc)` |
| 5 | `MatMulV2InferShape: "first input dims is not 2 or 4"`（拓扑、desc、origin shape 全部正确仍报） | MatMulV2 的 infershape rank 门槛；其读取源不是所设 desc（机制未查明；推测经过中间格式变换）——**当前条件下未走通，非证实不可行** | 用经典 `MatMul`（属性 transpose_a/transpose_b，同 kernel 族）替代 |
| 6 | Operator 构造/操作 undefined reference | libgraph_base 是 pre-cxx11 std::string ABI | CMake：`add_compile_definitions(_GLIBCXX_USE_CXX11_ABI=0)` |
| 7 | 想查 Update/SetAttr 是否生效 | Update*Desc 返回 graphStatus 可查；SetAttr/SetInput/SetInputs 返回链式引用不可查 | Update*Desc 检查返回值；其余用物化后 dump（取证工具箱 #2） |
| 8 | 从**多输出算子**（AddRmsNorm 的 y/rstd/x_out、ARPE 的 q/k、Split）连线：边不落图（dump `in0<-<none>`），编译死在断边消费点、plog 无 error 行（停在前一 pass） | `SetInput(dst_port, src)` 对多输出 src 的默认输出解析**静默失败** | 三参形式 `SetInput(dst_port, src, src_out_port)` 显式源端口 |
| 9 | AscendC transformer 族算子（PromptFlashAttention 等）desc 2-D 时编译被静默拒 | desc rank 必须匹配 layout：BSH = rank-3 `[1,m,*]` | 按 layout 维度设 desc；PFA 实测 [1,m,qd]/[1,m,kvd] 通过 |
| 10 | rank-3 输出接 MatMulV2 被拒（V2 有 rank∈{2,4} 门槛） | — | `Squeeze` 桥接（axis 是 int-list **attr**，无张量输入）：[1,m,qd]→[m,qd] |
| 11 | 裸 `RmsNorm` 直出图输出能编译，作**中间节点**喂静态 matmul 永远拒 | RmsNorm 只有 dynamic-shape 变体 | 用 `AddRmsNorm`（eager aclnnAddRmsNorm 同名，端口 x1/x2/gamma→y，x2 传 zeros Data） |
| 12 | `BroadcastToD` 编译崩（TBE task_distribute 空错误） | 310P 上该算子 kernel 编译失败 | 换 `TileD`（REQUIRED_ATTR multiples, ListInt）：`[1,cols]` + multiples `[rows,1]` → `[rows,cols]`，数值逐位验证通过 |
| 13 | `ConcatD` 的 desc/link 拒端口（x1/x2/x/x0 全试一遍）；或 desc 过了但编译崩 | **DYNAMIC_INPUT 端口不随 CreateOperatorByName 预建**（`GetDynamicInputNum("x")==0`；TF parser 是手动 `AddDynamicInputDesc` 的）；且 toolkit 不带 op_desc.h/op_desc_utils.h | 符号直链注册：声明 `OpDescUtils::GetOpDescFromOperator` + `OpDesc::AddDynamicInputDesc`（libgraph_base 有符号、pre-CXX11-ABI 匹配），add_op 后立即注册 n 个端口；端口名 = base+序号**从 0 起**（x0/x1，非 TF 惯例 x1/x2） |
| 14 | 模型输出 size 巨大（~1e16）/ dims 全 -1；运行侧 malloc 该 size 报 207001 | **Reshape（shape 张量输入版）的输出绑成图输出时 desc 是动态的** | 图输出只绑静态 desc 节点（mm/Add/Slice 等）；Reshape 只作中间桥（实测 Reshape→PFA、Reshape 作图尾均可编译运行，Reshape→SliceD 组合崩——陷阱 #16） |
| 15 | `AddLayerNorm` 输出比期望大 ~100×（eager aclnn 与 GE 图**一致地**放大；输入行方差正常） | 310P 上该 kernel 在大 shape（[768,1152] 实测）的行为错误 | 换 `LayerNormV4`（INPUT x + normalized_shape 张量[int32/int64] + OPTIONAL gamma/beta → y/mean/rstd，ATTR epsilon）；数值 0.00098 验证通过 |
| 16 | `Reshape` 输出接 `SliceD` 编译崩；Reshape 输出接 mm(rank-3 desc) 也崩 | 组合门槛（各自单算都过）；MatMulV2 rank-3 输出 desc 只能直出图输出，喂 SliceD 同样崩 | 全链 rank-2：mm(rank-2) → SliceD(rank-2) 切分 → Reshape 升 rank-3 → PFA（该链数值逐位一致） |
| 17 | `LayerNormV4` 的 y 数值爆（65504）——绑满 3 输出的单算图正常 | **mean/rstd 死端（未被消费/未绑图输出）会让 y 也错**——与 AddRmsNorm 死端无害的行为相反 | 每个 LayerNormV4 的 mean/rstd 都绑成图输出（aux 输出，parity 对拍跳过 aux） |
| 18 | GE OM vs eager aclnn 全层多层对拍逐层漂移（~2%/层，稳定不发散；层 0 逐位一致） | GE 静态 tiling 与 aclnn 运行时 tiling 选了不同 kernel 变体（这正是 C 路线性能来源），残差链上累积 | 对拍口径升级：**多层图对 fp32 host oracle**（GE 与 eager 互拍只对单算子/单层有意义）；正确性最终以 LIBERO 端到端为准。⚠ 2026-09-19 追记：vision 104%/prefix 30% 实为对拍参考竞态（#19/#20），修复后 vision 全深 0.1%——遇"逐层稳定漂移"先查参考侧竞态再谈 tiling 变体 |
| 19 | eager 对拍数值非确定（同图同输入 ref 量级随机跳变）；或含 host 读回的参考链在全 device kernel 图上确定性错 | **同步 d2h（aclrtMemcpy）不等待 compute 流上的生产 kernel**——读回跑赢生产者。含 PFA 的链被其 host 回调天然串行化掩盖，全 device kernel 链暴露 | host 读回前显式 `stream.synchronize()`（probe 的 host_ln 已带 stream 参数先同步） |
| 20 | eager 闭包返回后参考 buffer 内容被改写；ref 与后续计算交叉污染 | **闭包内中间量 drop 时 kernel 未落**：aclrtFree 非流序，内存回池被后续 malloc（如 GE 输出 buffer）复用，踩烂在途数据 | eager 闭包末尾（return 前）强制 `stream.synchronize()`，再让局部量 drop |
| 21 | Reshape/LayerNormV4 的 shape 类输入用 Data 节点 → 消费算子输出 desc unknown → 图被动态 shape 拆分、OM 膨胀（实测 221MB）、插运行时机制 | shape 张量是运行时输入，编译期不可折叠 | **Const 节点给 shape**（`geb_add_const_i32` FFI，编译期常量折叠；实测 OM 221MB→16MB）。⚠ 但 host 调度停顿另有其因——flow 带 2683 个 unknown 标记仅 70.9ms 反例 |
| 22 | 静态 OM 里 PromptFlashAttention 每次执行都触发 host 侧 InnerPFA/GetWorkspaceSize（api_statistic 可见 27 次/迭代）+ 输入 staging MemcopyAsync×3 | PFA 是 transformer-API 型算子（opInterface 标记），静态图内走 host launcher 按设计 | 手工 attention 替代：BatchMatMulV2(q,k,adj_x2)+SoftmaxV2(axes=-1)+BatchMatMulV2，scale 折进 qkv 权重/bias 的 q 块；单算对拍 0.26%，kernel 20µs vs PFA 323µs |
| 23 | AttentionScore（bert 时代融合静态 attention）注册表存在但 TBE 编译崩（三 mask 形态全崩） | 310P 无该 kernel 二进制（注册表与 kernel 目录不一致） | 查 kernel 目录 `opp/.../tbe/kernel/ascend310p/` 有无对应 .o 再选算子；用 #22 手工链 |
| 24 | token 主序 [t, h·d] 直接 Reshape 成 [b·h, s, d] 喂 bmm——数值错但 |max| 逐级对得上、单点 max_diff 巨大 | **直接 Reshape 是头/序错排**（token-major ≠ head-major）；attention 输出幅度小时被残差掩盖，逐级 |max| 对比发现不了 | 正确变换 headsplit：Reshape[b,s,h,d] → TransposeD(perm 0,2,1,3) → Reshape[b·h,s,d]；逆变换 headmerge 同构 |
| 25 | BatchMatMulV2/PFA 输出绑图输出 → desc 动态 [-1,-1,-1]（size ~1e18 → malloc 207001）；其直接下游 mm 输出也被感染 [-1,n] | 这些算子的输出 desc 动态推导，动态性只传一层 | 图输出只绑静态 desc 节点（Add/mm 尾部等）；调试需观察 attention 输出时绑其下游第二层之后的节点 |
| 26 | SoftmaxV2 `half_to_float=true` 输出读数全 0 | 输出侧 dtype 行为异常（fp16 缓冲读 fp32 之类，机制未深究） | `half_to_float=false`（fp16 内算，数值验证过）；输入幅度控制在 q·k 点积不溢出 fp16（LN·W 后真实量级安全） |
| 27 | `ge.enableSingleStream=true` 无效（仍 58 流）且改变融合选择 → 数值崩（d1 98.2%） | init 级选项被静默忽略 + 融合集变化 | 弃用；多流停顿问题另有根因（见 roadmap C2 攻坚段） |
| 28 | 静态 OM 执行墙钟远大于 kernel 总时（fill ~15%）；执行流上每层多次 MemcopyAsync（每次 ~380µs、前置 4.5-12ms host 停顿），下个 kernel 固定为切片的消费者（TransposeD/PFA/ConcatD）；换算子/换 attention/Const shape 都不动 | **SliceD 列切视图（stride≠连续）的下游 kernel 要连续物理布局 → GE 运行时每次执行插 D2D 物化拷贝，拷贝走 host 慢路径**（aclmdlExecuteAsync 内走走停顿提交）。msprof task_time 邻接分析可定位（MemcopyAsync 的 next kernel 恒定即指纹）。⚠ 动态路径（unknown 拆分）反而不付此税——切片被物化成 kernel | 图组织上消灭列切视图：① qkv 融合+切分 → 3 个独立 mm + 独立权重输入；② rope 的 lo/hi 半宽切+ConcatD → flat 视图行交换（Reshape[p,wd]→[p·h·2,d/2] → GatherV2D Const 索引 swap → mul/mul/add → Reshape back）。实测 vision 723→68 / prefix 750→188 / flow 70.9→17.5 ms |
| 29 | 改动输入注册集（如 shape 张量 Data→Const 后输入槽消失）后 eager 参考硬编码索引 panic（buffer size 断言，如 [832,256] 读到 [2560,1024]），且可能伪装成 TBE task_distribute 编译崩 | 输入序号整体漂移，索引未同步；段内 const_i32 不占输入槽 | eager 的段级/层内索引与注册序耦合，改注册集必须同步索引（用段头注释记录当前注册序）；先看 panic 的 shape 与实际 buffer 对应哪个输入定位错位量 |
| 30 | op_statistic 里 **TransData 占大头**（实测 flow 54%，27 次/层）；op_summary 签名 `[n,k] → [k/16,n/16,16,16] [ND→FRACTAL_NZ]`；小 m 段（如 decode/flow）每层 ~0.5ms 白耗 | **MatMulV2 的 b 权重按 ND Data 输入时，GE 每次执行都插设备侧 ND→NZ 转换 kernel**（无跨执行缓存；8MB ≈ 130µs @~63GB/s）。torch_npu 的 TransData 大头同源（TorchAir 靠权重入图逃税） | **权重 Const 入图**（`geb_add_const_raw` fp16 → GE 编译期折叠转换、OM 烤入权重，单算实证 0.3945→0.2945 ms/mm、OM 8.4MB）。代价：OM 变 per-checkpoint。⚠ NZ desc 直入（Data 声明 FRACTAL_NZ + host_nz_reorder 字节）在 310P 编译崩（TBE）——未走通，记开放项。⚠ 权重 Const 化会改变 mm kernel 变体的累加序 → 对拍 worst 微移同档（rel% 不变），非 bug |
| 31 | 图内 AddRmsNorm 读**在图中间量**时数值确定性错 11-45%（行剖面平坦/通道结构扁平、**同值作 Data 输入 0.073% 干净**、五类屏障与端口对调变体**逐位不变**、改图形状/垫 M 即变值）；`ge.exec.disableReuseMemory=1` 与 `ge.bufferOptimize=off_optimize` 均无效 | **`InplaceAddRmsNormFusionPass` 把 AddRmsNorm 融合成原地版本**（算子注册表 output0 名就叫 `x1`、output2 叫 `x2`——结果写回两个输入 buffer 本体）；原地别名与静态 OM 内存计划的交互在读中间量时污染数值，Data 输入因用户 buffer 全程受保护而免疫（机制细粒度未钉死，推测与别名 buffer 的计划复用有关）。disableReuseMemory 管不到它也自洽——Const 别名/复用不在其管辖 | **`ge.fusionSwitchFile`（init 级）关该 pass**：JSON `{"Switch":{"GraphFusion":{"InplaceAddRmsNormFusionPass":"off"},"UBFusion":{}}}`（第 4 层直接是字符串 "on"/"off"）——实测 MIN 复现图 11.041%→0.159%、全图 45.2%→0.159%。取证链见工具箱 #6/#7 |

## 环境与自检

GE 内存编译走 **TeFusion 算子编译器**，它依赖 python 子进程栈：

- python 包：`tbe`、`te`、`te_fusion`（CANN 的 `python/site-packages` 内自带）
- python 命令：`python3` 与 `python3-config` 都必须可用（后者常缺，见陷阱 #1）
- 运行三件套：
  ```bash
  export LD_LIBRARY_PATH=<你的build目录>:$CANN/lib64:$LD_LIBRARY_PATH
  export PYTHONPATH=$CANN/python/site-packages:$PYTHONPATH   # 追加勿覆盖
  export ASCEND_RT_VISIBLE_DEVICES=<空闲芯>
  ```
- 自检顺序：`python3-config --prefix` 能执行 → `aclgrphBuildInitialize` 成功 → 单算子小图编译成功，再上真图。
- 算子编译走 python 子进程，首次编译某 shape 秒级耗时属正常；编译失败的报错常在 plog 的 OP/FE 模块行（C++ 侧）而非 python stdout。

## 取证工具箱

1. **plog**：`/root/ascend/log/{run,debug}/plog/`。注意容器时区可能互差 8h——用 `find -mmin -15` 找新文件，别信文件名时间戳。按模块过滤：`grep -E "ERROR" <file>`，GE/OP/FE/TEFUSION 前缀标识来源。
2. **物化后图 dump**：`graph.GetAllNodes()` + `GNode::GetName/GetType` + `GetInputDesc/GetOutputDesc` + `GetInDataNodesAndPortIndexs`（连边来源与 port）——构图问题的 ground truth，构图后立即 dump 一份。
3. **模型 IO dump**：`aclmdlGetNumInputs/GetInputDims/GetInputSizeByIndex`（加载后、执行前）——验证编译产物带上了正确 shape/dtype/size。
4. **OM 落盘 strings**：把 ModelBufferData 写文件后 `strings xxx.om | grep -E "matmul|cast|kernel"`。真模型含 `te_<算子>_<hash>__kernel0` 与 `my_kernel_core.cce`；出现 `te_cast` = dtype 配错信号。
5. **strace 找环境探测失败**：`strace -f -e trace=execve,wait4 ./程序`——第三方库起子进程探测环境（python3-config 等）失败的特征是子进程退出码 127 且主库随后报 init 失败。比读反汇编字符串快。
6. **编译期逐 pass 图 dump**：env `DUMP_GE_GRAPH=3 DUMP_GRAPH_PATH=<dir>`——落盘每个优化 pass 前后的图（ge_proto .txt + onnx .pbtxt，目录下按 `pid_*_deviceid_*`）。查融合/插算子/格式决策的 ground truth（陷阱 #31 靠它发现 InplaceAddRmsNormFusionPass）。
7. **编译选项层级判别**（传错层 rc=-7/-1，与"选项不存在"同症状）：`ge.*` 前缀名是 **init 级**（aclgrphBuildInitialize 的 global_options——socVersion/fusionSwitchFile/bufferOptimize/disableReuseMemory…）；**build 级** map 只收 atc 风格短名（input_shape/input_format…）。合法值要查源码/文档（如 bufferOptimize 是 `off_optimize` 不是 `off`；disableReuseMemory 是 "0"/"1"）。开源 GE 仓（gitee mindspore/ge）的 `compiler/api/aclgrph/ge_ir_build.cc` `CheckGlobalOptions` 与 `api/atc/main_impl.cc` 是选项归属的权威索引。

## 边界

- 本库经验全部来自**静态 shape** 编译。动态 shape（input_shape_range / dynamic dims）未在此验证。
- 实测硬件 Ascend 310P3；其他 SoC 的算子门槛（如 MatMulV2 rank 检查）可能不同，陷阱 #5 的结论按"当前条件未走通"对待。
