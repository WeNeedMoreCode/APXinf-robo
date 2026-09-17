# 2026-09-18：executor 镜像完成 + 大 matmul NZ 战役（未结，排查现场归档）

## 本段完成

1. **B 阶段（executor 层函数镜像）完整**：`pi05/ascend_executor.rs` 四函数（language/vision/action/patch_embed）全部编译 + `AscendRopeCache`（Arc 表快照解借用）+ `aq::` 错误桥模块（46 处 aclnn 调用统一 core Error）+ ada-norm（ones-gamma + row_replicate 物化 (1+style)，因 mul 拒绝零步长广播）+ **BSH 布局 PFA**（`[tokens, hidden]` 线性域直通 attention，零 transpose，GQA 走 num_kv_heads）
2. **真权重路径首次真机串联**（`ascend_layer_smoke.rs`）：随机 host 权重 → `Bf16LinearWeights::from_host`（走 Backend::to_device，bf16→f16 免费）→ 输入上设备 → 层内前向。**前 3 个算子（AddRmsNorm 等）真机跑通**；顺带抓出 qkv bias 未按 q/k/v 切片的真 bug（已修）
3. **NZ 战役证据链**（详见 roadmap 卡点节）：大 ND matmul MTE 越界 / WeightNz 310P 不支持 / FormatCast desc 玄学 → host 重排实现已入库

## 下一轮排查现场（按嫌疑排序）

**第一优先：mat2 转置 stride 假设**——torch linear 权重 [out,in]，torch_npu 喂 aclnnMatmul 的 mat2 很可能是 **[N,K] shape + 转置 stride（[1,K]）**；我们传 [K,N] row-major。试法：同一块权重内存，desc 用 shape [2560, 2048]、stride [1, 2048]，喂现有 aclnnMatmul。一处改动即可验证。

**第二**：8.5.1 容器开日志跑 `torch.randn(8,2048,fp16,npu) @ torch.randn(2048,2560,...)`，日志抓 kernel 名 + 参数 dump = ground truth（上次被中断）。

**第三**：cubeMathType 0/2 变体。

## 本段坑档（部分已入 skill）

- `Weight NZ is unsupported by the current SOC [Ascend310P]`——头文件不写，设备日志才说
- aclnnNpuFormatCast 的 dst desc 要求 ori_shape 语义（公开 aclCreateTensor 表达不了），参数完全正确仍 161002
- DeviceBuffer 无 Clone（raw ptr + Drop）；所有权靠 Arc 或调用顺序重排
- add_rms_norm 返回 (y, rstd) 元组——`.0` 别忘

## 环境/工具增量

- 新 example：`ascend_layer_smoke`（apxinf-model，`--features ascend`）；ops_smoke 12 项全绿
- `AscendCaches { rope, nz }` 合并缓存贯穿层函数
