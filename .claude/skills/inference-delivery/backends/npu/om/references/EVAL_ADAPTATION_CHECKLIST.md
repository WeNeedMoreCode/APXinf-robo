# 评估脚本 OM 适配检查清单

当接回目标是评估/测试脚本时，除了通用的接回流程，还需要额外关注以下检查项。

## 1. 设备放置

OM session 的输入输出是 numpy，内部自行管理 NPU。接回后的外部代码（聚合、排序、指标计算）尽量用 CPU tensor：

```python
# OM 路径：转 CPU tensor 做聚合
score_pred_results = torch.from_numpy(score_pred_results)  # 默认 CPU

# 不要不必要的 .to(device)
score_pred_results = torch.from_numpy(score_pred_results).to(cfg.device)  # ❌
```

tensor 初始化也需要按路径区分：

```python
device = cfg.device if not is_om_model else 'cpu'
pose = torch.zeros(length, pose_dim, device=device)
```

## 2. 数据类型

- OM session 输入输出是 numpy。如果后续计算链路也是 numpy 原生的（如 `scipy.integrate.solve_ivp`），不要中间转 tensor 再转回来
- 确认完整调用链后再决定数据类型
- numpy 用 `.reshape()` 而非 `.view()`

```python
# OM 路径：直接用 numpy
pts_feat_repeated = pts_feat.reshape(bs * cfg.eval_repeat_num, -1)

# 不要转 tensor 再 view
pts_feat_repeated = torch.from_numpy(pts_feat).view(...)  # ❌
```

## 3. torch_npu 导入

如果评估脚本同时支持 PTH（在线推理）和 OM（离线推理）两条路径：

```python
if not is_om_model:
    import torch_npu
    ...
```

OM 路径不需要 `torch_npu`。OM wrapper 的 import 也不应依赖 `torch_npu`。

## 4. DataLoader 与批次处理

- `__getitem__` 返回的 Python bool 经过 DataLoader collate 后会变成 `tensor([False, False, True, ...])`。检查时必须用 `.any()` / `.all()` / `.item()`
- 跳过异常数据不能导致主循环提前退出：跳过后需检查是否还有未处理数据，有则 `continue` 而非 `break`

## 5. 性能统计

如果同时适配 single 和 tracking 两种评估模式，确保性能统计输出格式（时间、精度字段名、段落结构）保持一致，便于横向比较。
