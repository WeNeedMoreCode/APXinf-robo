# 2026-10-12 战报（续二）——gear 转正判决执行 + ckpt 选择性读取（serve-min）落地

终局一行：**① gear 转正执行完毕**——三谱系全量复验 **30/30 真跑**（object 10/10 / spatial 10/10[首跑 9 + t4 回退面补全后 retry 过] / goal 10/10），eval 默认根切 serve_gear、v3 object 桶（tl137-148 十二只）退役、supervisor 单实例；**② serve-min 落地**——ckpt 选择性读取数学段 **62.0→17.0s（−45s/芯）**、全舰队部署、bit 级对拍闭环（actions max_diff=0.0）；**③ inproc 未做**（前置摸清留下轮）；**④ 多 ckpt 卡点维持**（仍仅一只 π0.5 checkpoint）。

## ① gear 转正判决（goal 1）

### 复验数据（全部真跑，本轮新 jsonl）

| 谱系 | 结果 | 备注 |
|---|---|---|
| object | **10/10**（115-146 步全健康） | 容器内 eval（上轮的宿主裸跑是环境错位：宿主 python 从来没有 LIBERO 环境） |
| spatial | **10/10**（首跑 9/10 + t4 retry×5 过） | t4 失败两次的根因都是**回退面覆盖不全**（见下），非引擎回归 |
| goal | **10/10**（71-139 步） | 含 t9（上轮撞 L=136 崩 serve 的任务）——26 档表修复实证有效 |

**t4 的 L 漂移谱系修正**：上轮记录 152-156 五档；本轮 retry 实测 **151-157 七档**（L=151×47 主档 + 152-156 + 157×2）。回退表从 152-156 扩到 **151-157 七桶**（tl151/157 本轮新落芯 6/7）后 t4 过（retry5 success）。

**t4 的本质**（维持上轮结论 + 补强）：gear 分支 kernel 与 per-L 桶 ~1% 数值差，t4 对此行为敏感（47 次 replan 累积放大 → 520 打满）；回退路由 = 已知对策，覆盖面必须含谱系全部实测档。

### 转正执行清单（全部完成）

- **eval 默认根** → `/data/apxinf/serve_gear`（npu_ge.py `_SERVE_ROOT` 默认值改，服务器+本地副本同步；eval_gear_all.sh 本就显式指 gear 根）
- **v3 桶退役范围**：object 谱系 tl137-148 十二只全退（ctrl stop + shutdown 落盘，v3 supervisor 永久跳过）；**保留** tl151-157 七只回退桶 + tl200（未活，gear 档表覆盖）——v3 supervisor 保留运行（认养回退桶 pid/respawn）
- **supervisor 单实例**：新版（带 GEB_CKPT_SERVE_MIN=1 + 错峰 40s/芯）14:32:50 上线；老实例 237497 的容器内外 pid namespace 差点造成双实例（`docker exec kill 237497` 报 No such process 因它在容器内 pid 空间不存在——宿主视角 `kill 237497` 才杀掉）
- **回退桶拓扑终态**：tl152/153/154@芯6 + tl155/156/157@芯7 + tl151@芯6（每桶 ~5.3GB 设备内存/15GB host RSS）

### 本轮运维事故与处置（快照）

1. **OOM 风暴**（12:50-12:53）：5 桶并发落桶把宿主内存推爆（available 7GB、swap 满），OOM killer 杀 chip3 serve、chip0/2 连带死。止血 = kill 装载中的 154-156 三桶（ctrl stop 防复活）→ 释放 58GB。**教训：回退桶落桶上限 = 2-3 只/批，错峰 30s+**。
2. **v3 桶退役反转为内存解压阀**：tl137-148 十二只退役释放 ~185GB——从「转正后的动作」提前为「OOM 止血」，一举两得。
3. **宿主 python 环境错位**：eval 在宿主裸跑报 numpy 缺失——上轮/本轮 eval 的正确姿势 = `docker exec -d apxinf_npu bash eval_gear_all.sh`（容器内 python 3.11 + LIBERO 全家桶）；宿主 python3.10 只有 torch 2.10（89 包，从来不是 eval 环境）。
4. **367 只孤儿 ge_model_probe helper**（~27GB host RAM，ppid=容器 init "sleep infinity"，0% CPU）：历次 bake/probe 的 GE helper 泄漏。**未清理（需用户决策）**——本轮内存已通过桶退役缓解。

## ② serve-min：ckpt 选择性读取（goal 2a）

### 机制

`Pi05Weights::from_map_serve`（weights.rs）= **synthetic 骨架（shape 正确占位）+ 消费面真值覆写**。判据 = **Data 输入源必须真值**（binds 物化后进图执行），**Const/WCONST 面（mm 权重）可占位**（预烤 OM 已携带，不占图输入）：

| 消费面 | 件数 | 说明 |
|---|---|---|
| styles 链 | time_mlp×2 + 37 件 AdaRMS style 投影 | host f32 预计算 |
| 嵌入表 | token_embedding [262208,2048] 2.1GB | host 查表 |
| vision Data 源 | patch_b/pos_rep/n1w/n1b/qb/kb/vb/outb/n2w/n2b/fc1b/fc2b ×27 层 + post_LN + **projector bias** | 全部 `s.data()` 进 binds |
| flow Data bias | action_in/out bias（ainb/aoutb） | mm 权重 wt() 在 WCONST 下 Const 化不占输入 |
| 护栏 | `GEB_CKPT_SERVE_MIN` 遇 `GEB_SAVE`（bake）直接 panic | 占位永不可入图 |

### 三层泄漏取证（差异 1.63 → 0.030 → 0.0）

bit 级对拍法：L=144 同配置双桶（SERVE_MIN vs 全量），`send_gear_req.py`（seed=7 确定性 payload）→ actions 350 float 逐字节比 + `GEB_STYLES_DBG` 的 x0/styles checksum：

1. **vision Data 源**（max_diff 1.63→0.030）：vis_head 分岔定位——seg_vision 的 12 类 Data 槽全从 `real` 取，占位被 binds 物化消费。
2. **projector bias**（0.030 不变）：blocks 循环后的 projb 槽。
3. **action_in/out bias**（0.030→**0.0**）：flow 段 ainb/aoutb 图输入。x0/styles checksum 全程 bit 一致（styles 链首轮就正确）。

### 数字

- **from_map 数学段 62.0 → 17.0s**（−45s）；总 ckpt 67→22s；io 5.5-6.4s 不动（全量 mmap；按 header 过滤读留下轮）
- 舰队级：4 芯错峰 spawn（14:32:50-14:34:50），每芯 from_map_serve 16.9-17.4s，RDY 全绿
- 冷启动主体剩余：flow 池 26 只串行装载 27.4s + OM 装载段（from_map 并行化 rayon 与有界并行装载留待）

### 引擎提交

- `ec69a96`（ascend-port，已 push）：from_map_serve + probe 驱动 GEB_CKPT_SERVE_MIN 分支 + GEB_STYLES_DBG checksum 调试钩子
- 服务器部署：weights.rs/ascend_ge.rs/ge_model_probe.rs 全量同步 + release 二进制 13:03/13:22/13:57 三轮迭代
- supervisor（serve_gear_supervisor.sh）spawn env 带 GEB_CKPT_SERVE_MIN=1（bake_dyn 段不带——烤图必须全量）

## ③ inproc（goal 2b，未做，前置摸清）

- npu_ge.py 已有 inproc 分支但 **gear 模式回落 spool**（L397）——支持 gear 需 PyO3 GeServeModel 构造带 GEB_DYN_LLIST/GEB_FLOW_POOL
- 前置三件：apxinf_npu 供给 9.0.1 libs（容器现 8.5.1）、apxinf_py cp311 maturin build（容器 python 3.11）、客户端去 torch_npu（容器有 cpu torch 2.9 ✓）
- 预期收益 ~15ms/call（spool 轮询消除）

## ④ 多 checkpoint（goal 3，卡点维持）

`/data/apxinf/weights/` 仍仅 `pi05_libero_finetuned` + `paligemma-3b-pt-224`——无第二 checkpoint 可开工。管线全参数化就绪（同上轮）。

## 遗留与观察项

- **GEB_PRELOAD_EARLY 107000 未修**（e9e7301 无效实证：主线程 set_current 后 early 线程仍绑不上——in-seg 预载不受影响，early 段 0 装载 2ms 退出；修复留待）
- **367 只孤儿 helper 27GB**：待用户决策清理（kill -9 需批量，本 session 权限受限）
- **t4 回退依赖**：spatial t4 永久走回退桶（151-157 七桶必须保活——v3 supervisor 认养中）；档表外新 L 的通用对策仍是扩回退或扩档表
- eval resume 语义：results-jsonl 有记录（无论成败）即跳过——复验/重试必须换新 jsonl 或归档旧的

## 服务器终态（14:39 UTC）

- gear 舰队：/data/apxinf/serve_gear 芯 0-3 全 RDY（26 档 OM + flow 池 26 + vision），supervisor 单实例 928081（SERVE_MIN 版）
- 回退桶：tl151-157 七只全 RDY（芯 6/7），llist=151-157，fallback root=/data/apxinf/serve
- v3 位：tl137-148 退役（shutdown 落盘）；v3 supervisor 648516 运行中（回退桶认养）
- npu_ge.py 默认根 = serve_gear；内存 available 124GB
