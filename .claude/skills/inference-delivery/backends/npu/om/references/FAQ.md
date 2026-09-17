# ONNX -> OM 常见问题

本文件只记录当前 Skill 需要稳定记住的问题类型和处理方向，不保留旧项目流水账。

命令示例中的 `$SKILL_DIR` 表示本 Skill 安装目录，例如 `/path/to/ascend-onnx-atc-pipeline`。

## 1. ATC 失败后要不要直接放弃当前子图

不要。

至少先完成以下检查：

1. 输入形态是否选错
2. ONNX 输入输出契约是否被优化步骤改写
3. graph output 是否残留不合理动态 shape
4. 是否是局部实现不友好，而不是整张图都不能转
5. 当前部署边界是否过大或过碎

## 2. ONNX 已经能导出，为什么 ATC 还会失败

常见原因不是“图不存在”，而是“图不适合当前 ATC 输入条件”：

- 输入 shape 策略不对
- 中间 shape / dtype / layout 信息不完整
- 某些局部结构对导出友好，但对 ATC 不友好
- 优化后产物改变了输入契约
- 切图边界不合理

处理顺序：

1. 先看 `inspect_onnx_io_shapes.py`
2. 再看 `optimize_onnx.py` 生成的候选产物
3. 再按 `auto_optimizer -> onnxslim -> original` 逐个尝试
4. 最后才决定改边界或回退

## 3. 优化后的 ONNX 为什么还要重新检查输入输出

因为优化步骤可能改变输入形态或图签名。

典型风险：

- 可选输入被折叠
- 某些输出被清理或改名
- graph output 仍保留动态符号
- 输入已经固定，但输出 shape 标注没有同步固定

建议先执行：

```bash
python3 -u "$SKILL_DIR/scripts/inspect_onnx_io_shapes.py" \
  --model /path/to/model.onnx
```

## 4. 输入已固定或有动态 profile，但输出还是动态 shape，怎么办

先确认“真实运行输出是否固定”，不能只看 ONNX 文本。

如果需要判断真实输出是否固定，先做 probe，不在 Workflow 3 修改 ONNX：

```bash
python3 -u "$SKILL_DIR/scripts/inspect_onnx_io_shapes.py" \
  --model /path/to/model.onnx \
  --probe-outputs
```

如果输入是动态的，可以重复传入 `--probe-shape-profile` 覆盖目标动态轴：

```bash
python3 -u "$SKILL_DIR/scripts/inspect_onnx_io_shapes.py" \
  --model /path/to/model.onnx \
  --probe-outputs \
  --probe-shape-profile "input:1,3,1024,1024" \
  --probe-shape-profile "input:4,3,1024,1024"
```

Workflow 3 只形成结论，不物化 patched ONNX。脚本 probe 结果用于判断 graph output shape 是否可由 Workflow 4 的 `optimize_onnx.py` 在优化前补全。

输出 shape 是否可补全按证据判断，不按任务类型一刀切。固定输入 shape 只说明输入张量维度稳定，不自动证明输出 shape 与数据内容无关；若静态输入或代表性 profile 证明输出维度由模型结构、配置或 profile 决定且多次实跑稳定，可以补全为固定维，否则不修改。`dymdims` 应覆盖计划使用的档位；`dymshape` 若没有可验证的动态轴覆盖证据，只能记录观察结果，不能强行写死。

Workflow 3 如果已经执行 probe 并形成结论，Workflow 4 按结论执行：需要 patch 时用同一组 profile 调用 `optimize_onnx.py`，由优化脚本修改 `original.onnx` 副本；无需 patch 或 patch 不安全时调用 `optimize_onnx.py --skip-output-shape-probe`，避免优化脚本对静态输入的动态 graph output 自动 probe / patch。这一步仍只是补全 output shape 标注，不负责重新固定 input shape。

## 5. `onnxslim` 和 `auto_optimizer` 都必须成功吗

不是。

当前 Skill 的默认顺序是：

1. 先保留 `original.onnx`
2. 再生成 `onnxslim.onnx`
3. 再尝试 `auto_optimizer.onnx`
4. 最终按 `auto_optimizer -> onnxslim -> original` 做 ATC 回退

因此某一步失败，不代表整个流程失败。

但“命令执行成功”不等于“候选可用”。候选至少还应满足：

- ONNX checker 通过
- graph output 没有悬空
- ONNX Runtime 加载校验通过

如果候选连基础结构都不满足，应直接剔除，不要继续拿去 ATC。

## 5.1 `auto_optimizer` 为什么没有进入 ATC

当前规则以 `optimization_summary.json` 中的候选可用性为准：

1. `onnxslim` 和 `auto_optimizer` 都需要通过结构检查、graph output 悬空检查和 ONNX Runtime 加载校验
2. `auto_optimizer` 若被标记为 `success: true`，统一 ATC 脚本会按默认优先级先尝试它
3. `auto_optimizer` 若被标记为 `success: false`，统一 ATC 脚本会跳过它并回退到 `onnxslim` 或 `original`

也就是说：

- `auto_optimizer` 不能因为“结构合法但 ORT 未通过”而直接进入 ATC
- 只有复检通过的候选，才允许进入 ATC
- 真正生效的最终选择以 `atc_selection.json` 为准

如果某次实际执行中直接从 `onnxslim` 开始，优先检查：

1. 是否根本没走 `pipeline_onnx_to_om.py`
2. 是否 `optimization_summary.json` 已把 `auto_optimizer` 标成 `success: false`
3. 是否人为用 `--candidate onnxslim` 覆盖了默认顺序

## 5.2 `onnxslim` 产物如果 graph output 悬空怎么办

先看是不是优化前图里存在 `Identity` 别名关系。

例如某些多输出 encoder 或中间特征导出场景里，原图可能是：

- `vision_features -> Identity -> backbone_fpn_2`

而 `onnxslim` 后变成：

- 图里只剩 `backbone_fpn_2`
- 但 `graph.output` 还保留 `vision_features`

这种情况不是“动态 shape 没推出来”，而是 graph output 已经失效。应先修复输出别名或直接剔除该候选，不能继续带着坏图做 ATC。

## 6. 什么情况下应该重规划部署边界

出现以下任一情况就该重看边界：

- 大图导出失败，但问题集中在局部
- 大图 ATC 失败，且失败点说明切图位置不合理
- 为了过导出被迫拆出多个轻量碎图
- 相邻小图主要只是简单连接、投影、`reshape` 或轻量卷积
- 接回主链后发现输入契约和状态语义难以对齐
- 功能已跑通，但性能瓶颈来自图间搬运

## 7. 主路径应该怎么安排

默认原则：

- 优先 OM
- 再考虑 `torch_npu`
- CPU 只做最后兜底

但不要为了"全 OM"把链路切得过碎。主路径必须首先满足完整流程可运行、输入契约可对齐、状态语义不被破坏。

## 8. `.copy_()` 导致 ONNX 导出失败

**报错信息**：
```
RuntimeError: Argument passed to at() was not in the map.
at _C._jit_pass_onnx_remove_inplace_ops_for_onnx

# 或更直接的：
UnsupportedOperatorError: Exporting the operator 'aten::copy'
```

**根因**：`tensor.copy_(other)` 产生 `aten::copy` 算子，ONNX 不支持。

**典型场景**：PyTorch wrapper 函数中为了传出结果而使用 `.copy_()` 写入预分配 buffer。

**修复**：改为直接返回结果，不要用 `.copy_()`。

> 注意：这个报错指向 "inplace ops"，容易让人误以为是 `ReLU(inplace=True)`。但排查发现常见 inplace 操作（`ReLU(inplace=True)`、`y -= 0.5`）在单独测试中都能正常导出。排查时不要被报错信息误导。

## 9. 模型内部有 ODE / 动态循环无法导出

**现象**：包含 ODE 求解器（如 `scipy.integrate.solve_ivp`）的模型无法整体导出为 ONNX。

**原因**：ODE 求解器的循环次数是动态的（由求解器内部根据误差容忍度决定），ONNX trace 无法处理。

**解法**：将模型拆分为"单步网络"和"外部循环"两部分：单步网络导出为 ONNX/OM，ODE 循环留在 Python 中每步调用 OM 推理。

## 10. OM batch_size 与实际推理数据不匹配

**报错信息**：
```
[ERROR] check i:0 name:roi_rgb in size:2408448 needsize:4816896 not match
```

**根因**：OM 模型的 batch_size 在 ATC 转换时固定，运行时不能改变。但推理时实际 batch 可能小于 OM 期望的 batch。

另外，ONNX 导出时的 batch_size 必须与 ATC 转换时一致。即使设了 `dynamic_axes`，某些内部节点（如 Reshape）的 target shape 可能在导出时固化。

**常见解法**（按优先级）：

1. 推理时严格对齐 OM batch_size（丢掉最后一个不足的 batch，或调整数据组织）
2. ATC 转换时用 `dynamic_batch_size`（复杂模型可能导致导出过大或内存超限）
3. 对输入 padding 到 OM batch_size 的整数倍（LayerNorm 模型可能有精度问题，需实测）

## 11. ATC 静默算错 slice 写回（编译成功、ONNX Runtime 正确、OM 输出错）

**现象**：ATC 编译无任何报错；onnxruntime 跑同一张 onnx 与 eager 逐位一致；但 OM 推理输出大偏差（实测一例 32.5% of |ref|max），且错误位置集中——`clone()` 后按 slice 赋常量的位置（如 one-hot 的 `pos[..., -3] = 1.0`）在 OM 输出里 1 变成了 0（Diffusion-Planner 2026-09-03，Ascend310P3/310P1 类）。

**根因**：`clone() + tensor[..., i] = v` 这类 slice 写回被 trace 成写回型节点，ATC 对该模式的实现在部分 SoC 上 miscompile——**不报错，直接输出错值**。这是"编译成功"三个字最危险的形态。

**定位方法**（两分钟）：把可疑段单独导一张 mini onnx → 同输入下 ort 与 OM 各跑一遍 → 哪路输出差大就是哪段。图内的其他输出（同图正常的那几路）可以先把范围排除到具体函数。

**修复**：函数式重写，消灭写回——切片只读、结果用 `torch.cat` 拼接：

```python
# before (miscompiled):            # after (value-identical, clean):
p = x[:, :, -1, :7].clone()        core = x[:, :, -1, :4]
p[..., -3:] = 0.0                  typ = torch.tensor([1., 0., 0.]).expand(*core.shape[:-1], 3)
p[..., -3] = 1.0                   return torch.cat([core, typ], dim=-1)
```

**通用教训**："onnx 对拍 PASS" 只证明导出正确；ATC 引入的错只有 **OM-vs-eager 对拍**能抓到。对拍链必须覆盖到 OM 层，且判据要包含"常量/one-hot 位置必须逐位"这类结构性检查（zero-viol 检查正是为此）。

