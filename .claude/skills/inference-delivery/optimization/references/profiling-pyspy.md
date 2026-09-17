# CPU 侧火焰图定位（py-spy）

## 什么时候用

分侧计时（模式 1）找到慢的**段**之后（例如 "adapt 45ms"），要再往下拆
"段内哪个函数吃的"——粒度从段级下钻到函数级。CPU 侧热点常是
"每次几微秒 × 上千次"的形态，单看任何函数都很小，聚合占比才看得见。

## 采样

```bash
py-spy record --pid <PID> -o out.json --format speedscope --rate 50
# 跑够样本后 Ctrl-C；或加 -d <秒数> 定时停
```

参数要点：

- **`--format speedscope` 必须带**：缺省生成静态 SVG 火焰图，没有
  Time order / Left heavy / Sandwich 三视图，也不可机器聚合。输出格式由
  `--format` 决定，与文件扩展名无关（用户实测纠偏过）
- **`--rate 50`**：每秒 50 栈，开销小且够定位；换采样率时，聚合脚本的
  秒数换算（样本数 ÷ 50）要同步改
- 样本量：几百样本起步，覆盖多个推理步

**找 PID**：

- 独立脚本：`pgrep -f <命令关键词>`，取 PPID 为 shell 的主进程（不是子进程）
- 仿真/多进程框架：worker 的 PID 在日志里（如 Ray 的 `(wrapped_fn pid=...)` 行），
  采干活的那一个，不是 launcher

## 消费路径 A：speedscope.app 交互查看

把 `.json` 拖进 <https://www.speedscope.app>——三视图：

- **Time order**：按时间看每个采样时刻的栈（找抖动/阶段切换）
- **Left heavy**：按总耗时排序的合并视图（最常用，看大头）
- **Sandwich**：按函数看 caller/callee 两侧（看某函数被谁吃）

## 消费路径 B：离线聚合脚本

交互适合逛，批量出数字用 [../scripts/agg_speedscope.py](../scripts/agg_speedscope.py)
（纯标准库、零依赖，45 行）：

```bash
python agg_speedscope.py out.json              # TOP 40 by SELF
python agg_speedscope.py out.json map_process  # 按子串过滤，self/total 占比
```

## 读数

- **self**：该函数在栈顶的样本占比（自身耗时，不含子调用）
- **total**：该函数出现在栈中任意层的占比（含全部子调用）
- 定位"哪段代码在吃时间"看 self；评估"重写这个模块能省多少"看 total
- 占比 → 毫秒换算：`占比 × 采样时长 ÷ 采样期间推理步数`。50Hz、单步 20ms
  量级时，1% ≈ 单步零点几毫秒——先换算成单步毫秒再评估值不值得动

## 陷阱

- 只看 self 会漏"调度开销型"热点：某函数 self 很小但被调用上万次，
  它的 total 会暴露它——两个数都要看
- 采样期间负载要代表稳态：冷启动、编译、邻居进程争用都会污染占比
- 火焰图只看 CPU 侧；设备侧（NPU/GPU）用分侧计时＋同步读钟（模式 1），
  两侧工具不可互替

## 战例

Diffusion-Planner R4（[diffusion-planner-case.md](diffusion-planner-case.md)）：
5 场景仿真 + 50Hz 采样 9788 样本，聚合出"三行 Point2D 逐点构造 17.3%、
devkit `to_vector` 13.1%、agents 三层循环 4.3%"——直接喂出向量化＋缓存的
改造清单（adapt 179.8 → 54.2ms）。
