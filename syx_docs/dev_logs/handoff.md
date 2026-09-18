# Handoff（2026-09-19 C1-④ 开工前，compact 用）

## 状态一句话

**C 路线 C1 垫脚石 ①②③ 完成（1691df9 双仓已推）**：ge_builder 通用构图 FFI 全链绿（Rust 定义模型 → FFI → 编译 → 对拍 0.00009 → bench 4.649 ms/matmul）；转置权重布局（transpose_x2）零代价坐实；PFA GE IR 定案（`PromptFlashAttention` 全契约 + 310P 预编译 kernel）。**下一步 = C1-④：单层 language layer 全序 GE 化双路径对拍 + 单层 OM bench vs ACLGraph**（计划见 roadmap C 路线节）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**C1 剩余工作与 ge_builder 使用面**（④ 单层 GE 化：qkv→rope 组合→PFA→proj→rms/ada→gate_up→GeluV2·Mul→down→residual 全序用 geb_* 声明、双路径对拍容差 ~0.02、单层 OM bench vs ACLGraph；之后 C2 三段 OM）；**ge_builder FFI 面**（GeGraph::begin/add_data/add_op/set_input_desc/set_output_desc/set_attr_*/link/graph_inputs/graph_outputs/set_nd_input_shape/build/run/save/load + num_inputs/input_size/input_dims；APXINF_GE_BUILDER_LIB 覆盖 .so 路径，默认 /data/apxinf/ascendc/ge_builder/build/libge_builder.so；ge_builder::init 必须在 aclInit/SetDevice 之前）；**C1-①②③ 战果数据**（对拍 0.00009/4.649ms；转置 4.930 vs 4.941 打平；PFA 13 输入 8 attrs 契约 + apply_rotary_pos_emb/incre_flash_attention 附加发现；API 可查错性修正：UpdateDesc 返回 graphStatus、SetInput/SetAttr/SetInputs 链式不可查）；**探针数据纪律**（链式 matmul 对拍权重 std~0.01，增益=std_w²·√(k·n)，饱和=假分歧）；服务器三件套与 tar+touch 纪律；子模块双仓两步提交（push 用 fork）。丢弃：本轮 ge_builder 调试逐轮过程（编译错误迭代/探针幅值二分——结论已全部记入 roadmap C1 节与代码注释）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 C1-④ 单层 language layer GE 化**（C1-①②③ 已完成：ge_builder FFI + 转置布局 + PFA IR，见 roadmap C 路线节 ✅ 段；GE 构图知识在 ge-offline-om skill）。第一动作：在 `apxinf/crates/apxinf-ascend/examples/` 新建 `ge_layer_probe.rs`——用 `ge_builder::GeGraph` 声明单个 language layer 全序（qkv MatMulV2 → rope 组合（GatherV2/Mul/Add 或直接试 `ApplyRotaryPosEmb`——310P 预编译清单里有）→ `PromptFlashAttention`（attrs: num_heads/scale_value/input_layout=BSH；可选输入 gen_placeholder 可不接）→ proj → ada-norm 组合（Add/Mul/RMSNorm 内置算子）→ gate_up → GeluV2·Mul → down → residual Add），编译 → 与 eager aclnn 同输入对拍（容差 ~0.02，参照 pi05 ascend smoke）→ bench 单层 OM vs 同层 ACLGraph。PFA 端口名以 opp kernel json 为准（roadmap C1-③ 段记了全契约）。环境：rust 容器，`LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:CANN/lib64` + `PYTHONPATH=CANN site-packages` 追加 + `ASCEND_RT_VISIBLE_DEVICES=5`；同步 .rs 后必须 touch。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_c1-stepping-stones-gebuilder-transpose-pfa.md（新文件：C1 垫脚石三项收官——ge_builder FFI 全链 + transpose_x2 零代价 + PFA GE IR 契约）
