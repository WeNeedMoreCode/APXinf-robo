# M3 真实 e2e 稳态延迟 bench：310ms/调用 = torch 基线 0.82×，延迟验收线达成

日期：2026-09-21（晚班）　前置：[step0 残差 bisect 结案](2026-09-21_m3-flow-step0-residual-bisect.md)（parity 收口，裁判移交 LIBERO）

## 一句话

**全口径稳态 per-call ≈ 310.3ms（vision 66.82 + prefix 140.39 + flow 103.08，P50 ×10，chip6，t712fix OM）= torch_npu 基线 model_ms P50 376.4ms 的 0.82×（快 18%）——M3 延迟对标"显著优于 378ms"达成**。口径终于对齐：这是含全部 host glue 的完整调用链（每步 styles h2d、36 路 kv host 中转 d2h、x 逐步 d2h），与 torch 的 forward 全口径可比。styles host 计算 173ms/步（bring-up 定罪）改为一次性预计算缓存（2.06s/进程，10 步调度固定 ⇒ 跨调用不变）。

## 数字表（GEB_E2E_BENCH=10，稳态 rerun）

| 段 | 稳态 P50 | 设备侧（段 bench） | glue 增量（如实计入） | 备注 |
|---|---|---|---|---|
| vision | 66.82ms | 56.11 | +10.7ms | **111 路 d2h = LN aux 输出（trap #17 绑定副作用）——生产只读主输出可免，非必需 glue** |
| prefix | 140.39ms | 115.99 | +24.4ms | 36 路 kv d2h 13MB = **真 glue**（host 中转架构，pk/pv 设备直连可消） |
| flow（10 步/调用） | 103.08ms | 75.7 | +27.4ms | 37×2 styles h2d/步 + x d2h 3.2KB/步 + ins 组装；min 87.5 |
| **合计** | **310.3ms** | 247.7 | +62.6ms | **= 376ms 基线 0.82×** |

一次性成本：styles 预计算 2.06s/进程（可设备化到 ms 级或持久缓存，非热路径）；三段 OM 加载 + 2.1GB 嵌入查表 ~100s/进程（懒加载优化项，后置）。

## 口径注记（与 376ms 基线的可比性）

- torch 376ms = model_ms P50（TorchAir 稳态 forward，含模型内 host：styles/euler/mask 构造全在 forward 内）。
- 我们 310ms = 三段 OM run + sync + 输出 d2h + styles/state h2d——同层口径（"inputs ready → outputs ready"）。
- **不含**（两侧都不含或对称小项）：图像预处理（torch 侧在 total_ms 383.8）、噪声生成、actions 后处理；x0 token 查表（prompt 固定可缓存；LIBERO state 离散化只改少量 token，host 开销小）。
- vision 的 +10.7ms aux d2h 是保守计入（生产可免）——**生产口径真实值 ≈ 300ms（0.80×）**。

## 优化空间（按性价比排序，当前非阻塞）

1. **pk/pv 设备直连**（prefix OM 输出 buffer 直接作 flow 输入 bind，免 13MB d2h+h2d）：预计 −15~25ms
2. **styles h2d 批量化**（37×2 次 copy 合成 1 次 300KB 批量上传）或设备化投影：预计 −10~15ms
3. vision aux 输出不下载（bench harness 侧改动）：−10ms
4. 合计潜力 → **~265-275ms（0.70-0.73×）**，与纯设备侧 247.7 的差距收窄

## M3 剩余

**LIBERO 对标**（9/10 基线，验收 ≥9/10−1pp）——集成工程：真 tokenizer（当前 placeholder token ids）、图像 patch 管线（当前 golden patches）、pyo3/服务链接入 LIBERO harness、actions 反量化。parity 残差已定性 fp16-class（见前置 summary），行为裁判在此。

## 工具

`GEB_E2E_BENCH=<N>`：三段 e2e 各自稳态 rerun 循环（vision/prefix 在 e2e_run 内、flow 在 10 步循环外再包 N 次调用级循环；styles 走预计算缓存 = 生产口径）。
