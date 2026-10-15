# 2026-10-15 I9 收口：「tokenize 186ms」归因证伪 + first-call warmup 修复（inference 433→274）

立项原命题（handoff ④ I9 行）：prompt 前缀 episode 内不变 + state 离散化纯确定性 → tokenize 前缀缓存 + bin→tokenid 查表，**−186ms、inference 433→~250**。

## 证伪链（四步取证，每步都推翻上一步的主导假设）

**① tokenizer 单项（probe_dyn/probe_tok_cost_1015.py，apxinf_npu CPU）**
`GemmaTokenizerFast`（transformers 4.53.3），与 lerobot `TokenizerProcessorStep` 同参调用（max_length=200/padding=max_length）：**全量 prompt 0.43ms**；分段 prefix 0.30 / state 0.36 / tail 0.28；`np.digitize` 0.03ms。「tokenize 是 186ms」在组件级不成立。
- 副产物（若未来真要旁路 tokenizer）：per-int 查表 concat **不逐位 exact**——Gemma digit 逐字符切分，但 `"▁"+"-"` 会跨界合并成 728（`▁-`），首元素需特殊处理；表构建 58.6ms 一次性。

**② 真实宿主全链分项（probe_dyn/probe_frame_breakdown_1015.py，npu 宿主 + chip2 生产 gear serve）**
`_frame_inputs` 整体 **14.55ms** = to_frame 2.0 + **pipeline 整把 4.5-10.6（steps 仅 0.2-0.7，差值是 dict↔EnvTransition 转换包装税）** + ids 截断 0.1 + SigLIP 图像 1.0 + unfold 5.9；noise 0.07 / postprocess 0.43。真实 infer×3：total 261-281 / model 247-256 / **gap 14-25**。整个客户端链没有 186ms。

**③ 口径对账（10-14 spot 产物）**
summary json 的 `server_processor_ms=186.4` ≡ `total_ms − model_ms` 的 27 次平均——与探针同定义却差一个量级 → 必有结构性离群藏在均值里。

**④ 逐调用分布实锤（dbg_percall_1015.sh，env `APXINF_GE_PERCALL=1` 灌入 npu_ge.infer，1 集 object t0 seed7）**
```
首调用: total=4135.9 model=270.9 gap=3865.0   ← eager NPU 算子编译一次性成本
稳态:   total≈277    model≈250    gap≈29（21-39 波动,32 次）
```
186 = 3865 摊销 + 稳态零头。**真凶：npu-ge 路径无 warmup**（eval_libero 只对 npu-torch 调 warmup），预处理宿主的 eager torch_npu 算子（to(npu)/resize/mul）首执行编译 ~3.9s 全部进了首调用。

## 修复（两处，外层仓 + robo_src 已同步）

1. `src/apxinf_robo/npu_ge.py` — `GeServePi05Policy.warmup()`：合成 obs 跑 `_frame_inputs` + postprocess + gear 模式下 bucket 握手；**不发引擎请求**（serve 是常驻生产进程无需热身）、零数值路径改动；静态桶模式跳过 bucket 构造（避免 warmup 短 L 触发冷烤）。
2. `src/apxinf_robo/cli/eval_libero.py` — warmup 调用条件从 `engine == "npu-torch"` 放宽为「policy 暴露 warmup 即调」。

## 验证（dbg_percall2，同 seed 同任务同芯）

| 指标 | 修复前（10-14 spot） | 修复后 | Δ |
|---|---|---|---|
| inference_ms（per-call 均值） | 433.3 | **273.6** | **−159.7（−37%）** |
| server_processor_ms | 186.4 | **25.3** | −161.1 |
| model_ms | 246.9 | 248.1 | —（设备侧不变） |
| success（object t0） | 1.0 | **1.0** | 行为保持 |
| episode 推理总时长 | 11.70s | 7.39s | −37% |

首行 gap 3865→32.6ms，warmup 吸收全部一次性成本。I9「inference 433→~250」实质达成。

## 剩余与不去做的

- **稳态 gap ~25ms**：unfold 5.9 + pipeline 转换税 4-10 + to_frame 2.0 + 图像 1.0 + post 0.4。压缩它要绕开 lerobot pipeline 手搓 batch——背离「与 recorder/官方链同代码路径」的安全设计，ROI 低，**不立项**（记观察）。
- **L 漂移（144/145/146/147 本集全出现过）**：gear 模式零感（model_ms 不随 L 波动）——原「顺带修 L 漂移」需求消失。
- 原 I9 的 tokenize 缓存/查表方案：前提（186ms 在 tokenize）已证伪，方案归档不实施。

## 副产物

- 容器默认 PYTHONPATH 带 `.../python/site-packages` 与 `.../tbe`——`docker exec -e PYTHONPATH=...` **覆盖**式传参会打死 torch_npu 的 GE 初始化（`ModuleNotFoundError: tbe` → SetPrecisionMode 500001）；必须 `PYTHONPATH=...:$PYTHONPATH` 追加式。
- fleet_watch 的 `alive_orphans` 实为数的是容器 init 全部非僵尸子进程（= gear serve 本体 8 只，合法住户），已改名 `init_children_alive` 防误读。
- 逐调用计时开关 `APXINF_GE_PERCALL=1` 常驻 npu_ge（诊断基建）。

## 工具

probe_dyn/：`probe_tok_cost_1015.py`、`probe_frame_breakdown_1015.py`（分项计时，两轮 init ~200s 认知成本）、`dbg_percall_1015.sh`（v2 = 修复后复跑，results 文件 dbg_percall2_*）。
