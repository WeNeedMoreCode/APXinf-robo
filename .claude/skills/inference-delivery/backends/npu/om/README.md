# OM 离线推理路径

编排完整的昇腾 OM 部署任务。本文件是方法论路由层，描述"做什么、什么顺序、什么条件"。遇到具体技术步骤时，按指引读取对应的 Skill 或 references/。

## 相关 Skill 与读取规则

到达对应阶段时，**读取对应文件**获取执行细节：

| 阶段 | 读取 |
| --- | --- |
| ONNX 导出调试 / ATC 问题 | Read [../onnx-debug/README.md](../onnx-debug/README.md) |
| 评估脚本适配 / OM 接回 / 源码分析 | Read [references/om-eval-adapt.md](references/om-eval-adapt.md) |
| ATC 参数 / 动态策略 | Read [references/PARAMETERS.md](references/PARAMETERS.md) |
| 精度门控标准 | Read [../onnx-debug/README.md](../onnx-debug/README.md) 的"步骤 7"部分 |
| CANN 环境速查 | Read [../references/cann_env.md](../references/cann_env.md) |
| `107003` / `stream not in current ctx` / OM+torch_npu 混用 | Read [references/CONTEXT_MANAGEMENT.md](references/CONTEXT_MANAGEMENT.md) |
| 图化后端到端仍慢 / 图外小算子串 / 跨板性能差异归因 / 考虑搬 CPU 或 CANN 发射开关 | Read [../references/LAUNCH_OVERHEAD.md](../references/LAUNCH_OVERHEAD.md)（跨路径公共文件） |

不要一次性加载所有 Skill，只在到达对应阶段时才读取。

## 核心设计原则

| 原则 | 说明 |
| --- | --- |
| 大图优先 | 围绕交付场景寻找最大连续 tensor 计算边界；小图拆分必须有大图失败或重规划证据 |
| 图侧主策略唯一 | 单个 OM / 单次 ATC 只选一种输入形态策略：static / dymbatch / dymhw / dymdims / dymshape |
| 输出保真 | 替换点原始输出全集先记录；下游会消费的输出必须由 OM 或原始实现真实提供 |
| Context 隔离 | 混用 .om 与 torch_npu 时必须做 context 隔离，防止互相踩踏 |

详细说明见 [references/core-principles.md](references/core-principles.md)。

## 进度跟踪

```
部署进度：
- [ ] 步骤 0：任务启动（锁定信息、决定起点）
- [ ] 步骤 1：源码分析与候选规划
- [ ] 步骤 2：环境准备
- [ ] 步骤 3：ONNX 导出与 ATC 转换
- [ ] 步骤 4：边界重评估（按需触发）
- [ ] 步骤 5：子图级验证
- [ ] 步骤 6：接回原始推理流程
- [ ] 步骤 7：端到端验证与交付
```

## 步骤 0：任务启动

进入任何步骤前，先锁定以下信息（缺失则先补齐）：

| 信息 | 来源 |
| --- | --- |
| 模型源码或工程路径 | 用户提供 |
| 权重路径或下载来源 | 用户提供 |
| 目标 SoC | 用户提供 |
| CANN / Python / ONNX / ATC 环境 | 环境检测 |
| 用户真正关心的推理入口 / 本次适配场景 | 用户确认 |
| 是否需要接回原始工程 | 用户确认 |
| 是否已有可复用 ONNX | 用户确认 |

锁定后决定起点：有源码 → 从步骤 1 开始；只有现成 ONNX → 完成步骤 2 后进入步骤 3。

## 步骤 1：源码分析与候选规划

**目标**：锁定真实推理入口、候选全集、首批候选和图侧策略。

源码分析命令 → Read [references/om-eval-adapt.md](references/om-eval-adapt.md) 的"源码分析速查命令"部分。

必须回答：
- 用户真正调用的入口是什么
- 该场景能固定哪些业务维度
- 哪些代码属于控制面、状态管理、前处理、主链重计算、后处理
- 候选全集是什么，首批优先形成最大连续主链大图
- 每个候选的图侧主策略初判（static / dymbatch / dymhw / dymdims / dymshape）

候选枚举规则见 [references/CANDIDATE_RULES.md](references/CANDIDATE_RULES.md)。

## 步骤 2：环境准备

**目标**：确认 CANN、Python、ONNX 工具链、ATC 可用。

环境速查 → Read [../references/cann_env.md](../references/cann_env.md)。

门控：环境检查通过后才可进入步骤 3。

## 步骤 3：ONNX 导出与 ATC 转换

**目标**：获取 ONNX、优化、ATC 转换产出 `.om`。

ONNX 导出调试 → Read [../onnx-debug/README.md](../onnx-debug/README.md)。ATC 参数 → Read [references/PARAMETERS.md](references/PARAMETERS.md)。

导出时优先复用项目已有导出入口。临时 wrapper 只能做输入整理、输出暴露和契约对齐，不得改业务语义。

导出协作规则见 [references/ONNX_EXPORT_RULES.md](references/ONNX_EXPORT_RULES.md)。

## 步骤 4：边界重评估（按需触发）

**触发条件**：仅在导出/ATC/验证/接回暴露边界问题时进入。

当出现以下情况时触发：
- 大图导出或 ATC 失败集中在局部结构
- 切分导致过多碎图
- 状态语义或输出契约接回困难
- 端到端性能瓶颈来自切分边界

必须先判断当前问题更适合局部修复、合并前后图、重新切边界，还是保留原始实现。

## 步骤 5：子图级验证

**目标**：确认 `.om` 可稳定运行、ONNX vs OM 输出对齐。

精度验证标准 → Read [../onnx-debug/README.md](../onnx-debug/README.md) 的"步骤 7：精度验证标准"部分。

验证门控标准见 [references/validation-gates.md](references/validation-gates.md)。

子图验证后的流程判定：
- **契约不一致**：不得接回，回步骤 3 修复
- **契约一致且数值通过**：进入步骤 6 接回
- **契约一致但数值不通过**：偏差有合理解释且不影响主输出 → 标记为端到端复查候选，进入步骤 6/7
- **端到端复查不可接受**：回步骤 3 做精度修复，或回步骤 4 重规划边界

## 步骤 6：接回原始推理流程

**目标**：把 `.om` 接回原始工程。

接回规则、OMRunner 模板和 context 隔离 → Read [references/om-eval-adapt.md](references/om-eval-adapt.md) 的"OM 接回核心规则"部分。

用户确认门槛：本步骤会修改用户工程代码，执行前必须向用户说明将修改哪些文件、插入什么桥接代码、主路径与 fallback 策略。

接回后最小验证：
- 接回后链路能跑通
- `.om` 前后的张量语义没有接错
- 输出保真契约未被破坏

## 步骤 7：端到端验证与交付

**目标**：端到端验证并形成交付说明。

验证要求：
- 优先复用官方端到端入口（demo、benchmark、service API）
- 最终精度结论以端到端验证为准
- 性能结论必须基于实测

端到端验证指标 → Read [../onnx-debug/README.md](../onnx-debug/README.md) 的"7.2 端到端验证指标"部分。

**交付内容**：

| 类别 | 内容 |
| --- | --- |
| 可复现路径 | 执行命令和环境要求 |
| 产物 | `.om` 文件、日志、接回后的可运行推理流程 |
| 路径说明 | 主路径与 fallback、每步是 `.om` / 原始实现 / `torch_npu` |
| 混合 runtime | context 恢复方式和最小验证结论 |
| 功能状态 | 每个入口的验证状态 |
| 未支持功能 | 后续候选、未支持原因、风险 |
| 性能 | 端到端验证结果 |
| 风险 | 未完成项和已知风险 |

## 失败回跳

| 失败类型 | 回跳目标 |
| --- | --- |
| 环境不可用 | 留在步骤 2 |
| 导出、优化、ATC、契约不一致 | 回步骤 3 |
| 契约一致但子图数值不通过且可解释 | 进入步骤 6/7 端到端复查 |
| 部署边界、状态语义、输出保真 | 回步骤 4 |
| 桥接代码、输入整理、输出回填 | 留在步骤 6 |
| 端到端验证暴露边界或性能瓶颈 | 按原因回步骤 3/4/6 |

## 参考资料索引

按需读取，不要一次性全加载：

- [references/core-principles.md](references/core-principles.md) — 核心设计原则详细说明
- [references/validation-gates.md](references/validation-gates.md) — 精度门控标准
- [references/CONTEXT_MANAGEMENT.md](references/CONTEXT_MANAGEMENT.md) — OM + torch_npu 混用时 ACL context 管理（107003 排查、save/restore 时序、OMRunner 封装）
- [references/CANDIDATE_RULES.md](references/CANDIDATE_RULES.md) — 候选枚举规则
- [references/ONNX_EXPORT_RULES.md](references/ONNX_EXPORT_RULES.md) — ONNX 导出协作规则
- [references/ATC_DYNAMIC_STRATEGIES.md](references/ATC_DYNAMIC_STRATEGIES.md) — 动态策略选择
- [references/PARAMETERS.md](references/PARAMETERS.md) — ATC 参数参考
- [references/AIPP_CONFIG.md](references/AIPP_CONFIG.md) — AIPP 配置（仅在图像前处理准备下沉时读）
- [references/CANN_VERSIONS.md](references/CANN_VERSIONS.md) — CANN 版本与环境基线
- [references/INFERENCE.md](references/INFERENCE.md) — OM 推理与验证
- [references/FAQ.md](references/FAQ.md) — 常见问题排查
- [references/SOURCE_ANALYSIS.md](references/SOURCE_ANALYSIS.md) — 源码分析命令参考
- [references/EVAL_ADAPTATION_CHECKLIST.md](references/EVAL_ADAPTATION_CHECKLIST.md) — 评估脚本适配检查清单
- [references/om-eval-adapt.md](references/om-eval-adapt.md) — 评估脚本适配清单、OM 接回规则、源码分析命令、精度比对
- [references/OUTPUT_TEMPLATES.md](references/OUTPUT_TEMPLATES.md) — 输出模板（按需）
- [references/DEPLOYMENT_TEMPLATE.md](references/DEPLOYMENT_TEMPLATE.md) — 部署文档模板（按需）
