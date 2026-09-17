---
name: syx-doc-system
description: 项目文档与日志体系的标准化方案，覆盖文档分类、职责边界、写作时机、/compact 工作流。当用户开始新项目、需要建立文档结构、整理现有项目文档、讨论"这内容该放哪"、规划 /compact 准备、或问 plans/designs/decisions 区别时，请使用此 skill。即使用户没明确说"文档体系"，只要涉及项目组织、文件归类、文档维护、compact 准备、新机器 / 新 session 接手，都应主动参考此 skill。
---

# syx 项目文档与日志体系

一套从实战中沉淀的文档分类与维护方案。

**目标**：让任何项目都有一致的文档结构，新 session / 新人快速接手，关键决策可追溯，/compact 不丢上下文。

## 设计原则

1. **单一职责**：每个文档回答一个核心问题，不混内容
2. **时间维度清晰**：过去 / 现在 / 未来 分开存放
3. **边界明确**：plans ≠ designs ≠ decisions，混淆就漏内容
4. **living doc vs 流水账分开**：技术设计是 living doc（更新内容），开发日志是流水账（追加历史）
5. **summary 三级分层（事实 / 可信推理 / 推测）**：实测对比类内容必须按三层明确标注，避免 AI 通病（把推论当事实污染后续决策）。详见下方"[写作原则](#写作原则)"段

## syx_docs_location 配置（重要）

**所有文档放在哪个根目录，按"项目归属"决定**。

### 判断原则

先问：**这项目是不是你原生开发的？**

- **是**（你从零开发，自己拥有）→ `docs/`
- **不是**（学习 / 参与别人的 repo）→ 必须用独立目录隔离，**避免覆盖原作者的 `docs/`**

非原生项目进一步按新旧分：

- 新项目（约定生效后建的）→ `syx_docs/`（新约定，替代 `syx_records/`）
- 历史项目（约定前已在 `syx_records/`）→ `syx_records/`（保持，不强制迁移）

### 三档对应

| 项目情况 | `syx_docs_location` | 为啥 |
|---------|---------------------|------|
| **你原生开发**（任何时间，如 TapeForward） | `docs/` | 你的项目，社区标配 `docs/` 直接用 |
| **非原生 - 新项目**（学习/参与别人） | `syx_docs/` | 隔离原作者 docs，新约定 |
| **非原生 - 历史项目**（已在 `syx_records/`） | `syx_records/` | 老约定，不迁移 |

**关键区分**：
- 原生 vs 非原生 → 看**项目归属**（是不是你的）
- 非原生里的 syx_docs vs syx_records → 看**时间**（新旧约定）

### 声明位置

项目根的 `CLAUDE.md` 顶部加一行：

```markdown
- **syx_docs_location**: docs/   （或 syx_docs/ 或 syx_records/，按项目实际）
```

### fallback 规则（老项目没声明时）

1. 看项目级 CLAUDE.md 的 `syx_docs_location` 字段 → 用声明的
2. 否则按存在的目录猜：`syx_docs/` → `docs/` → `syx_records/`，第一个存在的就用
3. 都没有 → 问用户："这项目是你原生开发还是参与别人的？目录用啥？"

### 路径约定

本 skill 后文所有路径用 `docs/` 作示例（原生项目最常见），**实际操作时替换为该项目的 `syx_docs_location`**。比如 `docs/designs/X.md`：
- 在 syx_docs 项目里 → `syx_docs/designs/X.md`
- 在 syx_records 项目里 → `syx_records/designs/X.md`

## 11 类文档总览

按"必须 / 推荐 / 可选"三档，新项目按需启用。**类别**列说明该文档何时更新（living doc / compact 触发 / 手动），具体规则见下方[更新时机](#更新时机重要)段。

### 🔴 必须（最小可行集）

| 文档 | 用途 | 类别 |
|------|------|------|
| `README.md` | 怎么导航 + 项目干啥的 | living doc |
| `setup.md` | 怎么搭环境（API key / 依赖 / IDE） | living doc |
| `designs/` | 子系统怎么设计（how） | living doc |
| `dev_logs/summary/` | 时序上做了什么（past） | compact 触发（完整归档）+ 重要测试结果及时记 |
| `dev_logs/chat_exports/` | session 备份 raw | 手动 |

### 🟡 推荐（项目稍复杂时加）

| 文档 | 用途 | 类别 | 加的时机 |
|------|------|------|---------|
| `architecture.md` | 系统组成 / 数据流 | living doc | 子系统 ≥ 3 个 |
| `glossary.md` | 术语表 | living doc | 沟通出现"啥意思" |
| `decisions/` | 为啥做 X 决策（ADR） | living doc | 决策反复讨论时 |
| `plans/` | 长期 roadmap（future） | living doc | 项目跨多 session |
| `dev_logs/handoff.md` | 当前活跃任务 + 立即下一步 | compact 触发 | 频繁 /compact 时 |

### ⚪ 可选（按需启用）

| 文档 | 用途 | 类别 | 加的时机 |
|------|------|------|---------|
| `cookbook.md` | ad-hoc 脚本片段登记 | living doc | 经常写一次性脚本 |
| `references/` | 外部知识 / 规范 / 论文 | living doc | 做领域调研 |
| `dev_logs/run_prints/` | 训练 / 实验运行 stdout 备份（raw）| 手动（tee 存）| 经常跑训练 / 实验，需要跨 session 对比数字 |

## 更新时机（重要）

**三档触发，文档按类型分到不同档**：

| 触发时机 | 哪些文档 | 为啥 |
|---------|---------|------|
| 用户说"更新"（开发中任何时点） | living doc：`designs/` / `decisions/` / `architecture.md` / `plans/` / `setup.md` / `README.md` / `glossary.md` / `cookbook.md` | living doc 是当前实现/设计的镜像，开发中变化就该同步 |
| 用户表示要 compact | `dev_logs/handoff.md` + `dev_logs/summary/` | handoff 是 compact 用的 prompt 生成器，summary 是流水账归档——平时更新要么用不上要么噪声大 |
| 用户自己手动 | `dev_logs/chat_exports/` | Claude 拿不到完整 transcript，由用户 `/export` |

### 关键边界判断

- **"更新文档" ≠ "准备 compact"**：用户说"更新一下文档" / "同步一下 docs" → 只更 living doc，**不动 handoff / summary**
- **表示要 compact 的信号**：用户说"准备 compact" / "更新准备压缩" / "要 /compact 了" / 直接用 `/compact` 命令 → 触发完整流程（含 handoff + summary）
- **模糊时主动确认**：用户说"更新"但没提 compact，Claude 想更 handoff/summary 前先问一句"现在更 handoff/summary 吗？还是只同步 living doc？"

### 用户说"更新文档"时 Claude 怎么做

1. **commit**（可选）：用户让 Claude 代管时先做；用户自管时跳过
2. **同步 living doc**：扫 designs / decisions / architecture / plans / setup / README / glossary / cookbook，有变化的更，没变化的不动
3. **不动 handoff / summary**：除非用户明确表示要 compact
4. **重要测试结果提醒更新 summary**：如果本轮有方案对比测试（如 A vs B 的 IC / 性能 / 准确率对比），主动提醒用户"要不要把对比结果加到 summary？避免等 compact 丢失上下文"
5. **提醒 chat_exports**：如果距上次 export 跨度大，提醒用户 `/export`

### 用户表示要 compact 时 Claude 怎么做（顺序不能反）

1. **commit**（可选）
2. **同步 living doc**（同上）
3. **写 summary**：总结本轮 session 做的工作（不照 commit 写，是 session 工作的简要回顾）
4. **更 handoff**：最后。基于 summary 已归档的边界，剩下"还在干的"才进 handoff
5. **提醒 chat_exports**：让用户 `/export`

### 为啥 handoff / summary 只在 compact 时才更新

- **handoff 是 compact 用的 prompt 生成器**：平时不开 compact 就用不到。频繁更新增加噪声 + 容易跟当前实际状态脱节（"刚写的 handoff 又过时了"）
- **summary 是流水账归档**：每次写要冻结成历史。过早写会跟后续工作脱节——"上次写的 summary 还没接续就又有新工作了"
- **集中在 compact 时一次性写完**：summary 归档"上一段干了啥"，handoff 写"接下来干啥"，边界明确、互不矛盾

### 为啥 summary 必须在 handoff 之前

summary 归档"已完成"，handoff 写"当前在干"。如果先写 handoff，"哪些算完成、哪些还在干"边界没定，handoff 容易跟 summary 矛盾——比如 handoff 写"正在收尾 X"，summary 又把 X 归档为"已完成"，下次 compact 拿到矛盾信息，handoff 毫无意义。

## 各文档定位（含"不该放"反例）

### `README.md`
**导航 + 索引**。讲文档地图、写作约定、为何这么分类。
- ❌ 不该有：具体技术内容（去 designs）
- ❌ 不该有：项目特定细节（去 architecture）

### `architecture.md`
**系统总览**。讲组件图、数据流、模块分层（实际状态）。
- ❌ 不该有：具体算法（去 designs）
- ❌ 不该有：决策推理（去 decisions）

### `setup.md`
**纯环境配置**。一次性的"怎么搭起来"。
- ❌ 不该有：数据源对比（去 decisions）
- ❌ 不该有：术语表（去 glossary）
- ❌ 不该有：踩坑（分散到 designs 对应文档）

### `glossary.md`
**术语表**。领域 / 技术名词解释。
- ❌ 不该有：项目特定 acronym 列表（去 README）

### `cookbook.md`
**ad-hoc 脚本片段登记**。问题 → 关键代码 → 何时用，三段式。
- ❌ 不该有：完整业务脚本（去 `scripts/`）

### `designs/X.md`
**子系统技术 living doc**。讲当前实现 + 设计取舍 + 扩展点。
- ❌ 不该有：未来规划（去 `plans/`）
- ❌ 不该有：决策推理（去 `decisions/`）

### `decisions/00X-*.md`（ADR）
**为啥做这个选择**。决策 + 备选 + 理由。
- ❌ 不该有：实现细节（去 designs）
- ❌ 不该有：阶段性计划（去 plans）

### `references/X.md`
**外部知识**。论文、规范、API 文档笔记。
- ❌ 不该有：项目自己的设计（去 designs）

### `dev_logs/run_prints/X.txt`
**脚本运行 stdout 备份**（raw，原汁原味）。用 `2>&1 | tee dev_logs/run_prints/YYYY-MM-DD_描述.txt` 存。
- ✅ 应该有：训练 / 实验完整 stdout（避免被 `tail` 截断 / 跨 session 回看具体数字）
- ❌ 不该有：分析 / 解读（去 summary）
- ❌ 不该有：手动编辑（保持 raw）

### `plans/X.md`
**长期 roadmap / 阶段计划**。跨多 session 的"接下来做什么"。
- ❌ 不该有：单子系统技术细节（去 designs）
- ❌ 不该有：session 内任务（用 TaskCreate）

### `dev_logs/summary/X.md`
**已发生归档**（past 时态，写完即冻结）。
- ✅ 应该有：贴分析表（高度概括的衍生指标，如 horizon × IC × spread_shrp × mono）时，**基础数据（完整原始数字表，如所有 horizon × 10 decile 的实际 mean return）也要一起贴**。光贴概括表 = 解读 / 陷阱 / 异常发现全失去证据——下次自己（compact 后）回看或别人读 summary 都没法验证数字是真是假，只能盲信结论
- ❌ 不该有：未来计划（去 plans 或 handoff）

### `dev_logs/handoff.md`
**当前活跃任务**。单文件（覆盖式更新）。
- ❌ 不该有：已完成任务（移到 summary）
- ❌ 不该有：长期 roadmap（去 plans）

### `dev_logs/chat_exports/X.md`
**session 备份 raw**。原汁原味对话。
- ❌ 不该有：提炼版（去 summary）

## 关键边界判断

### 内容该放哪？3 个 yes/no

写内容时问自己：

1. **这是讲技术实现还是讲阶段计划？**
   - 技术 → `designs/`
   - 计划 → `plans/` 或 `handoff.md`
2. **5 年后这内容还有用吗？**
   - 有用（设计没变）→ `designs/` / `decisions/`
   - 没用（这阶段早过了）→ `plans/`（完成后归档）
3. **跨多个子系统吗？**
   - 单子系统 → `designs/X.md`
   - 跨多个 / 整体阶段 → `plans/`

### 常见混淆

| 容易混淆 | 区分 |
|---------|------|
| `plans/` vs `designs/` | plans = 接下来做什么（未来，跨阶段）；designs = 现在怎么设计（现在，单子系统） |
| `decisions/` vs `designs/` | decisions = 为啥这么做（why）；designs = 怎么做（how） |
| `setup.md` vs `cookbook.md` | setup = 一次性环境配置；cookbook = 重复但零散的操作片段 |
| `summary/` vs `handoff.md` | summary = 已完成归档；handoff = 当前活跃任务 |
| `references/` vs `designs/` | references = 外部知识；designs = 项目自己的设计 |

详见 [boundaries.md](references/boundaries.md)。

## /compact 工作流

handoff.md 是 **prompt 生成器**，产出三段可复制字符串给 /compact 用：

```
handoff.md =
  ├─ ① Compact 参数（贴到 /compact 后面，控制这次保留什么）
  ├─ ② Post-compact 首句（贴到压缩后 session 第一句，让新 session 接续）
  └─ ③ Export 标题建议（用户 /export 时复制，作为 chat_export 文件名）
```

**① Compact 参数**：精简指令（1-2 行），指向 handoff ② + 最新 summary，**不塞细节**。**为啥必须精简 + 真取舍**：compact 工具有压缩容量上限，① 里"全保留"会导致 compact 压不动（保留太多 = 没压缩 = 装不下）。必须明确"丢弃 X / 保留 Y"，让 compact 知道丢什么，才能把关键信息压缩进新 context。取舍原则：
- 保留：决策结果 / 当前架构 / 关键数字 / 下一步动作
- 丢弃：实施过程 / 中间探索 / 已归档到 docs 的细节

**② Post-compact 首句**：保留关键决策结果 + 下一步明确动作（不是选项列表）。长度 2-4 行。

**③ Export 标题**：完整文件路径（不是纯文件名），用户 /export 时直接复制粘贴。格式 + 示例见 [compact_workflow.md](references/compact_workflow.md)。

**三层互补**：
1. **CLAUDE.md `## Compact Instructions`**：项目固定项（已锁定决策/模块进度/工作约定），所有 compact 自动生效
2. **`/compact <①>`**：这次特定保留需求，覆盖/补充默认
3. **handoff.md ①+②+③**：关键节点 compact 用，跨 session 接续

详见 [compact_workflow.md](references/compact_workflow.md)。

## 起步最小集 → 演进路径

新项目不要一上来建全套 11 个，**按需启用**：

```
Day 1：README + setup + designs/ + dev_logs/{summary, chat_exports}/  (最小可行集)
       ↓
子系统 ≥ 3：+ architecture.md
       ↓
跨 session：+ plans/ + dev_logs/handoff.md
       ↓
关键决策多：+ decisions/
       ↓
术语多 / 调研多 / 一次性脚本多：+ glossary / references / cookbook
       ↓
经常跑训练 / 实验：+ dev_logs/run_prints/（避免 stdout 被截断，跨 session 对比数字）
```

**反模式**：一上来就建 11 个空目录占位。空目录是噪声，按需添加比预先规划好。

## 写作约定

### 命名规范

- `summary/`：`YYYY-MM-DD_短英文描述.md`（日期必须绝对，不写"昨天今天"）
- `decisions/`：`00X-short-name.md`（编号 + 短名，方便引用）
- `designs/`：按子系统命名（不带日期，living doc）
- `chat_exports/`：`<date>_<topic>.md`
- `handoff.md`：单文件，每次覆盖（不追加历史）
- `cookbook.md`：单文件，按主题追加条目

### 写作原则

- **summary 实测对比三级分层（核心原则）**：实测对比类内容（deme vs baseline / 标签方案对比 / 模型 A vs B 等）必须按三层明确标注，避免 AI 通病（把推论当事实记录，污染后续决策）：
  - **事实**：实测数字、可观察现象（无修饰，直接列数据）
  - **可信推理**：基于数学定义 / 严格逻辑推导（标"由 X 定义推出"或"数学必然"）
  - **推测**：基于经验 / 理论的归因，但未严格证明（必须标"推测未严格证明"，不能伪装成事实）
  
  实操：每层用独立小标题（"事实结果" / "严格推理" / "推测未严格证明"），让读者一眼看出可信度。**为啥严格分层**：AI 通病是混淆三层（特别是把推测当事实写），后续 session / 别人读 summary 时把推测当 ground truth，导致决策基于错误前提。即使推测合理，没严格证明就标推测，读者自然会怀疑。
- **记事实不记猜测**：未验证的根因标"推测 X，未验证"
- **解释 why**：决策不光写"决定 X"，要写"为啥不选 Y"
- **避免"必须 / 总是"**：用解释代替命令
- **关键信息放 docs 不放 memory**：memory 是用户偏好 / 工作风格，docs 是项目知识

各文档的模板详见 [templates.md](references/templates.md)。

## 不该塞进文档的内容

| 内容 | 该放哪 |
|------|--------|
| 用户偏好 / 工作风格 | memory（不是 docs） |
| 跨 session 的项目知识 | docs（不是 memory） |
| 临时任务跟踪 | TaskCreate（不是 docs） |
| 一次性脚本代码 | `scripts/`（代码不是 docs，但方法可记到 cookbook） |

## 详细参考

按需读取：

- [templates.md](references/templates.md)：各文档的模板（README / architecture / setup / ADR / summary / handoff / cookbook 条目 等）
- [boundaries.md](references/boundaries.md)：边界判断的详细案例 + 常见错误归类
- [compact_workflow.md](references/compact_workflow.md)：/compact 工作流详解 + handoff.md 完整模板
