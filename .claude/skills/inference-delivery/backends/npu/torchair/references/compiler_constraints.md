# TorchAir 编译器约束

torchair 图编译失败的常见原因和修复方案。README 第 5 节"不支持的写法"只列了一行表格，
本文件给出每个约束的报错信息、根因和实测演进案例。

| 你遇到 | 读哪章 |
|---|---|
| `ERR03007 GRAPH feature not supported` 报错 | 第 1 章 |
| 想给 `tensor[indices, :] = value` 找替代方案 | 第 1 章 |
| `GuardOnDataDependentSymNode` 报错 | 第 2 章 |
| `torch.split(lengths.tolist(), dim)` 编译失败 | 第 2 章 |
| `x[valid_mask]` 剔除无效行 + 算完 scatter 回零的写法想进图 | 第 3 章 |
| `if tensor.sum() > 0:` 之类数据依赖分支编译失败 | 第 4 章 |
| `ge_converter is not implemented`（如 atan2） | 第 5 章 |

---

## 1. 高级索引赋值（`tensor[indices, :] = value`）

### 报错

```
RuntimeError: ERR03007 GRAPH feature not supported
Original traceback:
    hidden_states[:, visual_indices, :] = current + visual_embed.unsqueeze(0)
```

任何形如 `tensor[index_tensor_or_bool_mask, ...] = value` 的赋值都会触发。

### 根因

NPU 图编译器不支持 Python 高级索引赋值（`__setitem__` with tensor index）。
图编译阶段需要把 Python 操作映射到标准 ATen 算子，高级索引赋值没有对应的单算子。

### 演进案例：deepstack 注入 visual embedding

以下是一个实际项目（HuggingFace transformers Qwen3-VL 的 `_deepstack_process`）的修复演进。
每一步都实测验证过。

#### Step 0：原始写法（布尔索引，编译失败）

```python
def _deepstack_process(self, hidden_states, visual_pos_masks, visual_embeds):
    local_this = hidden_states[visual_pos_masks, :].clone() + visual_embeds  # 布尔索引
    hidden_states[visual_pos_masks, :] = local_this                          # 布尔索引赋值
    return hidden_states
```

报错 `GuardOnDataDependentSymNode`——`visual_pos_masks` 是数据依赖的（输出 shape 取决于 True 的个数），Dynamo 无法 trace。详见第 2 章。

#### Step 1：布尔索引改整数索引（Dynamo 通过，但 torchair 编译失败）

eager 阶段预算固定 shape 的整数索引：

```python
# eager 阶段（不在编译函数里）
visual_indices = visual_pos_masks[0].nonzero().squeeze(-1)  # [256]，固定 shape
```

编译阶段用整数索引：

```python
current = hidden_states[:, visual_indices, :]                       # gather 读取
updated = current + visual_embed.unsqueeze(0)
hidden_states[:, visual_indices, :] = updated                      # ❌ ERR03007
```

Dynamo trace 通过了，但 torchair 编译阶段报 `ERR03007`——整数索引赋值同样不支持。

#### Step 2：换成 gather + scatter（编译通过）

```python
idx = visual_indices.unsqueeze(0).unsqueeze(-1).expand(-1, -1, hidden_states.shape[-1])
current = torch.gather(hidden_states, 1, idx)              # 读取
updated = current + visual_embed.unsqueeze(0)
hidden_states = hidden_states.scatter(1, idx, updated)     # 写回
```

`torch.gather` 和 `torch.scatter` 是标准 ATen 算子，NPU 有对应实现，编译通过。

#### Step 3：进一步优化为 scatter_add（省 2 个算子）

Step 2 的 `gather + add + scatter` 三连，如果 `updated` 是 `current + delta` 形式（delta 是新值，
不需要 current），可以合并成单算子 `scatter_add`：

```python
idx = visual_indices.unsqueeze(0).unsqueeze(-1).expand(-1, -1, hidden_states.shape[-1])
hidden_states = hidden_states.scatter_add(1, idx, visual_embed.unsqueeze(0))
```

实测某 VLA 模型：每步 211ms → 200ms，**节省 11ms**。精度不变。

### 决策树

```
需要写回 tensor 的部分位置？
│
├─ 是 → 用 scatter 系列
│   │
│   ├─ 写回值依赖原值（current + delta）→ 用 scatter(idx, current + delta)
│   │
│   └─ 写回值是新值（delta，跟原值无关）→ 用 scatter_add(idx, delta)
│
└─ 否 → 纯读取，用 gather
```

### 通用性

HuggingFace transformers 库里大量使用布尔索引和高级索引赋值。任何 transformers 模型
做 torchair 编译都可能踩。常见踩坑位置：
- `_deepstack_process` / visual embedding 注入
- masked scatter 操作
- 任何 `hidden_states[mask, :] = ...` 形式的代码

---

## 2. 动态 list 触发符号维度（`torch.split(lengths.tolist(), dim)`）

### 报错

```
RuntimeError: GuardOnDataDependentSymNode: Dynamic expression ... not supported
```

或类似的 Dynamo trace 错误。

### 根因

`torch.split(tensor, split_sizes, dim)` 当 `split_sizes` 是从 tensor 计算出来的（如 `.tolist()`、
`.item()`），split 后子 tensor 的 shape 是**符号维度**（symbolic shape），值取决于运行时数据。

Dynamo 在 trace 时无法确定符号维度的具体值，触发 `GuardOnDataDependentSymNode` 错误。

### 常见触发场景

```python
# 场景 1：attention 按 cu_seqlens 拆分
lengths = cu_seqlens[1:] - cu_seqlens[:-1]  # tensor，shape [batch]
splits = torch.split(q, lengths.tolist(), dim=2)  # ❌ lengths.tolist() 数据依赖

# 场景 2：deepstack 布尔索引
mask = some_tensor > 0
local = hidden_states[mask, :]  # ❌ 输出 shape 取决于 True 的个数
```

### 修复模式

#### 模式 A：用 reshape 替代 split（推理时 split_sizes 是固定值）

如果 `split_sizes` 在推理时是固定值（如 batch=4、tokens_per_image=256），可以预计算并 reshape：

```python
# 原始：torch.split(q, [256,256,256,256], dim=2) → 符号维度
# 替换：reshape 到固定 shape
# q: [1024, hidden] → [4, 256, hidden] → permute 给 attention → permute 回来
q_reshaped = q.reshape(num_images, tokens_per_image, n_heads, head_dim).permute(0, 2, 1, 3)
# 现在 q_reshaped.shape = [4, n_heads, 256, head_dim]，全是静态 shape
attn_out = F.scaled_dot_product_attention(q_reshaped, ...)
attn_out = attn_out.permute(0, 2, 1, 3).reshape(num_images * tokens_per_image, -1)
```

#### 模式 B：把数据依赖操作移到 eager 阶段

把 `lengths.tolist()` 这种动态计算放到编译函数外面（eager 阶段），只把固定 shape 的 tensor
传进编译函数：

```python
def prepare(self, ...):
    # eager 阶段：动态计算
    self._cached_lengths = ...
    self._cached_indices = lengths.nonzero()  # 固定 shape

def compiled_forward(self, ...):
    # 编译阶段：用 eager 阶段预算好的固定值
    # ...
```

### 通用性

HuggingFace 多模态模型（Qwen3-VL、LLaVA 等使用 packed attention 的）大量使用 `cu_seqlens` 做
序列拆分。任何 packed attention 的 torchair 编译都会踩这个坑。

README 的 monkey-patch attention 案例就是这种模式的完整实现，详见
[README 第 4 节 Monkey-patch 替换不可编译操作](../README.md#4-monkey-patch-替换不可编译操作)。

---

## 3. 布尔散回的根治：全量计算 + valid mask 置零

第 1、2 章的替代（整数索引 / gather+scatter / reshape）都是**保留索引语义**。但有一类
更常见的模式可以更彻底地消掉动态 shape：**"剔除无效行 → 计算 → scatter 回零"**。

### 模式识别

padded batch 模型（检测 / 轨迹规划 / 多智能体，pad 到固定 token 数）的 encoder 里到处都是：

```python
valid = ~mask.view(-1)          # 哪些行是真实数据
x = x[valid]                    # 剔除无效行（动态 shape，❌ 图不支持）
x = encoder_mlp(x)              # 行独立计算
x_result = torch.zeros(N, D)    # 零初始化
x_result[valid] = x             # scatter 回填（❌ 图不支持）
```

### 根治写法

当**计算模块行独立**（LayerNorm / Linear / MLP 逐行，Mixer/自回归结构只在行内 token 间）
时，剔除只是"省计算"，不是语义需要。直接全量静态 shape 计算，无效行在输出端置零：

```python
valid_f = (~mask).view(N, 1).to(x.dtype)   # [N,1] 0/1
x = x.view(N, ...)                          # 全量，静态 shape
x = encoder_mlp(x)                          # 无效行也算（产出有限垃圾）
x = x * valid_f                             # 无效行 × 0 = 精确零
```

### 等价性论证（三条，对拍前先纸上证明）

1. **有效行 bit-exact**：行独立模块下，有效行的 op 序列与剔除版完全相同——每行
   不知道其他行的存在。
2. **无效行精确零**：无效行输入全零（padded 数据的定义）→ 过 MLP 产出**有限**垃圾
   （Linear 的 bias、GELU(bias) 都是有限值；LayerNorm 零方差由 eps 兜住不会 NaN）→
   乘 0 精确归零 = 上游零初始化 scatter 的结果。
3. **零必须精确**：若下游 attention 对 context 无 mask，无效 token 以**零向量**参与
   softmax（q·0=0 → e⁰=1 的注意力权重）——这是训练时学到的语义，垃圾向量会改变
   softmax 分布。所以置零不能省，NaN 更不行（会污染整行 softmax）。

### 实测

Diffusion-Planner encoder 三个子编码器（agent/static/lane）静态化 + torchair 编译：
对拍 4 个真实输入**全部 bit-exact**（20544/20544 逐位相同），encoder 段 25→~2ms。
完整案例见
[../../../../optimization/references/diffusion-planner-case.md](../../../../optimization/references/diffusion-planner-case.md)。

### 何时不适用

- 模块**不行独立**（如 valid 行之间有跨行交互：全局 attention、batch 归一化）——
  无效行会污染有效行，只能走第 1 章的 scatter 方案或外提
- 无效行占比极大（如 99% padding）——全量算浪费的 FLOPs 可能超过省下的调度开销，
  先算笔账

---

## 4. 数据依赖 if 分支 → torch.where

### 报错

数据依赖分支在 Dynamo trace 时报 `GuardOnDataDependentSymNode`（同第 2 章），
或编译阶段图断裂。

```python
emb = torch.zeros((n, C))
if has_flag.sum() > 0:              # ❌ 条件依赖运行时数据
    emb[has_flag] = proj_a(x[has_flag])
if (~has_flag).sum() > 0:
    emb[~has_flag] = weight_b.expand(...)
```

### 根治写法

两侧都算，按位选——语义与"二选一填充"完全一致：

```python
emb = torch.where(has_flag[:, None], proj_a(x), weight_b.expand(n, -1))
```

多算的部分（原本被 if 跳过的行）被 where 丢弃，不影响输出。

### 何时不适用

- 分支两侧有一侧**很重**或会副作用（in-place 修改、随机数）——where 会把重的那侧
  也全量算，此时走外提：把分支移到 eager（参考第 2 章模式 B）
- 分支粒度是整图级（如"多模态/纯文本走不同 tower"）——那是两个编译单元的事

---

## 5. 第三类图障碍：`ge_converter is not implemented`

### 报错

```
NotImplementedError: torch.ops.aten.atan2.default ge_converter is not implemented!
[ERROR] ... ERR03007 GRAPH feature not supported
```

### 三类图障碍速查（先分类再动手）

| 类别 | 报错形态 | eager 表现 | 处理 |
|---|---|---|---|
| 硬件缺算子 | `EZ1001 ... has no binary` | **eager 也炸** | jit_compile 局部开 / 换实现（如 bool mask→float mask 避开 MHA fast path） |
| 图不支持动态 shape | `ERR03007` / `GuardOnDataDependentSymNode` | eager 正常 | 第 1~4 章的等价改写 |
| **GE 无转换器** | `ge_converter is not implemented`（op 名在报错里） | **eager 正常** | 见下 |

第三类的含义：硬件有这个算子、eager 跑得好好的，但 torchair 的 GE 后端**没写这个
ATen op 的图转换器**。已实测踩到的：`atan2`（torchair 7.2，CANN 8.3RC1）。

### 处理：最小段外提

把**含该算子的最小数据流独立段**挪到编译单元外（eager 跑），而不是整个模块外提。
粒度由数据流决定：atan2 只出现在"位置编码的 heading 改写"里，且该段是纯输入→pos
的函数，与矩阵主体无交织——于是只把 pos 构造函数外提，矩阵主体照常进图。

判断"最小独立段"的方法：从该算子出发沿数据流向上下游走，遇到第一个与主体共享的
张量边界就是切分点。外提段的代价是几毫秒级的 eager 小 op，通常可接受。

### 通用性

三角函数/坐标变换类（atan2、极坐标）出现在位置编码、heading 处理、空间变换的模型
（机器人 / 自动驾驶 / 轨迹预测）里概率很高。遇到报错先查 op 名，确认是第三类再按
最小段外提处理，不要盲目整模块放弃图化。
