# /compact 工作流详解

handoff.md 的本质是 **prompt 生成器**，产出三段可复制的字符串给 /compact 工作流用。

---

## 三层互补

| 层 | 内容 | 何时生效 |
|----|------|---------|
| **CLAUDE.md `## Compact Instructions`** | 项目固定项（已锁定决策/模块进度/工作约定） | 所有 compact 自动生效 |
| **`/compact [具体指令]`** | 这次特定保留需求 | 复制 handoff.md ① 到 `/compact ` 后面 |
| **`dev_logs/handoff.md`** | 三段复制字符串（① + ② + ③） | 关键节点 compact 前更新 |

**CLAUDE.md 那段写项目固定项**（已锁定决策 / 模块进度 / 工作约定）——指针式列举，不抄内容（CLAUDE.md 别处段已有），不写这次 compact 特定的（那归 handoff ①）。详见下方 [CLAUDE.md Compact Instructions 该写啥](#claude-md-compact-instructions-该写啥)。

**handoff.md 只产 prompt 字符串**，不放详细状态。详细状态归 `summary/`。

---

## CLAUDE.md Compact Instructions 该写啥

CLAUDE.md 这段写**项目层面、每次 compact 都不变的固定保留项**。指针式，不抄内容。

### 写啥

跨 session 必须留的项目层面信息，典型三样：

- **已锁定决策**（避免新 session 重议）
- **模块进度**（哪些子系统已通 / 未实现）
- **工作约定**（行动前说意图、改完跑测试之类）

**这次 compact 特定的**（当前任务、最近文件）归 handoff ①，不写这里。

### 为啥不抄内容

CLAUDE.md 别处段（`## 关键决策`、`## 当前状态`、`## 工作风格约定`）已经有详细内容。Compact Instructions 只指**类别名**，compact 时会去对应段找。抄一遍冗余，还增加压缩负担。

### ✅ 好

```
## Compact Instructions
保留：已锁定决策、模块进度、工作约定。
丢弃：探索性讨论、已完成任务的实现细节。
```

### ❌ 错

**错 1：写这次特定的**（归 handoff ①）

```
保留：当前任务一句话、最近修改的文件路径。
```

当前任务每次 compact 都变，不是 CLAUDE.md 这层该管的。

**错 2：抄内容**（CLAUDE.md 别处已有）

```
保留：已锁定决策（Tushare / LightGBM / qfq / 万一免五 / 不做实盘）...
```

括号内容冗余，compact 时还得 parse。

**错 3：写一大段**（压不下去）

```
保留：当前任务、文件路径、决策、调试上下文、未解决问题、待办、用户偏好、...
```

---

## handoff.md 结构

```markdown
# Handoff

> 给 /compact 工作流的三段复制内容。每次更新时重写①②③。

## ① Compact 参数（贴到 `/compact ` 后面）

\`\`\`
保留：[一句话]. 丢弃：[一句话]
\`\`\`

## ② Post-compact 首句（贴到压缩后 session 第一句）

\`\`\`
[一句话]
\`\`\`

## ③ Export 标题建议（/export 时复制）

\`\`\`
<项目根>/<syx_docs_location>/dev_logs/chat_exports/YYYYMMDD-关键词-关键词
\`\`\`
```

**只有这三段**。没有详细状态、没有 recent decisions、没有"立即下一步"列表——这些都是 summary 的事，handoff 是 prompt 生成器。

**③ 必须带完整路径**（不只是文件名）——/export 命令把整段当存盘文件名，用户复制粘贴即用，不用手拼路径。

---

## 工作流（按场景分层）

### 场景 A：日常 compact（80%）

任务中段，继续干同样的事。

**只靠 CLAUDE.md 默认段**：
```
/compact
```

CLAUDE.md 的 Compact Instructions 自动生效。

### 场景 B：特殊 compact（15%）

这次有特殊保留需求（如正在调试某个 bug、刚做了重要决策）。

**用 handoff ①**：
1. 更新 `dev_logs/handoff.md` 的 ①
2. 复制 ① 到 `/compact` 后面：
   ```
   /compact 保留：当前调试 fetch_pool.py 的 NoneType bug；丢弃早期探索
   ```

### 场景 C：关键节点 compact（5%）

跨 session、今天结束、大方向转换。

**三层都用**：
1. 更新 `dev_logs/handoff.md` 的 ① 和 ②
2. 复制 ①：`/compact <① 的内容>`
3. Compact 完，开新 session，复制 ② 作为第一句话

---

## 怎么写好 ① 和 ②

### ① Compact 参数（一句话控制保留）

公式：`保留：[当前任务一句话] + [关键文件] + [锁定决策勿重议]；丢弃：[探索/已完成细节]`

**好的 ①**：
- ✅ `保留：当前在重构 docs（已完成 architecture/decisions/glossary，待做 setup/README）；锁定决策（Tushare/LightGBM/qfq）勿重议。丢弃：探索性讨论`
- ✅ `保留：当前调试 fetch_pool.py 的 NoneType bug；最近改动 features/pool.py。丢弃：早期 akshare 探索`

**不好的 ①**：
- ❌ 太长（一句话变三段，compact 反而难压缩）
- ❌ 太空（"保留所有重要的事"等于没说）
- ❌ 包含详细状态（详细归 summary）

### ② Post-compact 首句（让新 session 知道在干什么）

公式：`继续 [任务名]：[立即下一步]，详见 dev_logs/handoff.md`

**好的 ②**：
- ✅ `继续 docs 重构收尾：瘦身 setup.md + 重写 README.md，详见 docs/dev_logs/handoff.md`
- ✅ `继续 Phase 2.1.b：提交 fetch_pool.py 改动 + 跑 train_model.py 验证`

**不好的 ②**：
- ❌ "继续之前的工作"（没说具体是啥）
- ❌ 把 7 步计划全列出来（太长，去 plans/）

---

## 反模式

### ❌ handoff.md 当状态记录本

```markdown
## 当前状态
做完了 A，正在做 B，下一步 C...

## Recent decisions
- 决策 1
- 决策 2

## 修改文件列表
- file1
- file2
```

**错**。这些归 summary。handoff 只产两段 prompt 字符串。

### ❌ handoff.md 追加历史

每次 compact 前在 handoff 后面追加新内容。

**错**。每次重写①和②，**覆盖**旧内容。handoff 始终是"当前这一次 compact"的 prompt。

### ❌ CLAUDE.md Compact Instructions 写一大段

```markdown
## Compact Instructions
保留：当前任务、文件路径、决策、调试上下文、未解决问题、待办、用户偏好、改动的函数签名、错误信息、最近测试结果、...
```

**错**。保留太多 = compact 压缩不下去。只保留**最基础**两三项，特定需求靠 handoff ①。

### ❌ /compact 不带参数也不更新 handoff

直接 `/compact`，指望 Claude 自己猜对保留什么。

**结果**：默认行为经常漏关键细节。至少 CLAUDE.md 那段要配好（场景 A 的最小要求）。

---

## 跟 summary 的边界

| 信息 | 放哪 |
|------|------|
| 这次 compact 要保留什么 | handoff ① |
| compact 后新 session 该做什么 | handoff ② |
| 上一阶段完成了什么 | summary |
| 最近修改了哪些文件（备查） | summary（或 git log） |
| 锁定的决策（避免重议） | decisions/（handoff ① 可引用） |

**关键**：handoff 是"prompt 生成器"，summary 是"已发生归档"。两者职责完全不同，**不要混**。
