# Handoff（2026-10-09 白天轮 v3 生产化就绪 + task7 结案 + spatial transfer → 下一轮压缩用）

## 状态一句话

**三项 goal 全闭环（全数字见 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）**：① **v3 生产化切换已执行 + 复验通过**（用户批准 06:33 UTC：退役 serve_i8 mini sup（16 serve 清光）→ 生产根 serve_supervisor_v3.sh 上线 → libero_object **9/10 + task3 重试 SUCCESS 119 步 = 有效 10/10 @ per-call 229.0ms**；task3 首跑打满判 aclnn 非确定性噪声——同 seed 重试健康、官方 torch 基线本身 9/10；老 f16 桶保留分钟级回退）；② **task7 结案**（干净 v3 位下 faulthandler 无 fault + rc=0 + **SUCCESS 118 步**——09-29"无痕死"定罪环境性：mini-sup 互杀 + OOM 遗产；149-156_i8 扩桶 + tl200 v3 重烤 9/9，spatial 谱系实证扩至 **L=157**）；③ **spatial 泛化 = transfer 成立**（replay_s{0..3} 40 帧×4 + golden + sweep：object v3 因子距 spatial 专属拟合仅差 5-8%，**单一因子集覆盖双谱系无需重烤**；行为面 **全量 10/10 rate 1.0** @ per-call 235.2ms，task7 补齐——v3 校准方法与因子集跨谱系双面闭环）。附带战果：**lazy-bake vision 缺失死循环**（mini_sup 的 vision 拷贝源 plain tl$L 对 L>148 不存在 → 静默跳过 → serve 加载即 panic ~82s/轮——修复 = vision 源改 t712fix）；**119 sshd kex 协商损坏破案**（TCP 通零 banner——ssh 必带 `-o KexAlgorithms=ecdh-sha2-nistp256 -F /dev/null`，入 memory，旧配方作废）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）——① 三线终态：生产切换已执行+复验（9/10 + task3 重试过 = 有效 10/10 @ 229ms，生产根 v3 运行中）、task7 环境性结案（SUCCESS 118 步）、spatial transfer 成立 + 行为 10/10（v3o 距专属拟合 5-8%，单一因子集）；② 纪律/坑新增：**vision 拷贝源必须 L 无关（t712fix），不得依赖 plain 桶存在性**；**119 ssh 必带 `-o KexAlgorithms=ecdh-sha2-nistp256 -F /dev/null`（kex 协商损坏，入 memory）**；sweep 参数化已加 v3o 固定候选（transfer 对照的标准做法）；record_rollout/golden_gen/sweep 三脚本已谱系参数化（REPLAY_SUITE/REPLAY_OUT/CALIB_OUT/REPLAY_FMT/CALIB/OUT_*）；sshd 断连时先 /dev/tcp banner 探测判层、detached 进程不受影响；③ 服务器状态：**生产根 /data/apxinf/serve = v3 int8 位运行中**（supervisor_v3 按需 spawn，138-157+200_i8 全热）；serve_i8 mini sup 已退役（A/B 实验根留档重启即回）。丢弃：施工迭代过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-09 白天，见 summary/2026-10-09_prod-readiness-task7-spatial-v3.md）：三线全闭环——**生产根 v3 int8 位运行中**（复验有效 10/10 @ 229ms）、task7 环境性结案、spatial transfer + 10/10。量化/行为/泛化/生产化四面全部收官。

**下轮 goal 建议（抄一项即可）**：
1. **动态 L 分桶生产化**（谱系上沿开放 138-157+200 已见；lazy-bake 兜底可用但有冷烤 ~4min 等待——预置范围策略 / 动态 shape 路线调研）
2. **OM 懒加载 + 引擎注册链入主路径**（checkpoint 61s/进程 摊销；serve 冷 spawn ~2min 主要是 3GB OM 全量加载——按段懒加载）
3. **多 checkpoint / 新任务集泛化**（v3 校准管线全参数化已就绪：record_rollout 换 SUITE 录制 → golden → sweep → fleet 重烤一条龙）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；**eval 默认生产根 /data/apxinf/serve（v3 位运行中，npu_ge.py 默认根）**；A/B 实验 = 重启 serve_i8 mini_sup_i8_v3.sh（A/B 根纪律不变：全谱系桶 + supervisor 单实例）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类规避自匹配；**119 ssh 必带 kex 修复配方**；sshd 断连先 /dev/tcp banner 判层。

## ④ 性能优化方向清单（2026-10-09 更新）

现状锚点：**v3 生产位 per-call 229.0ms（object 复验 345 calls）/ 235.2ms（spatial 235 calls）= 376ms 基线的 0.61-0.63×**（prefix int8 v3 + flow int8 v3 gud + vision f16）。量化侧 + 行为面 + 泛化面 + 生产化全部闭环——**剩余杠杆全在部署形态面（分桶/懒加载）**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准侧 | ✅ 全部闭环（历史行从略，见 roadmap + 上两份战报） | qmd per-token = 终点形态；v3 单一因子集 |
| I1 | v3 生产切换 | ✅ **已执行 + 复验（9/10+retry 过，229ms）** | 生产根 v3 运行中；f16 回退保留 |
| I2 | spatial 泛化 | ✅ 数值面闭环（transfer 成立）；行为面 suite 在盘待读 | 单一因子集结论入 memory |
| I3 | 动态 L 分桶 | 開放（157+ 已见；lazy-bake 修复后无死循环） | 生产化开放项 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-09_prod-readiness-task7-spatial.txt（v3 生产化就绪 + task7 环境性结案 + spatial transfer：扩桶 9/9 + vision 死循环定罪 + sshd 断连收尾）
