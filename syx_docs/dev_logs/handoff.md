# Handoff（2026-09-19 C1 收官 / C2 开工前夜，compact 用）

## 状态一句话

**C 路线 C1 四项全部完成**（①ge_builder FFI 1691df9 ②转置布局零代价 ③PFA GE IR 契约 ④单层全序 GE 化 7de49c7）：单层 GEMMA_2B language layer 对拍 eager **0.00000**、bench **10.28 vs 18.06 ms/layer（1.76×）**，外推全模型 ~380ms ≈ 验收线。陷阱知识已回填 ge-offline-om skill（#8-11）。**下一步 = C2 三段 OM 全量**（vision+embed 27 层 / prefix 18 层 / flow 18 层×10 步单 OM，+ OM 缓存落盘 + 全深度 bench → C3 验收线判定）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**C2 施工面**（三段 OM 的切分与执行模型：flow 10 步单 OM 执行 10 次、noise 走外部输入每步换绑定；OM 缓存按 (shape 签名, 引擎版本) 落盘 save/load 已备；全深度 bench → C3 判定 ≤378ms → M3）；**ge_builder FFI 完整使用面**（GeGraph::begin/add_data/add_op/set_input_desc/set_output_desc/set_attr_*/link/**link_out（多输出算子必用）**/graph_inputs/graph_outputs/**graph_outputs_idx**/set_nd_input_shape/build/run/save/load + IO introspection；init 在 aclInit 之前；APXINF_GE_BUILDER_LIB 覆盖路径）；**单层模板**（ge_layer_probe.rs = C2 每类层的起点：PFA rank-3 [1,m,*]→Squeeze(axis=0) 桥→2-D mm 流；AddRmsNorm+zeros；GeluV2 approximate="tanh"；Add/Mul x1/x2/y；GEB_SUB 1-9 编译冒烟矩阵）；**C1 战果数据**（对拍 0.00000 / 10.28 vs 18.06 ms/layer / matmul 4.649-4.94 波动带 / 转置打平）；**C2 开放项**（ApplyRotaryPosEmb 入图编译拒——layout attr/表形状未验，试 layout=1/BNSD 或 dump 对比；大图编译时长未知 ~2000 op；bias 加法未入图——Add 广播或 MatMulV2 bias 口待验）；服务器三件套（rust 容器 LD_LIBRARY_PATH=ge_builder build+CANN lib64 + PYTHONPATH 追加 + ASCEND_RT_VISIBLE_DEVICES=5；tar 同步后必须 touch）；子模块双仓两步提交（push 用 fork）。丢弃：本轮编译二分的逐轮过程（sub1-9 矩阵保留在例程里，结论已回填 skill 陷阱表 #8-11 + roadmap C1-④ 节）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 C2 三段 OM 全量**（C1 已全部完成见 roadmap C 路线节 ✅ 段；构图陷阱在 ge-offline-om skill 陷阱表 #8-11，先读）。第一动作：以 `apxinf/crates/apxinf-model/examples/ge_layer_probe.rs` 的单层模板为起点写三段 OM 构造器——① vision 段（SigLIP 层：LayerNorm 版 norm + 无 rope + batch PFA，注意 vision 层是 LayerNorm 语义不是 rms，GE 用 LayerNorm；vision PFA 是 batch 窗口注意）+ embed 段；② prefix 段（18 层 language 全序 × C1 模板串行 + KV 输出绑定）；③ flow 段（18 层 + euler，noise/time 外部输入）。每段独立 OM（GeGraph 多模型槽已备），先逐段编译冒烟 + 段内对拍（eager 全深度已有），再串三段全深度对拍 + bench。权重从 NzCache 转置布局直连（transpose_x2 零代价已证）。环境：rust 容器三件套 + tar 后 touch。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_c1-complete-ge-layer-parity-176x.md（新文件：C1 四项收官——ge_builder FFI/转置零代价/PFA 契约/单层 GE 化对拍 0.00000 + 1.76×，陷阱 #8-11 回填 skill）
