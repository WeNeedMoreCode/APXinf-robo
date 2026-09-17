# 测试与评估

定量测试、评分、基准聚合、盲比较、Description 优化的完整步骤。

不是所有 skill 都需要这些。对于主观输出的 skill（写作风格、艺术），或简单的工具型 skill，直接让用户试用就够了。这里的方法适用于需要严格验证的 skill。

## 目录

1. [运行和评估测试用例](#运行和评估测试用例)
2. [改进 skill](#改进-skill)
3. [盲比较](#盲比较)
4. [Description 优化](#description-优化)

---

## 运行和评估测试用例

本节是一个连续的序列——不要中途停止。不要使用 `/skill-test` 或任何其他测试 skill。

将结果放在 skill 目录同级的 `<skill-name>-workspace/` 中。在工作区内，按迭代组织结果（`iteration-1/`、`iteration-2/` 等），在每个迭代内，每个测试用例占一个目录（`eval-0/`、`eval-1/` 等）。不要预先创建所有这些——随用随创建。

### 步骤 1：在同一轮中启动所有运行（带 skill 和基线）

对于每个测试用例，在同一轮中启动两个子 agent——一个带 skill，一个不带。这很重要：不要先启动带 skill 的运行，然后再回来做基线。一次性启动所有运行，让它们大约同时完成。

**带 skill 的运行：**

```
执行此任务：
- Skill 路径: <path-to-skill>
- 任务: <eval prompt>
- 输入文件: <eval 文件（如果有），或 "none">
- 保存输出到: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- 要保存的输出: <用户关心的内容 — 例如 "the .docx file"、"the final CSV">
```

**基线运行**（相同的 prompt，但基线取决于上下文）：
- **创建新 skill**：没有任何 skill。相同的 prompt，没有 skill 路径，保存到 `without_skill/outputs/`。
- **改进已有 skill**：旧版本。编辑前，快照 skill（`cp -r <skill-path> <workspace>/skill-snapshot/`），然后将基线子 agent 指向快照。保存到 `old_skill/outputs/`。

为每个测试用例写一个 `eval_metadata.json`（断言可以先为空）。给每个 eval 一个基于测试内容的描述性名称——不要只叫 "eval-0"。目录也用这个名称。如果这次迭代使用了新的或修改过的 eval prompt，为每个新的 eval 目录创建这些文件——不要假设它们会从之前的迭代继承。

```json
{
  "eval_id": 0,
  "eval_name": "描述性名称",
  "prompt": "用户的任务 prompt",
  "assertions": []
}
```

### 步骤 2：运行进行期间，草拟断言

不要只是等待运行完成——你可以利用这段时间。为每个测试用例草拟定量断言并向用户解释。如果 `evals/evals.json` 中已有断言，审查它们并解释它们检查什么。

好的断言是客观可验证的，并且有描述性的名称——它们在基准测试查看器中应该一目了然，让人扫一眼结果就立刻理解每个断言检查什么。主观的 skill（写作风格、设计质量）更适合定性评估——不要在需要人工判断的事情上强行使用断言。

草拟完成后，更新 `eval_metadata.json` 文件和 `evals/evals.json` 中的断言。同时向用户解释他们将在查看器中看到什么——包括定性输出和定量基准。

### 步骤 3：运行完成时，捕获计时数据

每个子 agent 任务完成时，你会收到一个包含 `total_tokens` 和 `duration_ms` 的通知。立即将这些数据保存到运行目录中的 `timing.json`：

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

这是捕获这些数据的唯一机会——它通过任务通知传来，不会在其他地方持久化。在每个通知到达时立即处理，而不是尝试批量处理。

### 步骤 4：评分、聚合和启动查看器

所有运行完成后：

1. **对每个运行评分** — 启动一个评分子 agent（或内联评分）读取 `agents/grader.md` 并针对输出评估每个断言。将结果保存到每个运行目录的 `grading.json` 中。grading.json 的 expectations 数组必须使用 `text`、`passed` 和 `evidence` 字段（不是 `name`/`met`/`details` 或其他变体）——查看器依赖这些确切的字段名。对于可以通过程序检查的断言，编写并运行脚本而不是肉眼检查——脚本更快、更可靠，并且可以跨迭代复用。

2. **聚合为基准** — 从 skill-creator 目录运行聚合脚本：
   ```bash
   python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
   ```
   这会生成 `benchmark.json` 和 `benchmark.md`，包含每种配置的 pass_rate、时间和 token 使用量，以及均值 ± 标准差和差值。如果手动生成 benchmark.json，请参阅 `references/schemas.md` 了解查看器期望的确切 schema。
将每个 with_skill 版本放在其对应的基线版本之前。

3. **做一次分析** — 读取基准数据，找出聚合统计可能隐藏的模式。参阅 `agents/analyzer.md`（"分析基准测试结果"部分）了解要关注的内容——比如无论有无 skill 都通过的断言（无区分度）、高方差的 eval（可能不稳定）、以及时间/token 的权衡。

4. **启动查看器**，同时包含定性输出和定量数据：
   ```bash
   nohup python <skill-creator-path>/eval-viewer/generate_review.py \
     <workspace>/iteration-N \
     --skill-name "my-skill" \
     --benchmark <workspace>/iteration-N/benchmark.json \
     > /dev/null 2>&1 &
   VIEWER_PID=$!
   ```
   对于第 2 次及以后的迭代，还需传入 `--previous-workspace <workspace>/iteration-<N-1>`。

   **Cowork / 无头环境：** 如果 `webbrowser.open()` 不可用或环境没有显示器，使用 `--static <output_path>` 写入独立 HTML 文件，而不是启动服务器。当用户点击"Submit All Reviews"时，反馈将作为 `feedback.json` 文件下载。下载后，将 `feedback.json` 复制到工作区目录，以便下一次迭代读取。

注意：请使用 generate_review.py 创建查看器；无需编写自定义 HTML。

5. **告诉用户** 类似这样的话："我已经在浏览器中打开了结果。有两个标签页——'Outputs' 让你点击查看每个测试用例并留下反馈，'Benchmark' 显示定量对比。完成后回来告诉我。"

### 用户在查看器中看到什么

"Outputs" 标签页一次显示一个测试用例：
- **Prompt**：给出的任务
- **Output**：skill 生成的文件，尽可能内联渲染
- **Previous Output**（第 2 次迭代起）：折叠区域，显示上次迭代的输出
- **Formal Grades**（如果运行了评分）：折叠区域，显示断言 pass/fail
- **Feedback**：一个文本框，输入时自动保存
- **Previous Feedback**（第 2 次迭代起）：上次的评论，显示在文本框下方

"Benchmark" 标签页显示统计摘要：每种配置的通过率、时间和 token 使用量，以及每个 eval 的详细分解和分析师观察。

通过上一页/下一页按钮或方向键导航。完成后，点击"Submit All Reviews"将所有反馈保存到 `feedback.json`。

### 步骤 5：读取反馈

当用户告诉你他们完成时，读取 `feedback.json`：

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "图表缺少坐标轴标签", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "完美，很喜欢", "timestamp": "..."}
  ],
  "status": "complete"
}
```

空反馈意味着用户觉得没问题。将改进重点放在用户有具体意见的测试用例上。

完成后关闭查看器服务器：

```bash
kill $VIEWER_PID 2>/dev/null
```

### 迭代循环

改进 skill 后：

1. 将你的改进应用到 skill 上
2. 在新的 `iteration-<N+1>/` 目录中重新运行所有测试用例，包括基线运行。如果你在创建新 skill，基线始终是 `without_skill`（无 skill）——这在迭代之间保持不变。如果你在改进已有 skill，自行判断什么作为基线更合理：用户最初带来的版本，还是上一次迭代。
3. 启动查看器，用 `--previous-workspace` 指向上一次迭代
4. 等待用户查看并告诉你他们完成
5. 读取新反馈，再次改进，重复

持续进行直到：
- 用户表示满意
- 反馈全部为空（一切都看起来不错）
- 你没有在取得有意义的进展

---

## 盲比较

当你想要对两个 skill 版本进行更严格的比较时（例如，用户问"新版本真的更好吗？"），有一个盲比较系统。阅读 `agents/comparator.md` 和 `agents/analyzer.md` 了解详情。基本思想是：给一个独立的 agent 两个输出，不告诉它是哪个版本，让它判断质量。然后分析获胜者获胜的原因。

这是可选的，需要子 agent，大多数用户不需要。人工审查循环通常足够了。

---

## Description 优化

SKILL.md frontmatter 中的 description 字段是决定 Claude 是否调用 skill 的主要机制。创建或改进 skill 后，主动提供优化 description 以获得更好的触发准确性。

### 步骤 1：生成触发评估查询

创建 20 个评估查询——混合应该触发和不应触发的。保存为 JSON：

```json
[
  {"query": "用户 prompt", "should_trigger": true},
  {"query": "另一个 prompt", "should_trigger": false}
]
```

查询必须是现实的，是 Claude Code 或 Claude.ai 用户真正会输入的内容。不是抽象的请求，而是具体的、有充分细节的请求。例如，文件路径、关于用户工作或情况的个人背景、列名和值、公司名称、URL。一点背景故事。有些可能是小写的，或包含缩写、拼写错误或口语表达。使用不同的长度混合，并侧重于边界情况而不是一目了然的（用户将有机会审核它们）。

差的：`"格式化这些数据"`、`"从 PDF 中提取文本"`、`"创建图表"`

好的：`"我老板刚给我发了这个 xlsx 文件（在我的下载文件夹里，叫什么'Q4销售最终 确定版 v2.xlsx'），她要我加一列显示利润率百分比。收入在 C 列，成本在 D 列，我记得是"`

对于**应该触发**的查询（8-10 个），考虑覆盖面。你想要相同意图的不同表述——一些正式的，一些随意的。包括用户没有明确说出 skill 名称或文件类型但明显需要它的场景。加入一些不常见的用例，以及这个 skill 与另一个 skill 竞争但应该获胜的场景。

对于**不应触发**的查询（8-10 个），最有价值的是那些近似命中——与 skill 共享关键词或概念但实际上需要不同功能的查询。想想相邻领域、朴素关键词匹配会触发但不应该触发的歧义表述，以及查询涉及 skill 做的事情但上下文中另一个工具更合适的情况。

要避免的关键：不要让不应触发的查询明显不相关。"写一个斐波那契函数"作为 PDF skill 的负面测试太简单了——它没有测试任何东西。负面案例应该真正棘手。

### 步骤 2：与用户一起审查

使用 HTML 模板将评估集展示给用户审查：

1. 从 `assets/eval_review.html` 读取模板
2. 替换占位符：
   - `__EVAL_DATA_PLACEHOLDER__` → eval 条目的 JSON 数组（不加引号——这是一个 JS 变量赋值）
   - `__SKILL_NAME_PLACEHOLDER__` → skill 的名称
   - `__SKILL_DESCRIPTION_PLACEHOLDER__` → skill 的当前 description
3. 写入临时文件（例如 `/tmp/eval_review_<skill-name>.html`）并打开：`open /tmp/eval_review_<skill-name>.html`
4. 用户可以编辑查询、切换 should-trigger、添加/删除条目，然后点击"Export Eval Set"
5. 文件下载到 `~/Downloads/eval_set.json`——检查 Downloads 文件夹中最新版本，以防有多个（例如 `eval_set (1).json`）

这一步很重要——糟糕的评估查询会导致糟糕的 description。

### 步骤 3：运行优化循环

告诉用户："这需要一些时间——我将在后台运行优化循环，并定期检查进度。"

将评估集保存到工作区，然后在后台运行：

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <驱动当前会话的模型 id> \
  --max-iterations 5 \
  --verbose
```

使用你系统提示中的模型 ID（驱动当前会话的那个），以便触发测试与用户的实际体验匹配。

运行期间，定期查看输出，告诉用户当前是哪次迭代以及分数如何。

这会自动处理完整的优化循环。它将评估集分为 60% 训练集和 40% 保留测试集，评估当前 description（每个查询运行 3 次以获得可靠的触发率），然后调用 Claude 根据失败情况提出改进。它在训练集和测试集上重新评估每个新 description，最多迭代 5 次。完成后，它在浏览器中打开一个 HTML 报告，显示每次迭代的结果，并返回包含 `best_description` 的 JSON——通过测试集分数而非训练集分数选择，以避免过拟合。

### Skill 触发的工作原理

理解触发机制有助于设计更好的评估查询。Skill 出现在 Claude 的 `available_skills` 列表中，包含其 name + description，Claude 根据该 description 决定是否查阅 skill。重要的是要知道，Claude 只在它自己无法轻松处理的任务上查阅 skill——像"读取这个 PDF"这样简单的一步查询可能不会触发 skill，即使 description 完美匹配，因为 Claude 可以直接用基本工具处理。复杂、多步骤或专业化的查询在 description 匹配时能可靠触发 skill。

这意味着你的评估查询应该足够实质性，让 Claude 确实能从查阅 skill 中受益。像"读取文件 X"这样的简单查询是糟糕的测试用例——无论 description 质量如何，它们都不会触发 skill。

### 步骤 4：应用结果

从 JSON 输出中获取 `best_description` 并更新 skill 的 SKILL.md frontmatter。向用户展示修改前后的对比并报告分数。
