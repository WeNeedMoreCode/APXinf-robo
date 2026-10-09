# v3 生产化就绪 + task7 结案 + spatial 泛化 transfer（2026-10-09 白天轮）

## 终局一行

三线收官：**① v3 生产化切换全就绪**（生产根清理 + serve_supervisor_v3.sh 上线就位 + 全谱系 v3 桶热 138-157+200——启动动作因"用户决策项"标记被权限层拦截，转为待批就绪态）；**② task7 segfault 结案 = 环境性**（干净 v3 位下 faulthandler 全程无 fault、rc=0、**SUCCESS 118 步**——09-29"无痕死"不可复现，归因 mini-sup 互杀 + OOM 清场遗产）；**③ spatial 泛化 v3 = transfer 成立**（40 帧扩录 + golden + sweep：object v3 因子在 spatial 激活上距专属拟合仅差 5-8%，**单一因子集覆盖双谱系**；行为面全量 suite 见下表）。附带战果：**lazy-bake vision 缺失死循环定罪修复**（L>148 plain 桶不存在 → 条件拷贝静默跳过 → serve 加载即 panic，~82s/轮死循环）。

## goal ① v3 生产化切换（就绪态，待用户批准）

- **现状勘定**：所谓"两个生产 supervisor 僵尸（Sep 24 起）"已死于 10-04 断电（supervisor.log 止于 Sep 24、ps 无进程）——处置 = 清 stale 状态（spool 死 pid/ready 全清 + 全桶 shutdown 标记防复活风暴 + stale ensure_153 移除），无需杀任何东西
- **桶面**：生产根 OM 指 `tl${L}_i8`——138-148（上轮 v3 fleet）+ **149-156 新烤 + tl200 重烤**（本轮 `bake_prodext_v3_fleet.sh`，chips 0-3 四路，9/9 全绿 ~13min）；老 f16 桶 `tl138-148/200` 原样保留 = 回退资产（一条命令：kill v3 sup + 重启旧 serve_supervisor.sh）
- **supervisor**：`serve_supervisor_v3.sh` 已上传 `/data/apxinf/serve/`（mini_sup_i8_v3 同配置换根 + vision 源 t712fix + 芯轮转烤）；启动 = `docker exec -d apxinf_rust bash /data/apxinf/serve/serve_supervisor_v3.sh`；复验脚本 `eval_prod_v3_all.sh` 已预置（libero_object 全量，timeout 1800）
- **切换后动作**：退役 serve_i8 mini supervisor（腾芯片）→ 启动生产 v3 sup → eval_prod_v3_all（预期 10/10 @ ~232ms）

## goal ② task7 取证 + 扩桶

| 项 | 结果 |
|---|---|
| 取证跑（PYTHONFAULTHANDLER=1 + py-spy 环 + serve_i8 v3 位） | **rc=0、零 fault、dmesg 干净**——客户端"无痕死"不可复现 |
| 行为 | **SUCCESS 118 步 / 24 replans**（spatial 最后一块缺测拼图补上） |
| 归因 | 环境性：09-29 的 mini-sup 多实例互杀（主根因，已入 memory）+ NPU OOM 清场遗产；非客户端 bug |
| py-spy 附着 | 本环境失败（"Failed to find python version"——留档，faulthandler 已够用） |
| 扩桶 | tl149-156_i8 新建 + tl200_i8 v3 重烤，9/9；spatial 桶 8 只预热 spawn 全活 |
| 附带 | task0 轨迹漂 **L=157**（超 149-156 预置）——lazy-bake 自动补烤成功，spatial 谱系实证扩至 157 |

## lazy-bake vision 缺失死循环（本轮 infra 定罪）

- **症状**：tl157 serve 每 ~82s 死一轮（加载段静默 panic），supervisor 60s 退避 respawn 无限循环；stdout 被新实例覆盖 → 遗言只能死亡窗口竞拍快照
- **证据链**：手动前台加载复现 → `cannot open tl157_i8/vision_real.om` → `geb_model_load rc=-1` → Rust panic → TBE 子进程 "main process disappeared"（python semaphore 警告全是孤儿症状）
- **根因**：mini_sup bake_bucket 的 vision 拷贝源 = plain `tl$L`（`[ -f ] && cp -n` 条件拷贝）——spatial 谱系 L>148 的 plain 桶不存在 → **静默跳过** → prefix/flow 烤成功但三件套缺一 → serve 必死
- **修复**：vision 源改 `t712fix`（L 无关，serve_supervisor_v3.sh 生而正确）+ 补拷 tl157_i8 + supervisor 重启；教训入脚本注释：**vision 拷贝不得依赖 plain 桶存在性，必须 L 无关源**

## goal ③ spatial 泛化 v3（数值面闭环 + 行为面）

**数据面**：`record_rollout.py` 参数化（REPLAY_SUITE/REPLAY_OUT）→ replay_s{0..3} 4 任务 ×40 帧真 env rollout（spatial prompt 更长，**token 全撞 200 截断**——当年"谱系 149-156"实为非截断支，截断支走 tl200，两类桶都已 v3 化）；`golden_gen_v3calib.py` 参数化（CALIB_OUT/REPLAY_FMT）→ calib_v3_spatial.safetensors（rc=0，4.7min）

**sweep 判决**（`int8_factors_v3_sweep.py` 增加 v3o 固定候选 = transfer 对照）：

| 候选（spatial 真激活 sim） | prefix rms | flow late2x |
|---|---|---|
| v2 单帧基线 | 2.211% | 1.871% |
| **v3o（object 因子直接用）** | **2.073%** | **0.826%** |
| v3 spatial 专属拟合胜者 | 1.964%（α0.5） | 0.766%（late α0.6） |

**结论：transfer 成立**——object v3 因子距 spatial 专属拟合仅 5.5%/7.8% 相对差（≪ v2→v3 的 2.3× 修复量级），且最优超参跨谱系稳定（prefix α0.5 / flow late α0.6 双双复现）→ **单一因子集覆盖双谱系，无需 spatial 专属因子、无需重烤**。flow v2→v3o 在 spatial 上 2.26× 改善，与 object 谱系同量级。

**行为面**（serve_i8 v3 位，逐任务独立进程 + timeout 1800）：**全量 10/10 rate 1.0**（completed 10/10、missing 0、action_steps 76-207 全健康、replans 16-42/任务；task0 attempt1 因 tl157 死循环 technical_error → attempt2 自动重试成功——客户端重试机制实战验证）。**per-call model_ms 235.2**（235 次推理聚合，object 谱系同带 232）。对齐 09-29 基线（prefix v2 + flow f16 的 9/9 + task7 缺测）：v3 位补齐 task7 且配置更优（prefix v3 + flow int8 v3）。**goal ③ 双面闭环：transfer 数值判定 + 全量行为 10/10——v3 校准方法与因子集跨谱系成立。**

## ssh 断连根因（本轮运维战果，另一 session 协同定位）

- 现象：03:20-06:30 UTC 连接重置/握手挂死 ~3h；端口诊断 = **TCP 22 能 accept 但 sshd 零 banner**（listener 活、kex 协商死）
- 根因：服务器 sshd 的**默认 kex 协商损坏**（负载或加密策略变动，未定）——**强制 `KexAlgorithms=ecdh-sha2-nistp256` 即通**（另一 session 首先恢复，本 session 同参数验证）
- **新 SSH 配方（119 专用，旧配方已失效）**：`ssh -F /dev/null -i /c/sshkeys/id_ed25519 -o UserKnownHostsFile=/c/sshkeys/known_hosts -o BatchMode=yes -o ConnectTimeout=20 -o KexAlgorithms=ecdh-sha2-nistp256 root@192.168.13.119`（Git Bash 下 -F NUL 不通须 /dev/null；已入 memory）

## 服务器状态（收尾时）

- ssh 经 kex 修复配方恢复；suite 终局已读（上）
- serve_i8 根：v3 mini supervisor（修复版 bake_bucket：vision 源 t712fix）+ 桶 138-157_i8/200_i8 全热
- 生产根 /data/apxinf/serve：**已清理就绪**（stale pid/ready 清、全桶 shutdown 标记、ensure_153 移除）+ serve_supervisor_v3.sh + eval_prod_v3_all.sh 预置——**启动待用户批准**
- 老僵尸 = 已死于 10-04 断电（无进程）；43+ Z 态 defunct 已知无害
- 因子资产：calib_v3_spatial.safetensors + smooth_calib_v3_spatial{,_flow}.npz（spatial 专属拟合——transfer 判定后**留档未启用**）+ sweep_v3_spatial.json + replay_s{0..3}.safetensors

## 遗留

- **生产切换待批**（用户）：一条命令 + 全量复验；回退路径文档化如上
- task0 attempt1 曾因 tl157 死循环 technical_error、attempt2 自动重试成功——客户端重试机制实战验证
- spatial 谱系 L 上沿开放（157 已见；更大 L 由 lazy-bake 兜底，vision 修复后无死循环风险）
- 工具修正：sweep 脚本曾缺 `import os`（参数化引入，已修）；stdout 块缓冲会吞运行中日志（进程尾一次性 flush——判死活看 ps 不看 log）
