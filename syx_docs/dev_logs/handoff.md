# Handoff（2026-10-09 白天轮 v3 生产化就绪 + task7 结案 + spatial transfer → 下一轮压缩用）

## 状态一句话

**三项 goal 全推进至终态（全数字见 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）**：① **v3 生产化切换 = 就绪待批**（生产根已清理、serve_supervisor_v3.sh + eval_prod_v3_all.sh 预置、全谱系 v3 桶热 138-157+200；启动被权限层拦 = 用户决策项，一条命令即切，老 f16 桶原样保留可分钟级回退）；② **task7 结案**（干净 v3 位下 faulthandler 无 fault + rc=0 + **SUCCESS 118 步**——09-29"无痕死"定罪环境性：mini-sup 互杀 + OOM 遗产；149-156_i8 扩桶 + tl200 v3 重烤 9/9，spatial 谱系实证扩至 **L=157**）；③ **spatial 泛化 = transfer 成立**（replay_s{0..3} 40 帧×4 + golden + sweep：object v3 因子距 spatial 专属拟合仅差 5-8%，**单一因子集覆盖双谱系无需重烤**；行为面 suite 因 **sshd 断连 ~1.5h** 收尾时未读终局——task0/1/7 已核实 SUCCESS，task2-9 结果在盘：`cat /data/apxinf/serve_i8/eval_spv3_all_summary.json`）。附带 infra 定罪：**lazy-bake vision 缺失死循环**（mini_sup 的 vision 拷贝源 plain tl$L 对 L>148 不存在 → 静默跳过 → serve 加载即 panic ~82s/轮——修复 = vision 源改 t712fix）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）——① 三线终态：生产切换就绪待批（启动命令 + 复验脚本名）、task7 环境性结案（SUCCESS 118 步）、spatial transfer 成立（v3o 距专属拟合 5-8%，单一因子集）；② 纪律/坑新增：**vision 拷贝源必须 L 无关（t712fix），不得依赖 plain 桶存在性**；sweep 参数化已加 v3o 固定候选（transfer 对照的标准做法）；record_rollout/golden_gen/sweep 三脚本已谱系参数化（REPLAY_SUITE/REPLAY_OUT/CALIB_OUT/REPLAY_FMT/CALIB/OUT_*）；sshd 断连时服务器 detached 进程不受影响、结果在盘（7f69acf 先例）；③ 服务器状态：serve_i8 v3 supervisor（修复版）+ 138-157/200_i8 全热；生产根清理就绪；**生产切换启动待用户批准**（用户问过"有啥损耗"——答：零损耗纯升级 + 分钟级回退，等其拍板）。丢弃：施工迭代过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-09 白天，见 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）：三线终态——生产切换就绪待批（一条命令）、task7 环境性结案 SUCCESS、spatial transfer 成立（单一因子集）；spatial suite 终局数字在盘未读（sshd 断连收尾）。**下轮首动作：读 eval_spv3_all_summary.json 定 spatial 行为面验收，然后按用户决策执行生产切换**。

**下轮 goal 建议（抄一项即可）**：
1. **生产切换执行 + 双谱系复验**（用户已知情零损耗；一条命令 docker exec -d apxinf_rust bash /data/apxinf/serve/serve_supervisor_v3.sh + eval_prod_v3_all.sh + spatial suite 数字补录）
2. **spatial 数字补录**（若切换暂缓：读 eval_spv3_all_summary.json + 战报补表即可闭环 goal ③）
3. 动态 L 分桶（spatial 上沿开放至 157+，lazy-bake 兜底已修复但有冷烤等待——分桶策略生产化）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；eval 用隔离根 serve_i8 + mini_sup_i8_v3.sh（vision 修复版）；**生产根切换后 serve_i8 mini sup 退役腾芯**；A/B 隔离 = 等价生产根；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类规避自匹配；**sshd 闪烁/断连时先 ping 判层、detached 进程不受影响**。

## ④ 性能优化方向清单（2026-10-09 更新）

现状锚点：**v3 位 per-call ≈232ms（object 谱系）= 376ms 基线的 0.62×**（prefix int8 v3 + flow int8 v3 gud + vision f16）；spatial 口径 task7 实测 model_ms 239.3。量化侧 + 行为面 + 泛化面全部闭环——**剩余杠杆全在生产化/部署形态面**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准侧 | ✅ 全部闭环（历史行从略，见 roadmap + 上两份战报） | qmd per-token = 终点形态；v3 单一因子集 |
| I1 | v3 生产切换 | **就绪待批**（脚本/桶/复验全预置） | 零损耗升级 + 分钟级回退 |
| I2 | spatial 泛化 | ✅ 数值面闭环（transfer 成立）；行为面 suite 在盘待读 | 单一因子集结论入 memory |
| I3 | 动态 L 分桶 | 開放（157+ 已见；lazy-bake 修复后无死循环） | 生产化开放项 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-09_prod-readiness-task7-spatial.txt（v3 生产化就绪 + task7 环境性结案 + spatial transfer：扩桶 9/9 + vision 死循环定罪 + sshd 断连收尾）
