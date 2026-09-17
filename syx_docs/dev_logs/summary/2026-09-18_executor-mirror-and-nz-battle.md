# 2026-09-18：executor 镜像完成 + 大 matmul NZ 战役（未结，排查现场归档）

## 本段完成

1. **B 阶段（executor 层函数镜像）完整**：`pi05/ascend_executor.rs` 四函数（language/vision/action/patch_embed）全部编译 + `AscendRopeCache`（Arc 表快照解借用）+ `aq::` 错误桥模块（46 处 aclnn 调用统一 core Error）+ ada-norm（ones-gamma + row_replicate 物化 (1+style)，因 mul 拒绝零步长广播）+ **BSH 布局 PFA**（`[tokens, hidden]` 线性域直通 attention，零 transpose，GQA 走 num_kv_heads）
2. **真权重路径首次真机串联**（`ascend_layer_smoke.rs`）：随机 host 权重 → `Bf16LinearWeights::from_host`（走 Backend::to_device，bf16→f16 免费）→ 输入上设备 → 层内前向。**前 3 个算子（AddRmsNorm 等）真机跑通**；顺带抓出 qkv bias 未按 q/k/v 切片的真 bug（已修）
3. **NZ 战役证据链**（详见 roadmap 卡点节）：大 ND matmul MTE 越界 / WeightNz 310P 不支持 / FormatCast desc 玄学 → host 重排实现已入库

## 下一轮排查现场（第二波实验后更新）

**第一波三假设已全部执行完**（转置 stride 假设最有价值），新证据链：

| 实验 | 结果 |
|---|---|
| probe 独立跑 plain b（生产 shape） | ✅ 4.9e-4——推翻"大 shape 必崩" |
| probe 前置 AddRmsNorm + plain b | ❌ 数值错 0.79（不崩但读错数据）——**AddRmsNorm 状态污染** |
| probe 前置 AddRmsNorm + 转置 b | ✅ 4.9e-4——转置路径免疫且正确（**aq::matmul 已切此路径**） |
| ascend_layer_smoke 全序列 + 转置 b | ❌ 仍 507015，kernel `MatMulV2_NZ_ND_false_true`——**第二层差异存在** |

**下一轮**（详见 roadmap）：smoke 瘦身二分第二层差异（候选：from_host 上传 / zeros 缓存 / rope pos-gather / PFA / kv_bias d2h-h2d）；torch_npu 日志对照 desc；AddRmsNorm 输出 desc 污染源排查。

## 本段坑档（部分已入 skill）

- `Weight NZ is unsupported by the current SOC [Ascend310P]`——头文件不写，设备日志才说
- aclnnNpuFormatCast 的 dst desc 要求 ori_shape 语义（公开 aclCreateTensor 表达不了），参数完全正确仍 161002
- DeviceBuffer 无 Clone（raw ptr + Drop）；所有权靠 Arc 或调用顺序重排
- add_rms_norm 返回 (y, rstd) 元组——`.0` 别忘

## 环境/工具增量

- 新 example：`ascend_layer_smoke`（apxinf-model，`--features ascend`）；ops_smoke 12 项全绿
- `AscendCaches { rope, nz }` 合并缓存贯穿层函数
