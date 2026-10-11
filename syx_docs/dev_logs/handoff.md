# Handoff（2026-10-12 轮动态分档 HYBRID 生产化 → 下一轮压缩用）

## 状态一句话

**三项 goal 收口（全数字见 summary/2026-10-12_dyn-gear-hybrid-production.md）**：① **动态分档 HYBRID 形态上线**（prefix 22 档单 OM + flow per-L 静态池 + 每芯一 serve @ 空芯 0-3；CANN SetInputDynamicDims **四连坑**全取证绕道——纯动态输入集 / payload=全维 vs 选项=纯 -1 值 / 128 维上限 / 单次全维调用；行为面 object 10/10（重试口径）/ spatial 9/10（t4 二连败=唯一硬回归）/ goal 10/10；延迟 237-250ms/call；skill ge-offline-om 已回填）；② **冷启动 OM 三段并行预载落地**（52s→10-22s；ckpt 选择性读与 inproc 未及——施工时间耗在 ① 运行侧四坑）；③ **多 ckpt 卡点确认**（服务器仅一只 π0.5 checkpoint）。生产 v3 桶（4-7 芯）未动，gear 舰队（0-3 芯）并存待转正判决。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-12_dyn-gear-hybrid-production.md）——① HYBRID 拓扑（prefix 22 档 gear OM / flow per-L 池换柄 / 每芯一 serve / GEAR 客户端芯轮询；SetDims 四坑与解法在 skill ge-offline-om 动态分档节；引擎 12 commits 6dd0817..c378fbd 已 push；服务器 serve_gear_supervisor.sh + om_cache/tl_dyn + serve_gear 舰队）；② OM 并行预载（preload_e2e_oms + 线程绑 context）；③ 多 ckpt 卡点（仅一只 checkpoint）。丢弃：四坑的调试迭代过程、eval 监控过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-12，见 summary/2026-10-12_dyn-gear-hybrid-production.md）：动态分档 HYBRID 上线（29/30 行为面，spatial t4 唯一回归）、OM 并行预载落地。v3 生产桶与 gear 舰队并存（0-3 芯），转正判决待做。

**下轮 goal 建议（抄一项即可）**：
1. **gear 转正判决 + t4 回归收口**（spatial t4 per-L 桶专属路由或该档静态 OM 混跑；全谱系复评后切 eval 默认根 serve_gear、v3 桶退役、supervisor 单实例）
2. **冷启动 lazy 剩余**（ckpt 选择性读取 −54s——sm/g Const 化后 serve 权重消费面更小，stub 化收益更大；inproc：apxinf_npu 供 9.0.1 libs + 客户端去 torch_npu，省 spool ~15ms/call）
3. **多 checkpoint 泛化**（管线全参数化就绪：record 换 ckpt → golden → sweep v3o 对照 → transfer 判定 → eval；需先到位第二个 checkpoint）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；**eval 默认生产根 /data/apxinf/serve（v3 位运行中；gear 转正前 serve_gear 为并列实验根）**；A/B 实验 = 重启 serve_i8 mini_sup_i8_v3.sh；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类；**119 ssh 必带 kex 配方；上行断流走 gzip+480B 分块 base64 append（scp 不可用；引擎源码迭代走 git diff 补丁通道）**；docker exec -d 必须脚本文件形态（& 后台随 exec 退出即死）；sshd 断连先 /dev/tcp banner 判层。

## ②b 下轮 goal 注解（是什么/为什么/怎么做——给人读的，不用搬运）

**1. gear 转正判决 + t4 回归收口** —— 决定 HYBRID 拓扑是否替换 per-L 桶成为生产位。
- **为什么**：gear 舰队已 29/30（object/goal 10/10、spatial 9/10），收益是每芯一 serve（消 20 只 idle 进程 + prefix OM 22 份→1 份）与档表内新 L 零冷烤；卡点是 spatial t4 二连败（分支 kernel ~1% 数值漂移的行为放大）与 +5ms/call 派发开销。不收口则两套拓扑长期并存，运维面翻倍。
- **怎么做**：先给 t4 定位 L（eval 客户端打日志或 serve 侧记 L）→ 两策二选一：该 L 走 per-L 静态桶专属路由（客户端按 L 分流，最小改动）/ 该档从 gear 表剔除混跑静态桶 → 全谱系复评 ≥30/30 或明确接受 9/10 → 切 eval 默认根 + v3 桶退役 + supervisor 单实例。验收 = 三谱系行为面 + 延迟对比表落 summary。

**2. 冷启动 lazy 剩余** —— serve 冷启动从 ~2min 压到 ~1min 内，顺带 eval 全链 inproc。
- **为什么**：HYBRID 下冷启动已是每芯一次，但 flow 池 22 只 + ckpt 全量解析 63.7s 仍是主体；inproc 再省 spool 轮询 ~15ms/call（237→~222ms）且架构上消灭 serve 进程面。
- **怎么做**：ckpt 选择性读（GEB_CKPT_LAZY：只读 token_embedding + time_mlp + style 投影，权重走 stub——Const 化后构图不消费权重字节，前提已比上轮更好）；三段+flow 池装载并行化；inproc 的 PyO3 入口就绪，缺 apxinf_npu 容器 9.0.1 libs 供给 + eval 客户端不 import torch_npu。验收 = 冷启动计时 + per-call 延迟 + 行为面 spot check。

**3. 多 checkpoint 泛化** —— 换新 π0.5 权重走完整 v3 校准管线。
- **为什么**：三谱系 10/10 全在同一 checkpoint 上——「引擎通用」还差权重组间一维。
- **怎么做**：管线已全参数化（同 goal ③ 上轮）。**卡点：需先拿到第二个 checkpoint**（不同数据/任务微调的 π0.5），选此 goal 前先确认 ckpt 到位。

## ④ 性能优化方向清单（2026-10-12 更新）

现状锚点：**gear 舰队 per-call 237-250ms（29/30）；生产 v3 229-235ms（30/30）**。量化/行为/泛化闭环；剩余杠杆在部署形态面（转正判决 + lazy + inproc）。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-H | 量化/行为/校准/生产化 | ✅ 全闭环（历史行从略，见 roadmap + 历史战报） | qmd per-token 终点形态；单一因子集三谱系 |
| I3 | 动态 L 分桶 | ✅ **HYBRID 上线**（prefix gear + flow 池）；t4 回归 + 转正判决留下轮 | SetDims 四坑全录 skill |
| I5 | OM 冷启动 lazy | ◐ 并行预载落地（52→10-22s）；ckpt 选择性读 + inproc 留下轮 | HYBRID 下每芯一次 |
| I6 | eval 全链 inproc | 前置就绪（PyO3 + 回落）；缺 9.0.1 libs 供给 + 去 torch_npu | 省 spool ~15ms/call |
| I7 | 多 checkpoint 泛化 | 管线就绪；**卡点 = 第二 checkpoint** | goal ③ |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-12_dyn-gear-hybrid-production
