# 边界判断详解

各文档之间容易混淆的边界，详细对比 + 案例。

---

## plans/ vs designs/

| 维度 | `plans/` | `designs/` |
|------|---------|-----------|
| 时间 | 未来 | 现在 |
| 视角 | 阶段规划 | 技术实现 |
| 核心问题 | 做什么 / 何时做 | 怎么做 |
| 范围 | 跨子系统 / 整个 Phase | 单子系统 |
| 更新触发 | 阶段调整 | 实现变化 |
| 完成后 | 归档（成为历史） | 保留（living doc） |

### 判断流程

3 个 yes/no：
1. 这是讲技术实现还是讲阶段计划？技术→designs，计划→plans
2. 5 年后还有用吗？有用→designs，没用（阶段早过了）→plans
3. 跨多个子系统吗？单→designs，跨→plans

### 案例

| 内容 | 放哪 | 理由 |
|------|------|------|
| "backtest 引擎用 close-to-close 模型" | designs | 技术实现 |
| "Phase 2.1.b 加 PE/PB/PS 估值特征" | plans | 这阶段做什么 |
| "shift(1) 防未来函数的实现" | designs | 技术实现 |
| "Phase 2.1.c 要做 MLStrategy" | plans | 未来计划 |
| "为啥选 LightGBM 不选 Transformer" | **decisions**（不是 plans 不是 designs） | 决策记录 |

### 典型错误

`designs/ml_pipeline.md` 包含 "Phase 2.1.c / 2.2 / 2.3 未来扩展" 段 —— 这是 plans 性质，**拆出去**到 `plans/phase2_ml_roadmap.md`。

---

## decisions/ vs designs/

| 维度 | `decisions/` | `designs/` |
|------|-------------|-----------|
| 核心问题 | 为啥这么做（why） | 怎么做（how） |
| 内容 | 决策 + 备选 + 理由 | 实现细节 + 算法 |
| 触发 | 关键决策（数据源、模型选型、架构） | 设计实现 |
| 时间 | 决策点（freeze） | 持续维护（living） |

### 案例

| 内容 | 放哪 |
|------|------|
| "为啥用 Tushare 不用 akshare" | decisions |
| "Tushare API 怎么调" | designs 或 references |
| "为啥自写 backtest 不用 vectorbt" | decisions |
| "backtest 引擎的 cost model 怎么算" | designs |
| "为啥 LightGBM 起步不上 RL" | decisions |
| "LightGBM 的特征工程怎么设计" | designs |

### 典型错误

`designs/backtest_engine.md` 包含 "为啥自写不用 vectorbt" 段 —— 这是 decision 性质，**拆出去**到 `decisions/002-self-write-backtest.md`，designs 只引用。

---

## setup.md vs cookbook.md

| 维度 | `setup.md` | `cookbook.md` |
|------|-----------|--------------|
| 频率 | 一次性（新机器 / 新 session） | 重复（每次遇到类似问题） |
| 内容 | 环境配置（API key / 依赖 / IDE） | ad-hoc 脚本片段（调试 / 检查） |
| 触发 | 配环境时 | 解决具体小问题时 |

### 案例

| 内容 | 放哪 |
|------|------|
| "如何注册 Tushare token" | setup |
| "如何查看模型某层权重" | cookbook |
| "如何装 Python / uv" | setup |
| "如何快速看 xlsx 某列 unique 值" | cookbook |

### 典型错误

setup.md 塞了"调试 ML 模型的 5 个技巧" —— 这是 cookbook 性质。setup 应该聚焦"环境搭起来"。

---

## summary/ vs handoff.md

| 维度 | `summary/X.md` | `handoff.md` |
|------|---------------|-------------|
| 时间 | 过去（已发生） | 现在 + 近未来 |
| 形式 | 追加（每次一篇） | 覆盖（单文件） |
| 触发 | 用户主动让写 | 每次 /compact 前 |
| 写完状态 | 冻结（历史快照） | 持续更新（直到任务完成） |

### 案例

| 内容 | 放哪 |
|------|------|
| "今天完成了 fetch_pool.py" | summary |
| "明天要做 train_model.py" | handoff（短期）/ plans（长期） |
| "这周 Phase 2.1.b 完成的事" | summary |
| "当前在重写 architecture.md，下一步是 decisions" | handoff |

### 典型错误

summary 末尾写 "下一步要做 X、Y、Z" —— summary 写完即冻结，但 "下一步" 会随任务推进变化。下次写 summary 时旧 "下一步" 还在，**会混淆**。"下一步" 去 handoff.md。

---

## chat_exports/ vs summary/

| 维度 | `chat_exports/` | `summary/` |
|------|---------------|-----------|
| 内容 | raw 对话原汁原味 | 提炼后的回顾 |
| 长度 | 长（完整对话） | 短（聚焦关键） |
| 价值 | 应急回溯（万一 summary 漏了细节） | 日常复盘 |

### 案例

- `/compact 前导出整个对话` → chat_exports
- `总结今天做的事` → summary

### 典型错误

把 chat_exports 当成 summary 用 —— 太长，关键信息淹没。chat_exports 是 raw 备份，summary 是提炼。

---

## references/ vs designs/

| 维度 | `references/` | `designs/` |
|------|--------------|-----------|
| 来源 | 外部（论文 / 规范 / API 文档） | 项目自己 |
| 形式 | 学习笔记 | 设计文档 |
| 触发 | 调研时 | 实现时 |

### 案例

| 内容 | 放哪 |
|------|------|
| "PE-TTM 计算公式定义" | references |
| "我们项目 PE-TTM 怎么用" | designs |
| "Transformer 论文笔记" | references |
| "我们是否用 Transformer" | decisions |
| "我们的 Transformer 实现细节" | designs |

### 典型错误

把外部公式 / 论文塞进 designs —— designs 应该聚焦"项目自己怎么实现"，外部知识去 references 引用。

---

## 综合判断流程图

```
有内容要写，问自己：

是讲 why 吗？
├─ 是 → decisions/00X-*.md
└─ 否 ↓

是讲 how（技术实现）吗？
├─ 是 → designs/X.md
└─ 否 ↓

是讲 what（做什么）吗？
├─ 是 → 是当前任务吗？
│       ├─ 是 → handoff.md
│       └─ 否 → plans/X.md
└─ 否 ↓

是讲已发生的事吗？
├─ 是 → summary/X.md
└─ 否 ↓

是环境配置吗？
├─ 是 → setup.md
└─ 否 ↓

是一次性操作片段吗？
├─ 是 → cookbook.md
└─ 否 ↓

是外部知识吗？
├─ 是 → references/
└─ 否 ↓

是术语吗？
└─ glossary.md
```
