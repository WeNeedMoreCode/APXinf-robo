# 2026-10-12 战报——动态分档 HYBRID 生产化落地（① 施工 + 四连坑取证）+ OM 并行预载（② 部分）

终局一行：**① 动态分档以 HYBRID 形态上线**（prefix 22 档单 OM + flow per-L 静态池 + 每芯一 serve，CANN SetDims 四连坑全部取证绕道）；行为面 object 0.8 / spatial 0.9 / goal 1.0（26/30，边际任务翻转——生产 t3 本需重试；重试结果见文末）；延迟 237-250ms/call。**② 冷启动 OM 三段并行预载落地（52s→10-22s）**，ckpt 选择性读与 inproc 未及（时间耗在 ① 的运行侧四连坑）。**③ 卡点确认**：服务器仅一只 π0.5 checkpoint，多 ckpt 泛化无法开工（管线已全参数化就绪）。

## ① 动态分档 HYBRID 生产化（goal 1）

### 路线演变：单 OM 全 gear → HYBRID

spike（上轮）四绿后按「prefix/flow 双双 gear 化、单 serve 多 L」施工，真图运行侧连撞四坑，最终形态：

| 件 | 形态 | 缺口原因 |
|---|---|---|
| prefix | **22 档单 OM**（1.95GB，int8 v3 全七投影 ×18 层，烤时 465-472s 一次） | 无 |
| flow | **per-L 静态 OM 池**（22 只现存 tl{L}_i8 资产，进程内 22 句柄按 L 换柄执行） | styles 是运行期内容的静态 shape Data 输入——无法 Const 化，而静态 Data 混入动态集即坑 ① |
| vision | 静态单 OM（共享拷贝） | 与 L 无关 |
| serve | **每芯一只**（验证期空芯 0-3；生产位 4-7 被 v3 桶占 15-17GB，gear serve +6GB 会顶爆 24GB） | — |
| 客户端 | npu_ge.py `_GearClient` 芯轮询（`gear_mode` 标记路由；L 走 payload 原样） | — |

### CANN 9.0.1 SetInputDynamicDims 四连坑（本轮主战场，全部取证）

| # | 坑 | 症状 | 取证/解 |
|---|---|---|---|
| 1 | **静态 Data 混入动态输入集 → 档位匹配必败** | 145012 | spike v3 最小复现（3 动态+1 静态即炸）。解：静态内容全 Const 化（g1/g2/sm 因子/折叠 bias 不注册）；Const 走 Case 参数不占 Data 位 |
| 2 | **payload 与 dynamicDims 选项是两种格式** | 选项混入静态尾维 → 编译 rc=-7（四变体旋钮 bisect 全败反推） | 选项串=纯 -1 位值；SetDims payload=全部动态输入完整 dims（含静态尾维，注册序拼接） |
| 3 | **payload ≤ ACL_MAX_DIM_CNT(128)** | 定值动态输入（每档恒值绕道）全深 186 维被 C++ 截断 → 145012 | 大图只能压缩动态输入数（Const 化）；「legacy Const 墙」系坑 2 的误判 |
| 4 | **多动态输入须一次调用带全维** | 逐输入调用 145012 | index=0 + 拼接全部（spike v2 S2 定式） |

配套：`geb_run_gear`（C++ 自动补 gear-info 输入 + SetDims）、`copy_h2d_async_sized`（实际行 < max buffer 的按长度 H2D——等长断言口会炸）、段局部 gear 门（env 全局的 gear_mode 会误伤 flow 段 Const 化 → 池 OM 输入数错位 rc=-2）。

### 行为面（三谱系全量，gear 舰队 4 芯）

| 谱系 | gear 舰队 | 生产 v3 基线 | 备注 |
|---|---|---|---|
| object | **10/10**（首跑 8/10 + 重试 t3/t7 双过） | 10/10（t3 需重试） | 重试口径与生产同式；first_action_checksum 差 ~1%（分支 kernel 编译差异固有） |
| spatial | **9/10**（t4 首跑+重试二连败，520 步打满） | 10/10 | t4 = 唯一硬回归（真行为 miss） |
| goal | **10/10** | 10/10 | 含 L=200 截断支 ✓ |

延迟：per-call 237-250ms（vision 58 / prefix 100-107 / flow 74-76）vs 生产 229-235ms——prefix 分支派发 +~5ms。

失败任务重试（同 seed、生产 t3 重试先例同式）：见 `eval_retry.log` / 战报末尾更新。

### 资产与提交

- 引擎（apxinf/ascend-port，12 commits `6dd0817..c378fbd` 已 push）：gear FFI / GEB_DYN_LLIST 构图 -1 化 / HYBRID flow 池 / sized h2d / 并行预载
- libge_builder.so：+gear census/run_gear/cur_output_dims + load mutex（源码副本 syx_docs/dev_logs/probe_dyn/ge_builder.cpp）
- 服务器：/data/apxinf/serve_gear_supervisor.sh（HYBRID 版）、eval_gear_all.sh、om_cache/tl_dyn/{prefix(22 档),vision}_real.om、serve_gear/ 舰队（空芯 0-3）
- probe 资产：dyn_gear_probe2/3.c、gear_load_probe.c、gear_inq_probe.c、bisect_gear_bake.sh、send_gear_req.py、run_gear_serve_dbg.sh
- skill ge-offline-om 动态分档节：四连坑全录

## ② 冷启动 lazy（goal 2，部分交付）

- **OM 三段并行预载**：`preload_e2e_oms`（3 线程 + C++ load mutex + 线程绑主 context——裸线程 rc=-3 实测）52s → **10-22s**。
- 未及：ckpt 选择性读取（63.7s 白 parse——sm/g Const 化后 serve 构图对权重的消费面进一步缩小，stub 化收益更大）、inproc eval 全链（apxinf_npu 9.0.1 libs + 客户端去 torch_npu）。
- 注：HYBRID 下冷启动 = 每芯一次（prefix 1.95GB + flow 池 22 只 ≈ 11GB 装载 ≈ 1-2min）。

## ③ 多 checkpoint 泛化（goal 3，卡点确认）

服务器 `/data/apxinf/weights/` 仅 `pi05_libero_finetuned`（+ paligemma 视觉塔权重，非策略 ckpt）；`pi05_lerobot/` 为代码无 ckpt。**无第二 checkpoint 可开工**。管线已全参数化（record 换 SUITE/ckpt → golden → sweep v3o 对照 → transfer 判定 → eval），ckpt 到位即可跑。

## 遗留与观察项

- gear 舰队行为面 26/30（边际翻转）：若重试通过 → 与生产同口径；不通过 → 分支 kernel ~1% 漂移的系统性代价，需权衡（档内核二进制 = 逐档独立 FE 编译，与 per-L 静态 OM 非逐位同）。
- prefix 档 OM 只认档表内 L（137-157+200）；档外 L 需扩档重烤（465s）或回退 per-L 桶。
- 生产切换未执行：v3 桶（4-7 芯）与 gear 舰队（0-3 芯）并存；转正 = 互换芯位 + eval 默认根切 serve_gear + supervisor 单实例纪律。
- serve_gear 冷启动含 flow 池 22 只装载（~1-2min/芯）——lazy ckpt 未做前这是主要冷启项。
- 119 上行断流 workaround（gzip+480B 分块）本轮全程使用；引擎源码迭代改走 git diff 补丁通道（秒级）。

## 失败任务重试结果（补录）

- object t3：**过**（127 步）；object t7：**过**（122 步）→ object 10/10（重试口径）
- spatial t4：**二连败**（两轮均 520 步打满）→ spatial 9/10，t4 为 gear 路线唯一硬回归（分支 kernel ~1% 数值漂移在该任务放大为行为 miss；候选对策：t4 走 per-L 静态桶专属路由、或该 L 档回退静态 OM 混跑——未施工）
