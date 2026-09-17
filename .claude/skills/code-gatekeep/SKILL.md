---
name: code-gatekeep
description: Python 代码门禁(lint)规则自查与修复。每当提交 PR、过门禁、门禁报违例、修复 lint 报错,或写生产 Python 代码做提交前自查时,使用此 skill——按门禁规则清单逐项自查并给出修复,避免"改一条→推→门禁报下一条"的反复。即使用户没说"门禁",只要涉及代码审查、提交前检查、修 lint/pycodestyle/flake8 报错,都用这个 skill。
---

# 代码门禁(lint)自查

## 为什么这样做

门禁(CI 的 lint 检查)报违例会让 PR 卡住。最痛的模式是:**改一条 → 推 → 门禁报下一条 → 再改 → 再推**。这往往因为门禁报告在内部系统、拿不到完整文本,只能逐条人工转述,效率极低。

正确做法:**写代码 / 提交前就按门禁规则自查,一次改干净**,不要等门禁逐条报。

## 自查工具

> ⚠️ 参考节:本节中「lint 工具可用」**未经实测验证**——当前环境还没成功装/跑过 flake8/pycodestyle。只有「grep 查空格类规则不可靠」是实测结论,其余是推测。

**实测事实**:用 grep 查空格类规则(算术运算符 E226 等)不可靠。实测用一个匹配「字符+算术符+字符」的 pattern 去查,命中几乎全是注释、docstring、URL、科学计数法(`1e-5`)、标识符(`foo_bar2`)里的算术符号——真正的代码违例淹没在噪音里。原因是 grep 分不清"代码里的 `a+b`"和"注释里的 `end-to-end`"。

**推测(未验证)**:专门的 lint 工具(flake8 / pycodestyle)能解析 Python 语法、区分代码与注释,应该能正确查这类规则:

```bash
# 推测可用,本环境尚未验证能否装/跑
pip install flake8 pycodestyle
flake8 . --max-line-length=120     # 项目配置的行长;或读 setup.cfg/tox.ini
pycodestyle .
```

**待办**:下次有可用 python 环境时,先跑 `flake8` 验证它真能用、输出可信,再把本节从「推测」升级为「结论」。在那之前的过渡做法:
- 精确、无歧义的规则(如 `\bassert\b`、`^\s*import ` 出现在函数体内)可以用 grep 查。
- 空格 / 行长 / 运算符类规则——grep 实测不可靠,要么等工具,要么人工逐行读。

## 规则清单(逐项自查)

每条给「规则 → 反例 → 正例」。

### 1. 函数内 import 不能覆盖顶部已有的同名

实测:函数内 import 一个**模块顶部已经 import 过**的名字(局部覆盖全局),会被门禁拒。

```python
import os                  # 顶部已 import

def f():
    import os              # ✗ 覆盖顶部的 os,被拒
    ...
```

> 这里只记「覆盖会被拒」这一实测事实。顶部没有的名字放函数内行不行——门禁没说、未验证,不发挥。

### 2. 生产代码禁止 assert

`assert` 在 `python -O` 下会被整体跳过,不能用来做生产校验。改 `if not ...: raise`。

```python
# ✗                          # ✓
assert x.dtype == torch.float32
# →
if x.dtype != torch.float32:
    raise ValueError("x must be float32")

assert ret == 0, f"kernel failed: ret={ret}"
# →
if ret != 0:
    raise RuntimeError(f"kernel failed: ret={ret}")

assert os.path.exists(path)
# →
if not os.path.exists(path):
    raise FileNotFoundError(f"not found: {path}")
```

异常类型选:输入/参数校验 → `ValueError`;运行时/内核/外部调用失败 → `RuntimeError`;文件缺失 → `FileNotFoundError`。

### 3. except 里 raise 要保留原始堆栈(raise ... from e)

裸 `raise XxxError(...)` 在 `except` 里会丢掉原始异常的 traceback,排查困难。

```python
# ✗
try:
    import fpsample
except ImportError:
    raise ImportError("fpsample not installed")

# ✓
try:
    import fpsample
except ImportError as e:
    raise ImportError("fpsample not installed") from e
```

注意:如果**不是在 except 里**(主动 raise,没有原始异常),不需要 `from`,直接 raise 即可。判断标准——这一行头上有没有 `except:`。

### 4. 顶级函数 / 类前至少 2 空行(E302)

PEP 8:模块级 `def` / `class` 前要 2 空行。方法内的 `def`(类方法等)前是 1 空行,别搞混。

```python
# ✗
_patched = False

def patch_fps():
    ...

# ✓
_patched = False


def patch_fps():
    ...
```

### 5. 算术运算符两侧空格(E226)

`+ - * /`(二元)两侧要有空格。切片冒号 `:` 不加空格,但**切片里的算术仍要空格**:

```python
# ✗                              # ✓
pointcloud[i:i+1]            #    pointcloud[i:i + 1]     # 切片冒号不加, + 加
x=a+b                        #    x = a + b
```

### 6. 其它常见项(工具会报)

- **E501 行长**:通常 120(看项目配置),超长拆行。
- **E231 逗号后空格**:`a,b` → `a, b`(切片 `i:j` 的冒号不加)。
- **E402 import 位置**:import 要在模块顶部、所有非 import 代码之前(docstring / `__future__` 例外)。
- **W291/W293 行尾、行内多余空格**。

### 7. 对外文档:命名用正式名、只声称实测过的(人工审查,非 lint 工具)

这一类 flake8/pycodestyle 查不到,是 reviewer 人工把关,但同样会让 PR 卡:

- **对外文档用正式名,不用内部代号**:README 等对外文档里,产品/设备用对外正式名称。内部代号容易误导——比如某型号内部叫「X DUO」(字面暗示双芯),但实际只跑单芯,对外应称正式名。存在「内部名 ↔ 对外名」映射时,文档统一用对外名。
- **只声称实测过的**:文档里「支持 X」只写实际跑通测过的。代码逻辑上兼容、但没实测的设备/配置,不写「支持」——声称了没测,reviewer 一问就露,还误导用户。

> 这条源自具体案例(某项目设备内部名 vs 对外名、某型号没测就写了支持)。案例细节是项目特定的,这里只抽通用规则:对外命名要准、声称要如实。

## 边界:fork 项目只改"自己的"代码

如果项目是 fork(基于上游),只改**自己加的 / 自己改的**代码里的违例。上游原有的违例不动——改了会让 diff/patch 膨胀,且不是你的责任,还可能被 reviewer 质疑"为什么动无关代码"。

判断"自己加的":看 `git diff <上游 baseline>` 里带 `+` 的行。上游原有、但不在你改动里的违例,留给上游。

这条对"以 patch 文件分发改动"的项目尤其重要:patch 里每多一行无关改动,上游 apply 时就多一处合并负担。

## 工作流

1. **先跑工具**:`flake8`/`pycodestyle` 扫改动的文件,拿全违例清单(拿不到工具才退 grep,且只查精确规则)。
2. **逐项对照规则清单**修复(用上面的正例模板)。
3. **fork 项目**:只修 `git diff <baseline>` 里自己引入的(`+` 行);上游原有的跳过。
4. 再跑一次工具确认清零,再提交——别等门禁逐条报。
