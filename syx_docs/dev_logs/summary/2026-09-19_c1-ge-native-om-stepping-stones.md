# 2026-09-19 C 路线 C1 垫脚石四项收官

## 一句话

C1 全部完成（1691df9 + 7de49c7 双仓已推）：ge_builder 通用构图 FFI 全链绿、转置权重布局零代价、PFA GE IR 契约取证定案、单层 GEMMA_2B language layer 全序 GE 化对拍 **0.00000** + **1.76× vs eager**（10.28 vs 18.06 ms/layer @ m=832）——外推全模型 ~380ms ≈ 验收线 378ms。下一步 C2 三段 OM 全量。

## 分项

| 项 | 交付物 | 关键数据 |
|---|---|---|
| ① ge_builder FFI | `ascendc/ge_builder/`（C++ 薄层）+ `src/ge_builder.rs`（Rust 客户端）+ 两个探针例程 | C++ 驱动复现 POC verify 逐位一致（0.002075）；Rust 全链对拍 aclnn 0.00009、bench 4.649 ms/matmul |
| ② 转置权重布局 | geb_main trans 模式 | MatMulV2 transpose_x2 + [n,k]：数值 0.002075 同分；bench 4.930 vs 4.941 打平（零代价，NzCache 管线直连） |
| ③ PFA GE IR | 310P opp 包 kernel json 取证 | 注册名 `PromptFlashAttention`，13 输入（query/key/value fp16 必选 + 10 可选）/输出 attention_out/8 attrs 全契约；附加发现 apply_rotary_pos_emb、incre_flash_attention 预编译 |
| ④ 单层 GE 化 | `examples/ge_layer_probe.rs`（含 GEB_SUB 1-9 编译冒烟矩阵） | 对拍 0.00000（同族 kernel 逐位一致）；1.76× |

## 排障主线（三陷阱，全部取证定罪，已回填 ge-offline-om skill #8-11）

1. **多输出算子默认输出解析静默失败**（真凶）：`SetInput(dst_port, src)` 对 AddRmsNorm（y/rstd/x_out）类 src 边不落图（物化 dump `in0<-<none>`），编译死在断边点、plog 无 error 行 → 三参 `link_out`（FFI 新增）。rstd 死端是红鲱鱼（顺带新增 geb_graph_outputs_idx 索引式图输出）
2. **PFA 必须 rank-3 desc** [1,m,*]（BSH）；2-D 静默拒
3. **裸 RmsNorm 只有 dynamic 变体**：直出图输出能编译、中间节点喂静态 matmul 永拒 → AddRmsNorm（eager aclnnAddRmsNorm 同名同端口 x1/x2/gamma→y，x2=zeros Data）
4. 桥接件：Squeeze（axis 是 int-list attr，无张量输入）解决 rank-3 输出 → MatMulV2 rank∈{2,4} 门槛

## 其他记录

- API 可查性修正（9.0.1 operator.h）：UpdateInputDesc/UpdateOutputDesc 返回 graphStatus（可查错）；SetAttr/SetInput/Graph::SetInputs/SetOutputs 链式不可查（skill 已修正旧结论）
- 探针数据纪律：链式随机 matmul 对拍需权重 std ~0.01（增益/对 = std_w²·√(k·n)）；幅值爆炸 → fp16 饱和 → 双路径 ±65504 异号假性分歧（131008/1616）
- 开放项（C2）：ApplyRotaryPosEmb 入图编译拒（layout attr/表形状未验）；bias 加法未入图（Add 广播或 MatMulV2 bias 口待验）
- 跨日 bench 波动带：matmul 4.649-4.94（同 chip 不同进程 ±5%），零税结论稳定
