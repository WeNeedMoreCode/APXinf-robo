# Handoff（2026-10-12 轮动态分档 HYBRID 生产化 → 下一轮压缩用）

## 状态一句话

**三项 goal 收口（全数字见 summary/2026-10-12_dyn-gear-hybrid-production.md）**：① **动态分档 HYBRID 上线且行为面 30/30**——prefix **26 档单 OM**（133-157+200；L=136 档表外崩 serve 的根因修复）+ flow per-L 静态池 26 只 + 每芯一 serve @ 空芯 0-3（supervisor 错峰 spawn）；object 10/10 / spatial 10/10（t4 走 152-156 静态回退路由）/ goal 10/10（t9 内部重试）；延迟 237-250ms/call；CANN SetDims **四连坑**全取证入 skill。② OM 并行预载 52→10-22s；ckpt stub 实测定不可行（61.4s 在 from_map 数学，真杠杆 = from_map 并行化）；inproc 未做。③ 卡点确认：仅一只 π0.5 checkpoint。**转正判决留下轮**（30/30 已达标，宜再跑一轮全量确认稳定性后切 eval 默认根）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-12_dyn-gear-hybrid-production.md）——① HYBRID 拓扑（prefix 22 档 gear OM / flow per-L 池换柄 / 每芯一 serve / GEAR 客户端芯轮询；SetDims 四坑与解法在 skill ge-offline-om 动态分档节；引擎 12 commits 6dd0817..c378fbd 已 push；服务器 serve_gear_supervisor.sh + om_cache/tl_dyn + serve_gear 舰队）；② OM 并行预载（preload_e2e_oms + 线程绑 context）；③ 多 ckpt 卡点（仅一只 checkpoint）。丢弃：四坑的调试迭代过程、eval 监控过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-12，见 summary/2026-10-12_dyn-gear-hybrid-production.md）：动态分档 HYBRID 上线（29/30 行为面，spatial t4 唯一回归）、OM 并行预载落地。v3 生产桶与 gear 舰队并存（0-3 芯），转正判决待做。

**下轮 goal 建议（抄一项即可）**：
1. **gear 转正判决**（再跑一轮三谱系全量确认 26 档舰队 + 回退路由稳定性 → 切 eval 默认根 serve_gear、v3 桶退役范围判定[152-156 回退桶保留]、supervisor 单实例）
2. **冷启动 lazy 剩余**（ckpt 选择性读取 −54s——sm/g Const 化后 serve 权重消费面更小，stub 化收益更大；inproc：apxinf_npu 供 9.0.1 libs + 客户端去 torch_npu，省 spool ~15ms/call）
3. **多 checkpoint 泛化**（管线全参数化就绪：record 换 ckpt → golden → sweep v3o 对照 → transfer 判定 → eval；需先到位第二个 checkpoint）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；**eval 默认生产根 /data/apxinf/serve（v3 位运行中；gear 转正前 serve_gear 为并列实验根）**；A/B 实验 = 重启 serve_i8 mini_sup_i8_v3.sh；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（scp 不可用；引擎源码迭代走 git diff 补丁通道）**；docker exec -d 必须脚本文件形态（& 后台随 exec 退出即死）；sshd 断连先 /dev/tcp banner 判层。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. gear 转正判决** —— 决定 HYBRID 拓扑是否替换 per-L 桶成为生产位。
- **为什么**：gear 舰队已达 30/30（t4 走 152-156 静态回退路由、goal t9 内部重试；L=136 档表外崩 serve 根因已修——26 档表重烤 + flow 池补 4 只 + 错峰 spawn + 串行池装载），收益是每芯一 serve（消 20 只 idle 进程 + prefix OM 22 份→1 份）与档表内新 L 零冷烤。不转正则两套拓扑长期并存，运维面翻倍。
- **怎么做**：再跑一轮三谱系全量（26 档舰队 + 回退路由的稳定性确认——晚间偶发 serve 崩的根因 L 档表外已修，需复验）→ 切 eval 默认根 serve_gear + npu_ge.py 默认值改 + v3 桶退役范围判定（152-156 回退桶保留）+ supervisor 单实例纪律。验收 = 三谱系行为面 + 延迟对比表落 summary。

**2. 冷启动 lazy 剩余** —— serve 冷启动再压缩 + eval 全链 inproc。
- **为什么**：HYBRID 下冷启动已是每芯一次，但 ckpt 全量解析 61.4s（from_map 数学，实测 stub 化不可行）+ flow 池 26 只装载 27.4s 仍是主体；inproc 再省 spool 轮询 ~15ms/call 且架构上消灭 serve 进程面。
- **怎么做**：from_map 并行化（rayon 分层——812 张量单线程是瓶颈的唯一真解）；GEB_PRELOAD_EARLY 的 context 激活修复已入（e9e7301）待验；inproc 的 PyO3 入口就绪，缺 apxinf_npu 容器 9.0.1 libs 供给 + eval 客户端不 import torch_npu。验收 = 冷启动计时 + per-call 延迟 + 行为面 spot check。

**3. 多 checkpoint 泛化** —— 换新 π0.5 权重走完整 v3 校准管线。
- **为什么**：三谱系 10/10 全在同一 checkpoint 上——「引擎通用」还差权重组间一维。
- **怎么做**：管线已全参数化（同 goal ③ 上轮）。**卡点：需先拿到第二个 checkpoint**（不同数据/任务微调的 π0.5），选此 goal 前先确认 ckpt 到位。

## ④ 性能优化方向清单（2026-10-12 更新）

现状锚点：**gear 舰队 per-call 237-250ms（29/30）；生产 v3 229-235ms（30/30）**。量化/行为/泛化闭环；剩余杠杆在部署形态面（转正判决 + lazy + inproc）。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略，见 roadmap + 历史战报） | qmd per-token 终点形态；单一因子集三谱系 |
| I3 | 动态 L 分桶 | ✅ **HYBRID 30/30**（26 档表 133-157+200 + flow 池 26 只；spatial t4 走静态回退路由）；转正判决留下轮 | SetDims 四坑 + L 漂移全录 skill/战报 |
| I5 | OM 冷启动 lazy | ◐ 并行预载落地（52→10-22s）；ckpt stub 实测定不可行（61.4s 在 from_map 数学）、inproc 未做 | 真杠杆 = from_map 并行化 |
| I6 | eval 全链 inproc | 前置就绪（PyO3 + 回落）；缺 9.0.1 libs 供给 + 去 torch_npu | 省 spool ~15ms/call |
| I7 | 多 checkpoint 泛化 | 管线就绪；**卡点 = 第二 checkpoint** | goal ③ |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-12_dyn-gear-hybrid-production
