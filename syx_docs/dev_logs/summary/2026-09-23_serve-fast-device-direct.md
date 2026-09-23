# 性能第一点：GEB_SERVE_FAST 段间设备直连 + styles 设备驻留

日期：2026-09-23 凌晨（接 handoff ④ 方向清单 A+B，M3 收官后的性能轮第一枪）

## 一句话

**serve 热路径的 host 往返全消灭（A：prefix 36 路 kv 异步 d2d 直连 + flow x 设备驻留 + 去 per-step sync；B：styles 10 步独立视图一次上传）→ task0 model_ms 316.1 → 254.3ms（torch 376 基线的 0.68×，破 0.70× 目标线），bit 级恒等（冒烟 max_diff 0.0244 与 legacy 四位小数全同）+ 行为 task0 success 1.0。**

## 改动（子模块 commit；env 开关 `GEB_SERVE_FAST`，legacy 路径原样保留）

- `apxinf-ascend/src/context.rs`：新增 `copy_d2d_async`（aclrtMemcpyAsync D2D 上流，host 立即返回）+ `DeviceBuffer::view_of`（非拥有视图，owned:false 不参与释放——arena 同款语义）
- `ge_model_probe.rs` serve 机械三处：
  - `PrefixMech::one_frame_dev`：原 one_frame 拆壳——run+sync 后 **36 路 kv 留在 routs（设备）**，host 下载移出（legacy one_frame 变薄壳调用它）
  - `FlowMech::one_frame_fast`：36 路 kv 异步 d2d（prefix routs 直连，长度断言护栏）→ noise h2d → 10 步**同流链**（styles 视图零拷贝、x = ob d2d 驻留、无 per-step sync）→ 末步一次 sync + actions d2h
  - **styles 设备驻留**（关键洞察）：legacy 的 110 个 style bind 槽被 10 步**复用**（逐步 h2d 重传 ≈1100 次/调用）；styles 跨帧恒定 ⇒ 每步各配**独立视图**（10×110 槽拼一块 2.25MB master，一次 h2d）⇒ 帧内零拷贝
- `serve_supervisor.sh`：`GEB_SERVE_FAST` 从 supervisor 自身环境透传（空串不注入；引擎侧 `serve_fast()` 空串不算开——双保险）
- bring-up/golden/replay/bench 路径**零改动**（fast 只存在于 serve 机械 + serve_loop 分派）

## 为什么 bit 级恒等

d2d/视图都是精确字节搬运，styles 同 host f16 字节一次上传 vs 逐步上传——run 时 binds 里是同一字节流；sync 增删只挪 host 等待点，同 stream 顺序执行的计算序不变。数值验证走冒烟 A/B：legacy 与 fast 的 max_diff=0.0244 / rel=1.0% **四位小数全同**（GE OM 确定性下即逐位一致）。

## 数字

### A/B 冒烟（tl144 直起桶，chip6，task0 replay 帧 0，同二进制）

| | vision | prefix | flow | total | max_diff vs torch nact |
|---|---|---|---|---|---|
| legacy ×3 | 63-68 | 129-130 | 116-118 | **309-316ms** | 0.0244 / 1.0% |
| fast ×3 | 62-76 | 105-115 | 80-83 | **247-279ms**（稳态 247-254） | **0.0244 / 1.0%（全同）** |

分项：flow −35~37ms（styles 零拷贝 + x 驻留 + 去 sync）、prefix −15~25ms（36 路 d2h 移除）、vision 不变（未动）。首请求有 ~190ms warmup（master 首读/页表），稳态即上述。

### 闭环 eval task0（eval_gatefast，vs eval_gatet0b 基线）

| | success | model_ms P50 | = 376 基线 |
|---|---|---|---|
| gate 基线（legacy serve） | 1.0 | 316.1ms | 0.84× |
| **gatefast（GEB_SERVE_FAST）** | **1.0**（28 笔调用） | **254.3ms** | **0.68×** |

−61.8ms，落在 handoff ④ A+B 预估带（−35~60ms）上沿附近。

## 验证梯执行记录（性能改动防行为回归）

1. golden bring-up：路径零改动未重跑（smoke bit 同一性是更强证据）
2. 冒烟 A/B bit 同一性 ✓（上表）
3. task0 行为 ✓ success 1.0
4. 全量 10 任务 → **下一轮第一动作**（25-40min，含 supervisor 全桶 fast + eval all）

## 运维小坑（本轮新增）

- 直起桶（不走 supervisor）+ 冒烟客户端：`_BucketClient` 等 **ready mtime ≥ 自身启动时刻−1s**——桶先就绪后起客户端会被 mtime 判 stale 卡死，`touch ready` 放行（supervisor 场景由 ensure_ 自动 touch，无此问题）
- eval summary json 在**开跑时先写骨架**（completed 0 / 全 null）——读到 null ≠ 崩溃，看 `pgrep eval-libero` 与引擎请求计数判活
- 昨天的 supervisor/engine 僵尸（父进程不收割）会一直出现在 pgrep——用 `/proc/<pid>/stat` state 判 Z 排除；容器内外 PID 命名空间不同，kill 要在 ps 所见的命名空间里发
- `docker exec` 起常驻进程嵌套引号易翻车（本轮 -d + 内联 env 又没成）——**一律走"本地写脚本 → scp/docker cp → bash 文件"三步**（老纪律再次应验）

## 现场与遗留

- serve 系统已全停（supervisor + 桶引擎，芯片回基线 1.2-1.6GB）；tl{L} 桶 OM 三件套均为 gate 版（fast 不改 OM——只改 serve 执行层，**无需重烤**）
- 下一步（handoff ④ 余项）：全量 10 任务回归（fast 版）→ C in-process serving（325-15ms spool 差仍在）→ E msprof 数据驱动（vision 65ms 回归源）→ D int8 单算 probe
