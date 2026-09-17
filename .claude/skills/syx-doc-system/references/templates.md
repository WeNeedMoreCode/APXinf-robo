# 文档模板

各文档的标准模板。新建文档时复制粘贴，按需修改。

---

## README.md

```markdown
# <项目名> — 文档与日志索引

## 核心文档

- [架构文档](architecture.md) — 系统组成 / 数据流
- [环境配置](setup.md) — 怎么搭环境

## 目录用途

| 目录 | 用途 | 写入时机 |
|------|------|---------|
| `designs/` | 子系统设计 living doc | 设计变化时 |
| `decisions/` | 关键决策记录（ADR）| 做决策时 |
| `plans/` | 长期 roadmap | 开新 Phase 时 |
| `references/` | 外部知识 / 规范 | 调研时 |
| `dev_logs/summary/` | 已发生归档 | 用户主动让写时 |
| `dev_logs/handoff.md` | 当前活跃任务 | /compact 前 |
| `dev_logs/chat_exports/` | session 备份 raw | 用户主动 |

## 写作约定

- summary 命名：`YYYY-MM-DD_短英文描述.md`
- decisions 命名：`00X-short-name.md`
- designs：按子系统命名，living doc
- 关键信息入 docs，不入 memory

## 索引

### Designs
- [子系统 A](designs/a.md)
- [子系统 B](designs/b.md)

### Decisions
- [001-xxx](decisions/001-xxx.md)

### Plans
- [Phase X roadmap](plans/phase_x.md)

### Summary
- [YYYY-MM-DD xxx](dev_logs/summary/yyyy-mm-dd-xxx.md)
```

---

## setup.md

```markdown
# <项目名> — 开发环境配置

**用途**：新机器 / 新 session 配置环境的参考。

## 1. 工作区关系
（项目位置 / 上级目录关系）

## 2. Git 托管
（远程仓库 / 分支策略）

## 3. 语言 / 包管理器
（Python 版本 / uv / Node 等）

## 4. 数据源 / API key
（注册步骤 + token 配置，**不写数据源对比**——去 decisions）

## 5. 硬件要求
（如果有 GPU / 内存需求）

## 6. 常见踩坑
（**只放环境/工具相关**，子系统特定踩坑去 designs）

## 7. IDE 推荐
```

---

## architecture.md

```markdown
# <项目名> — 架构文档

**最后更新**：YYYY-MM-DD（Phase X）

## 当前架构图
（组件图 / 数据流图，反映**实际状态**，不是建议）

## 模块分层（实际结构）
（实际代码结构，不是初始化时的建议）

## 已锁定决策
（一句话列表 + 指向 decisions/ 的链接）
- 数据源：Tushare（详见 [001-xxx](decisions/001-xxx.md)）
- ...

## 待决问题
（**只列真没决定的**，已决策的移到上面"已锁定决策"）
```

---

## designs/X.md（子系统设计）

```markdown
# <子系统名> 设计

## 目的
（一句话讲这子系统干啥）

## 接口
（核心 API / 类定义）

## 核心决策
（**怎么实现** + 为什么。每个决策一段）

### 1. 决策名
（做法 + 理由 + 已考虑的备选）

### 2. ...

## 已知缺陷
（**当前实现的问题**，标明严重度 + 改进方向）

## 未来扩展
（**近期会做的扩展**，跨多 session 的去 plans/）
```

**反模式**：把 "Phase X 要做什么" 塞进 designs → 去 plans/。

---

## decisions/00X-*.md（ADR，Architecture Decision Record）

```markdown
# 00X — 决策标题

**日期**：YYYY-MM-DD
**状态**：accepted（或 proposed / deprecated / superseded by 00Y）

## 背景（Context）
（为啥需要这个决策？遇到什么问题？）

## 决策（Decision）
（最终选了什么）

## 备选方案（Alternatives）
（考虑过哪些其他选择？每个为啥不选？）

| 方案 | 优点 | 缺点 | 为啥不选 |
|------|------|------|---------|
| 选定方案 | ... | ... | — |
| 备选 A | ... | ... | ... |
| 备选 B | ... | ... | ... |

## 后果（Consequences）
（这决策带来的影响：正向 + 负向）

## 相关
（链接到 designs / 其他 decisions）
```

**反模式**：写实现细节 → 去 designs。

---

## dev_logs/summary/X.md

```markdown
# YYYY-MM-DD <短描述>

## 概述
（一两句话讲这阶段做了什么）

## 完成的事
（bullet list，每条聚焦一件事）

## 关键决策
（指向 decisions/ 或简短说明）

## 实测结果
（如果有具体数字 / 验证结果）

## 待办
（如果用户后续要让写，**待办归 handoff.md / plans/**，summary 是历史快照）
```

**反模式**：把"下一步要做什么"写进 summary → summary 写完即冻结，下一步会变。去 handoff.md。

---

## dev_logs/handoff.md

handoff 是 prompt 生成器（不是状态记录），产三段复制字符串给 /compact 用。**完整模板 + 规则见 [compact_workflow.md](compact_workflow.md)**，这里不重复。

每次 /compact 前**覆盖**更新（不追加历史）。

详见 [compact_workflow.md](compact_workflow.md)。

---

## glossary.md

```markdown
# 术语表

按类别组织，每个术语 1-3 行解释。

## 类别 A

| 术语 | 解释 |
|------|------|
| XXX | 一句话解释 |
| YYY | 一句话解释 |

## 类别 B
...
```

---

## cookbook.md

```markdown
# Cookbook — ad-hoc 脚本片段登记

记录一次性脚本的方法（不维护完整代码）。

---

## 检查 / 调试某事

**场景**：什么时候用

**关键代码**：
\`\`\`python
# 关键片段，能 recreate 即可
\`\`\`

**何时用**：触发条件

---
```

每个条目三段：场景 / 关键代码 / 何时用。简洁，能 recreate 就行。

---

## plans/X.md（长期 roadmap）

```markdown
# <Phase / 主线名> Roadmap

## 当前阶段
（在做的子阶段，链接到 designs / handoff）

## 接下来
（按顺序列子阶段，每个一两句话讲做什么 + 何时开）

## 已完成（归档）
（完成的子阶段，标完成日期）

## 长期愿景
（这 Phase 完成后系统的样子）
```

**反模式**：把"子系统怎么设计"塞进 plans → 去 designs。
