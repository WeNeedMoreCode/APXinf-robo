# Handoff（2026-10-10 轮动态分档定案 + goal 三谱系泛化 → 下一轮压缩用）

## 状态一句话

**三项 goal 全闭环（全数字见 summary/2026-10-10_dyn-gear-goal-suite-om-lazyload.md）**：① **动态 L 分桶生产化 = 路线定案 GE 动态分档（dynamic gear）**（spike 全绿：ge_builder 路径编译过、**权重零重复**（双档 OM 仅 +42KB，32MB Const 根图单份——源码 CreateRootGraph/ChangeConstToData 机制 + 实验双证）、档位真分发（GetCurOutputDims 650/712）、数值 0.23%、**性能零税** 6.04≈5.57ms；skill ge-offline-om 已回填动态分档节）；② **OM 冷启动 125.6s 分解定案**（ckpt 63.7s 全量解析 ~90% 白 parse（e2e serve 只需嵌入表+time_mlp）+ vision 11.9 + prefix 41.2（含 2.1GB 嵌入查表）+ flow 8.8s）——lazy 施工与 gear 生产化同轮（单 serve 常驻后冷 spawn 从每 L 一次变每芯一次）；③ **libero_goal 第三谱系双面闭环**（transfer：v3o 距 goal 专属拟合 prefix 6.6%/flow 14.2% 相对差，最优超参三连复现 prefix α0.5/flow late α0.6 → **单一因子集三谱系覆盖**；行为面 **10/10 @ per-call 234.0ms 中位（229 calls）**，三谱系 229/235/234 全带内）。附带：**119 上行断流新坑**（>~700B 上行即 RST、下行正常、scp 双协议死 → gzip+480B 分块 base64 append workaround，入 memory）；goal 录制器 200 vs eval 客户端 138 的 tokenize 差异（观察项，校准 L 无关不受影响）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-10_dyn-gear-goal-suite-om-lazyload.md）——① 动态分档定案（选项 `input_shape` 带 -1 + `ge.dynamicDims` 档表；权重零重复；SetInputDynamicDims + gear-info 额外输入坑；hybrid 模式档外兜底；spike 在 syx_docs/dev_logs/probe_dyn/dyn_gear_probe.c + 服务器 /data/apxinf/probe_dyn/）；② 冷启动分解（ckpt 63.7 + 三段 OM 51.9s；lazy 与 gear 同轮施工）；③ goal 三谱系 10/10 @ 234ms + transfer 三连（v3o 固定候选对照法）；上行断流 workaround（gzip+480B 分块）。丢弃：spike 调试迭代、eval 监控过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-10，见 summary/2026-10-10_dyn-gear-goal-suite-om-lazyload.md）：三线全闭环——动态分档路线实证（编译/零权重重复/真分发/零税）、冷启动 125.6s 分解定案、goal 三谱系 10/10 @ 234ms（单一因子集）。生产根 v3 位持续运行中。

**下轮 goal 建议（抄一项即可）**：
1. **动态分档生产化施工**（prefix/flow 图 -1 维 + 档集 138-157+200 → GeServe SetInputDynamicDims + per-gear IO → 单 serve 多 L → supervisor 每芯一只；vision 保持静态；hybrid 模式档外兜底选读）
2. **冷启动 lazy 施工**（与 1 同轮：ckpt 选择性读取 −54s + 三段 OM 并行加载 −20s → ~50s；"引擎注册链入主路径" = eval 全链 inproc：apxinf_npu 供给 9.0.1 libs + 客户端去 torch_npu，省 spool 轮询 ~15ms/call）
3. **多 checkpoint 泛化**（换 checkpoint 跑管线一条龙：record → golden → sweep v3o 对照 → 免烤/重烤判定 → eval；需先到位第二个 checkpoint）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；**eval 默认生产根 /data/apxinf/serve（v3 位运行中）**；A/B 实验 = 重启 serve_i8 mini_sup_i8_v3.sh（全谱系桶 + supervisor 单实例）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（scp 不可用）**；sshd 断连先 /dev/tcp banner 判层。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 动态分档生产化施工** —— 把"每个 token 长度 L 一只 OM 桶 + 每桶一只 serve 进程"换成"**单只多档 OM + 单 serve 按请求选档执行**"。
- **为什么**：prompt+state 离散化使 L 随任务漂移（已观测 137-200），现在 20 只桶靠 lazy-bake 兜底——新 L 首次请求要冷烤 ~6min + 冷启动 2min，且 idle serve 只增不减（本轮已累积 23 只占显存）。10-10 spike 已实证 GE 动态分档在 310P 编译过、**权重零重复、档位真分发、零性能税**（每档独立静态 kernel，tiling 收益不丢）——风险已被排除，剩下纯施工。
- **怎么做**：引擎侧 prefix/flow 图 Data 维改 `-1` + `ge.dynamicDims` 传档表（档集 = 观测谱系 138-157+200，约 22 档 ≪ 100 上限）→ GeServe 执行前调 `aclmdlSetInputDynamicDims` + 按档取输出尺寸 → supervisor 改每芯一只常驻 serve。vision 段与 L 无关不动；坑与配方全在 skill ge-offline-om 动态分档节。验收 = 全量 eval 成功率/延迟不低于现配置。

**2. 冷启动 lazy 施工** —— serve 冷启动 125.6s 压到 ~50s，顺带 eval 客户端进程内直调引擎（inproc）。
- **为什么**：分解定案 = checkpoint 全量解析 63.7s（serve 实际只消费嵌入表+time_mlp，~90% 白 parse）+ 三段 OM 串行加载 ~52s。做完 goal 1 后冷启动从"每 L 一次"变"每芯一次"，所以**与 goal 1 同轮做才不白干**。inproc 再省 spool 文件轮询 ~15ms/call，且架构上消灭 serve 进程面。
- **怎么做**：ckpt 改按需读 tensor（门控开关，bake 路径不动）+ 三段 OM 并行加载；inproc 的 PyO3 入口和 GIL 修复都已就绪，剩余 = apxinf_npu 容器供给 9.0.1 libs + eval 客户端不 import torch_npu（npu_ge.py inproc 分支已在，失败自动回落 spool，无回归风险）。

**3. 多 checkpoint 泛化** —— 换一个新 checkpoint（不同训练数据/任务的 π0.5 权重）走完整条 v3 校准管线并 eval。
- **为什么**：三谱系 10/10 已闭环但全是**同一个** checkpoint——"引擎通用"的叙事还差权重组间这一维（对checkpoint泛化，而非对任务泛化）。
- **怎么做**：管线已全参数化（record 换 SUITE/ckpt → golden → sweep v3o 对照 → transfer 成立免烤直评 / 不成立才 fleet 重烤）。**卡点：需要先拿到第二个 checkpoint**——没有它这项无法开工，选此 goal 前先确认 ckpt 到位。

## ④ 性能优化方向清单（2026-10-10 更新）

现状锚点：**v3 生产位 per-call object 229.0 / spatial 235.2 / goal 234.0ms = 376ms 基线的 0.61-0.63×，三谱系 10/10**。量化/行为/泛化/生产化全闭环——**剩余杠杆全在部署形态面**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略，见 roadmap + 历史战报） | qmd per-token = 终点形态；单一因子集三谱系 |
| I1-I2 | v3 生产切换 / spatial 泛化 | ✅（2026-10-09） | 生产根 v3 运行中 |
| I3 | 动态 L 分桶 | ✅ **路线定案 = 动态分档**（spike 四绿）；生产化施工待下轮 | spike 资产 + skill 回填齐 |
| I4 | goal 第三谱系泛化 | ✅ 双面闭环（transfer + 10/10 @ 234ms） | 单一因子集三谱系覆盖 |
| I5 | OM 冷启动 lazy | 分解定案（125.6s = 63.7 ckpt + 51.9 OM 段 + warmup）；施工与 I5 生产化同轮 | 当前架构施工 = 镀金将替换路径 |
| I6 | eval 全链 inproc | 前置就绪（inproc 分支 + GIL 修复）；缺 9.0.1 libs 供给 + 客户端去 torch_npu | 省 spool 轮询 ~15ms/call |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-10_dyn-gear-goal-suite.txt（动态分档 spike 定案 + goal 三谱系泛化 10/10 + 冷启动分解 + 上行断流 workaround）
