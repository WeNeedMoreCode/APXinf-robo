# 高级 Skill 架构模式

当 skill 内容量大（1000+ 行）或需要覆盖多个维度（语言、框架、场景）时，简单的单文件 SKILL.md 不够用。这里记录经过验证的高级架构模式。

---

## 模式一：Router-Delegate（路由-委托）

**适用场景**：内容量大、有明确的场景分支。

**来源**：Anthropic 官方 `claude-api` skill（12,000+ 行，44 个文件）。

### 核心思路

SKILL.md 只做路由，不放具体内容。职责严格分离：

1. **检测上下文**：用户在用什么语言、什么框架、什么场景
2. **决策路由**：判断用户需要哪个分支
3. **精确指路**：告诉模型"读这个文件"

### 结构模板

```
skill-name/
├── SKILL.md                    ← 路由器（占总内容 3-5%）
├── {维度A}/                    ← 维度A 的内容（如语言、框架）
│   ├── README.md               ← 维度A 的基础指南
│   ├── feature-1.md            ← 具体功能
│   └── feature-2.md
├── {维度B}/                    ← 维度B 的内容
│   └── ...
└── shared/                     ← 跨维度共享内容
    ├── concepts.md             ← 通用概念
    └── reference.md            ← 通用参考
```

### SKILL.md 内部结构

```markdown
## 场景检测

[如何判断用户属于哪个分支的规则]

## 快速读取表

| 用户要做什么 | 读取 |
|---|---|
| 场景 A | `{维度A}/README.md` |
| 场景 A + 功能 X | `{维度A}/README.md` + `{维度A}/feature-x.md` |
| 场景 B | `shared/concepts.md` + `{维度B}/README.md` |
| 只查参考 | `shared/reference.md` |

## 路由规则

[决策树或分支逻辑]
```

### 关键数据

来自 claude-api 的实测：
- SKILL.md 占总内容 **2.6%**（325 行 / 12,275 行）
- 最大嵌套深度 **3 层**（SKILL.md → 语言目录 → 功能文件）
- Router-to-content 比例 **1:38**

### 注意事项

- **SKILL.md 不要超过 500 行**。如果路由逻辑本身就超过 500 行，说明维度太多，考虑拆成多个 skill
- **Reading Guide 表是核心**。模型看到这张表就能精确读取，不需要通读 SKILL.md
- **每个子文件顶部写明"何时读取此文件"**。防止模型在不相关时读取
- **shared/ 放跨维度内容**。概念性、通用性的内容不要在每个维度目录里重复

---

## 模式二：渐进式路由

**适用场景**：有层级关系的多维分类（如：语言 × 功能 × 场景）。

### 核心思路

不是一次性路由到最终文件，而是逐级缩小范围：

```
第一级：检测大方向 → 读对应维度的 README
第二级：README 内部再做细分路由 → 读具体功能文件
```

这样做的好处：
- SKILL.md 更简洁（只做第一级路由）
- 每个维度的 README 可以独立维护
- 模型按需深入，不会一次加载太多

### 例子

```
SKILL.md
  → 检测到 Python → 读 python/README.md
    → README.md 发现用户要做 streaming → 读 python/streaming.md
```

---

## 模式三：路由 Skill + 专用 Skill 组合

**适用场景**：一个大领域内有多个独立子领域，每个子领域本身就很复杂。

### 核心思路

用路由 Skill 指向多个独立 Skill，而不是把所有内容放在一个 Skill 里。

```
cuda-to-npu/               ← 路由 Skill
├── SKILL.md               ← 帮用户选路径
└── references/
    ├── torch_npu_path.md  ← 纯 torch_npu 踩坑
    └── torchair_path.md   ← TorchAir 踩坑

ascend-om-deployer/        ← 独立 Skill（OM 路径）
├── SKILL.md               ← 完整的 OM 部署流程
└── references/...
```

路由 Skill 的 SKILL.md 用 Read 指向独立 Skill：
```markdown
OM 离线路径 → Read [../ascend-om-deployer/SKILL.md](../ascend-om-deployer/SKILL.md)
```

### 选择依据

| 情况 | 用什么模式 |
|---|---|
| 单一领域、内容量中等 | 简单单文件 SKILL.md |
| 单一领域、内容量大、有场景分支 | Router-Delegate（模式一） |
| 多维度分类（语言×功能） | 渐进式路由（模式二） |
| 跨领域、每个子领域独立复杂 | 路由 Skill + 专用 Skill（模式三） |

---

## 如何选择架构

问自己三个问题：

1. **内容量多大？** < 500 行 → 单文件；> 500 行 → 需要分层
2. **有几个独立维度？** 1 个 → 模式一；2+ 个 → 模式二或三
3. **维度之间是否完全独立？** 是 → 模式三（拆成多个 Skill）；否 → 模式一或二（放一起，用路由区分）
