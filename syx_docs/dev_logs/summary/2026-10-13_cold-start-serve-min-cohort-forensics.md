# 2026-10-13 战报——serve-min 零物化骨架 + 数值「代际」现象取证

终局一行：**① 冷启动 lazy 剩余收口**——零物化骨架 + 39 件 style 并行转置把 from_map_serve 数学段 **17s → 0.53s（32×）**、总 ckpt 段 22→5.7s；PyO3 `GeServeModel.open` 接 `GEB_CKPT_SERVE_MIN`（inproc open **145.5 → 81.9s**）；**② 稳定性长跑**——gear 舰队过夜（11h 空载）零 respawn、内存 124GB 稳定、晨间 spot eval **2/2**（object t0 133 步 / spatial t4 120 步走 151-157 回退）；**③ 多 ckpt 卡点维持**（weights/ 仍仅一只 π0.5）。**过程副产品：一次完整的跨进程数值差取证，判决为 GE 运行时固有的「代际」现象**（非回归、非本次改动引入）。

## ① 冷启动 lazy 剩余（goal 1）

### 零物化骨架（`synthetic_skeleton`）

`Tensor::zeros`（`vec![0u8]` → 大块 calloc → **懒 commit 零页**）替代 LCG 随机填充：占位张量在 GEB_LOAD serve 路径上从不被读（OM 已烤 Const/WCONST 面——昨日已证），7GB 填充是纯冷启动浪费；零页不 touch 不计费，**顺带砍掉 serve 的占位 RSS**。`synthetic` 本体保持随机（bench/bake 计算要用值）。

### 39 件 style 并行转置（`parallel_transpose`）

骨架零化后剩余大头 = styles 链 39 件 [3w,w]/[w,w] 转置（~925MB cache-hostile 列写）。先顺序 take（纯 move）再 `std::thread::scope` 分块并行（chunk 独占所有权无锁）——**不引 rayon，引擎 crate 零新依赖**。

### PyO3 open 接 serve-min

`from_safetensors_serve` + `GeServeModel::open` 按 `GEB_CKPT_SERVE_MIN` env 分流（与 probe 驱动同约定；PyO3 open 无 bake 面，不需要 GEB_SAVE 护栏）。eval wrapper `cann901_eval_inproc.sh` 已加该 env。

### 数字（全部实测）

| 项 | 前 | 后 |
|---|---|---|
| from_map_serve 数学段 | 17.0s | **0.53-0.72s** |
| ckpt 总段（含 io 5.5s 不动） | 22s | **5.7s** |
| inproc（PyO3）open | 145.5s | **81.9s** |
| inproc per-call | 239.5ms | 236-241ms（无回归） |

bit 级验证：同代际内 **zero/rand 填充、并行/顺序转置全部逐位一致**；inproc actions 与 spool serve 逐字节同（4f46a679）。引擎 `298694a`（ascend-port，已 push）。

### GEB_PRELOAD_EARLY 处置：退役（不修）

该旋钮的价值 =「ckpt 解析期间并行预载 OM」。serve-min 后 ckpt 数学段只剩 ~0.5s，预载提前量从 ~15s 缩到 **~2s 以下**——修复 107000 的 ROI 消失。早载线程代码保留（in-seg 预载不受影响、正常工作）。

## ② 数值「代际」现象取证（本日主体工程，结论先行）

**现象**：同一 seed-7 L=144 payload，生产 gear 舰队（昨日 14:32 spawn）回 A（md5 8502b68e），今日任何新 spawn 的 serve 回 B（4f46a679）——actions 差 ~0.3%。

**排除链（每格一个实验）**：

| 嫌疑 | 实验 | 判决 |
|---|---|---|
| 零物化填充被读 | GEB_SM_ZSCOPE=rand（旧随机占位+新代码）@chip2 | = B，填充无罪 |
| 并行转置/重构 | GEB_SM_SEQ=1（旧顺序路径逐字复刻）@chip2 | = B，重构无罪 |
| 二进制本身 | /proc/PID/exe 恢复昨日生产二进制，干净 harness 重跑 @chip2 | = B，二进制无罪 |
| 同源重建 | git HEAD 源重建（headrb）@chip2 | = B |
| spawn 机制 | supervisor 脚本复制成测试 ROOT 单芯版 spawn @chip2 | = B，机制无罪 |
| 芯片异质性 | chip0/1/2/3 生产互拍（A 逐位同）；新 spawn 在 chip2/chip4 均 B | 芯内逐位确定，非芯问题 |
| 文件代际 | OM/ckpt/smooth 因子 mtime 全部早于生产 spawn | 无文件变动 |
| 环境/库 | /proc/environ diff（仅 4 行无关差）+ /proc/maps 全同 | 无差 |
| 进程内漂移 | 生产进程对同 payload 两次请求逐位同；昨日 #8001/8002 系不同 payload | 无漂移 |

**终判**：判决变量是**进程 spawn 的时间代际**——昨日 ≤14:32 的进程全体 A，今日新进程全体 B；同代际内（跨芯、跨二进制、跨填充）逐位一致。机制未明（候选：设备运行时 per-process 调度序在首跑定形、含原子累加的 kernel 内归约顺序因上下文而异）。量级与已知「gear vs 静态桶 ~1%」「t4 数值敏感」同类——**GE 运行时固有属性，预先存在，非回归**。行为面双代际都过（A 代：昨日 30/30 + 今日 spot 2/2；B 代：本日全部 bit 对拍 + smoke）。

**取证方法论收获**：① spool serve 会吃掉旧 resp 文件——对拍必须「发完即拷贝」；② 多 serve 共抢一个 spool 目录时请求会被任意一只抢答——**每次测量前必须清场并验证单实例**（`test_serve_cleanup_1013.sh` 按 env 匹配收尸）；③ GE 每次进程启动在 /root/ascend/atrace 写 per-spawn trace 目录；④ 对拍实验的对照与实验组必须同芯同时代设计。

## ③ 稳定性长跑（goal 2）

- **过夜观察**（14:38 → 次日 01:43，~11h 空载）：4 芯 ready 文件未重触摸（无 respawn）、supervisor.log 停在初始 spawn（无风暴）、available 124GB 稳定、双 supervisor（gear 928081 + v3 648516）健在。
- **晨间 spot eval**（spot_eval_1013.sh，新 jsonl）：object t0 **success 133 步**、spatial t4 **success 120 步**（L=155 走静态回退——回退桶过夜健康）。
- 孤儿 helper 367 → **414 只**（~30GB，昨日 eval/bake 新增 47）——清理仍待用户决策。

## ④ 多 checkpoint（goal 3）：卡点维持

`/data/apxinf/weights/` = paligemma + pi05_libero_finetuned，无第二只 π0.5。管线就绪。

## 服务器终态（04:00 UTC）

- 生产 gear 舰队 4 芯 RDY（**旧二进制 A 代际**，spot 2/2 验证后未动）；supervisor 单实例；BIN 路径已就位**新优化二进制**（298694a，下次 respawn 自动生效——**舰队重启决策留给用户**：当前 A 代际健康运行，无紧急性）
- cp311 pyo3 .so 已重建部署（engine_py/apxinf，serve_min 支持）
- 回退桶 tl151-157@芯 6/7 由 v3 supervisor 认养
- 测试资产已清场（serve_gear_test*/supervisor_test2 全灭）

## 遗留与观察项

- **代际现象机制未明**（观察项级——行为面双代际都过；若未来跨代际 bit 对拍需求出现，需同代际设计）
- **414 只孤儿 helper ~30GB**：待用户决策
- **舰队换新二进制**：等下次自然 respawn 或用户授权重启（supervisor ctrl stop/ensure 走起即可）
- GEB_PRELOAD_EARLY 退役（本日判决，非阻塞）
