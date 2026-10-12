# Handoff（2026-10-12 轮二 gear 转正 + serve-min → 下一轮压缩用）

## 状态一句话

**goal 三项收口（全数字见 summary/2026-10-12_gear-promotion-serve-min.md）**：① **gear 转正执行完毕**——复验 30/30 真跑、eval 默认根 = serve_gear、v3 object 桶 tl137-148 退役、回退桶扩为 **tl151-157 七只**（t4 的 L 谱系实测 151-157，152-156 的旧记录偏窄）、supervisor 单实例 928081（SERVE_MIN 版）。② **serve-min 落地**：ckpt 选择性读取数学段 **62→17s**、全舰队部署、bit 级对拍闭环（max_diff=0.0；判据 = **Data 输入源必须真值、Const/WCONST 面可占位**）；inproc 未做（gear 模式现回落 spool，前置三件已摸清）。③ 多 ckpt 卡点维持（仅一只 π0.5 权重）。服务器终态：4 芯 RDY + 7 回退桶 RDY + v3 supervisor 认养回退桶。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-12_gear-promotion-serve-min.md）——① gear 转正终态（默认根 serve_gear 已切；回退桶 tl151-157@芯6/7 + llist 同步；v3 桶 137-148 已退役；t4 L 谱系 151-157）；② serve-min（from_map_serve = synthetic 骨架 + Data 输入源真值；GEB_CKPT_SERVE_MIN=1 已在 supervisor spawn env；bake 路径 panic 护栏；引擎 ec69a96 已 push）；③ inproc 前置三件（9.0.1 libs 供给/cp311 build/客户端去 torch_npu）。丢弃：三层泄漏的取证迭代、OOM 止血过程、eval 监控过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-12 晚，见 summary/2026-10-12_gear-promotion-serve-min.md）：gear 已转正（默认根 serve_gear、复验 30/30、v3 object 桶退役）、serve-min 冷启动 −45s/芯 已部署全舰队、inproc 未做、多 ckpt 卡点维持。

**下轮 goal 建议（抄一项即可）**：
1. **冷启动 lazy 剩余**（from_map 并行化 rayon 分层——17s 里骨架生成占大头，零物化骨架（shape-only Tensor）+ rayon 数学是下一步；GEB_PRELOAD_EARLY 107000 未修（e9e7301 无效实证）；inproc：apxinf_npu 供 9.0.1 libs + cp311 maturin build + npu_ge.py gear inproc 分支，省 spool ~15ms/call）
2. **稳定性长跑**（gear 舰队 + 回退桶拓扑过夜观察：supervisor respawn 风暴是否复发、L 档表外新漂移、内存水位；晨间一轮回访式 spot eval）
3. **多 checkpoint 泛化**（管线全参数化就绪：record 换 ckpt → golden → sweep v3o 对照 → transfer 判定 → eval；需先到位第二个 checkpoint）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；**eval 默认生产根 /data/apxinf/serve_gear（gear 位运行中；回退桶在 /data/apxinf/serve 由 v3 supervisor 认养）**；eval 必须容器内跑（`docker exec -d apxinf_npu bash eval_gear_all.sh`——宿主 python 无 LIBERO）；**results-jsonl 有记录即跳过——复验/重试换新文件**；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类、**容器内进程 kill 要 namespace 对齐（宿主 pid 用宿主 kill，docker exec kill 只对容器内 pid）**；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（scp 不可用；引擎源码迭代走 git diff 补丁通道，同一文件二次改动走全文件上传避免叠加）**；docker exec -d 必须脚本文件形态；sshd 断连先 /dev/tcp banner 判层；**回退桶落桶 ≤3 只/批错峰 30s（5 只并发曾 OOM 杀 serve）**。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. 冷启动 lazy 剩余** —— serve 冷启动再压缩 + eval 全链 inproc。
- **为什么**：serve-min 后冷启动 = ckpt 22s + flow 池装载 27.4s + OM 段——主体已从 90s 级降到 ~60s 级；剩余大头（i）from_map_serve 17s 里 synthetic 骨架生成（7GB 随机填充）占大半——占位只需 shape 不需内容，零物化骨架可再砍 10s+；（ii）inproc 消 spool 轮询 ~15ms/call 且架构上消灭 serve 进程面。
- **怎么做**：骨架零物化（Tensor shape-only 变体或惰性填充）；from_map rayon 分层；GEB_PRELOAD_EARLY 的 context 绑定换「主线程激活 + 同 context 句柄传递」重试；inproc = 9.0.1 libs 拷入 apxinf_npu + maturin build cp311 + npu_ge.py gear 分支。验收 = 冷启动计时 + per-call 延迟 + 行为 spot check。

**2. 稳定性长跑** —— 转正后拓扑的过夜验证。
- **为什么**：转正基于本轮 30/30 + 终态快照，但 fleet+回退桶混合拓扑的长时间行为（respawn 风暴、档表外 L、内存泄漏）未观察过；转正前两次 serve 死亡（OOM 风暴/12:16 前的 respawn 风暴）都是运行期暴露的。
- **怎么做**：留观过夜（supervisor.log/chip stdout 的 mtime 监控 + 内存水位），晨间跑一轮 smoke eval（object task0 + spatial t4）确认。发现问题回填运维手册。

**3. 多 checkpoint 泛化** —— 换新 π0.5 权重走完整 v3 校准管线。
- **为什么**：三谱系 10/10 全在同一 checkpoint 上——「引擎通用」还差权重组间一维。
- **怎么做**：管线已全参数化。**卡点：需先拿到第二个 checkpoint**，选此 goal 前先确认 ckpt 到位。

## ④ 性能优化方向清单（2026-10-12 轮二更新）

现状锚点：**gear 舰队 per-call 237-250ms（30/30 复验）；冷启动 serve-min 后 ckpt 段 22s/芯**。转正/复验/serve-min 闭环；剩余杠杆在冷启动残余 + inproc。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略，见 roadmap + 历史战报） | qmd per-token 终点形态；单一因子集三谱系 |
| I3 | 动态 L 分桶 | ✅ **转正完成**（默认根 serve_gear + 30/30 + 回退面 tl151-157） | t4 永久回退依赖已记录 |
| I5 | OM 冷启动 lazy | ◐ serve-min 落地（62→17s 数学段）；剩余 = 骨架零物化 + from_map 并行 + PRELOAD_EARLY 修复 | 判据 = Data 源真值/Const 面占位 |
| I6 | eval 全链 inproc | 前置三件摸清（9.0.1 libs/cp311 build/去 torch_npu）；gear 分支待写 | 省 spool ~15ms/call |
| I7 | 多 checkpoint 泛化 | 管线就绪；**卡点 = 第二 checkpoint** | goal ③ |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-12_gear-promotion-serve-min
