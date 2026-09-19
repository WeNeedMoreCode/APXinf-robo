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

**执行进展（C2）**：三段 OM 全量落地（2026-09-19，f0787fa）——编译/运行/缓存全通，flow 全深对拍 1.6%；**但全模型 bench ~2182ms，距 378ms 验收线 5.8×**。慢源定性为第一版图组织的拷贝类胶水 kernel（TileD/SliceD/Reshape 桥，为绕过编译陷阱引入；eager 路径等价物是广播/零拷贝），核心算子链结论未被推翻——msprof op 级定位 + 逐热点替换是决策的下一个验证点：**若胶水可消除则路线成立，若 GE 图内无广播/零拷贝等价入口则需重谈**（备选回退 ACLGraph 679.8ms 或接受溢价）。

**执行进展（C2 攻坚第一轮，2026-09-19）**：msprof 三轮定律修正了上述定性——**胶水 kernel 不是主因**：vision OM ~700ms 中设备 busy 仅 ~87ms（胶水贡献 ~30ms），**~600ms 是 81 次/迭代的 EVENT→~20ms→MemcopyAsync 空隙**（host 参与的运行时调度路径）。排除 PFA host 回调（手工 attention 替换后仍 700ms）与 unknown-shape 拆分（Const 折叠 OM 221→16MB 仍 700ms；flow 带 unknown 标记 + PFA 仅 70.9ms 反例）。头号嫌疑收敛到**图输出数量**（vision 111 个 LN aux 输出 vs flow 1 个），最小 A/B 验证待下轮。核心算子链进一步强化：bmm 20µs/次（PFA 323µs 的 1/16）、手工 attention 全深对拍 0.1%。

**执行进展（C2 攻坚第二轮，2026-09-19）——空隙根因捕获并修复，路线判定材料齐**：第一动作最小 A/B **反向击毙 111 输出假设**（去掉 LN aux 反而 710ms：死端 mean/rstd 逼编译器换 LN 动态变体）；上轮 profile 邻接分析出铁证（82 次 MemcopyAsync/执行、每次前 4.5-12ms host 停顿、下个 kernel 恒为切片消费者）→ **根因 = SliceD 列切视图触发运行时 D2D 物化（host 慢路径）**。三个图组织修复（qkv 独立投影 / flat rope 行交换 / 手工 attention，全 env 门控）：**全模型 2182→~431ms（5.06×），vision 68.06（0.1%）/ prefix 187.75（25.1%⚠）/ flow 17.51/步（1.6%），距 378ms 验收线 14%**。**决策结论：C 路线的调度上限疑虑解除（空隙是图组织问题非执行器架构问题）；剩余差距主要是 prefix MLP 算力（INTER=16384 busy ~145ms）与 flow 每层 ~1ms 非算力开销；prefix 漂移随 MLP 宽度单调（fp16 大 K 累加序假设）待 M3 e2e 判定。**
