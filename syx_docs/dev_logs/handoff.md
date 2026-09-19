# Handoff（2026-09-19 C2 性能攻坚第一轮收尾 / 压缩用）

## 状态一句话

三轮 msprof 定律：vision OM ~700ms 中 **busy 仅 ~87ms，~600ms 是 81 次/迭代的毫秒级空隙**（`EVENT → ~20ms → MemcopyAsync`）。已排除 PFA host 回调（换手工 attention 仍 700ms）与 unknown-shape 拆分（Const 折叠 OM 221→16MB 仍 700ms；flow 带 unknown 标记却 70.9ms 反例）。**头号嫌疑：111 图输出（LN aux）vs flow 的 1 输出**——GEB_NO_AUX 全深隔离实验进程卡死无结论。顺带修复 eager 参考竞态（d2h 非流序 + 中间量提前释放），**vision 全深对拍 0.1% 稳定，C2 的 104%/30% 漂移销案**。本轮代码/文档已提交。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**性能 profile 定律**（busy 87ms vs 墙钟 700ms；空隙 81 次/迭代 EVENT→~20ms→MemcopyAsync；算子账本：TransData 17-21/Trans 融合 mm 19/LN 14.7/Gelu 9.5/Softmax 6.3/**bmm 1.1ms(20µs/次)**）；**假设排除链**（PFA host 回调 InnerPFA 27 次/迭代但换手工 attention 仍 700；unknown-shape Const 折叠 OM 221→16MB 仍 700；**flow 反例**：2683 unknown 标记 + PFA + Data shape 却 70.9ms）；**未决头号嫌疑：111 图输出**（LN aux ×108，flow 只有 1 输出；GEB_NO_AUX 隔离实验全深卡死——**下轮第一动作 GEB_DEPTH=2 + GEB_ROUNDS=5 GEB_PER=3 + GEB_NO_AUX=1 最小 A/B，1 分钟出数**）；**eager 竞态 bug 取证**（d2h 非流序 + 闭包 drop 内存复用；C2 的 104%/30% 漂移是假的，vision 全深 0.1% 销案）；**新工具面**（GEB_ATTN=manual 手工 attention 0.1% 对拍、headsplit/headmerge、GEB_OPT_/GEB_INIT_OPT_ 选项直通、geb_add_const_i32、GEB_DBG/GEB_NO_AUX/GEB_ROUNDS/GEB_PER）；**坑**（enableSingleStream 无效且数值崩；AttentionScore 310P 无 kernel；SoftmaxV2 half_to_float=true 输出全 0；[768,1152]→[48,256,72] 直接 Reshape 是头/序错排；bmm 输出绑图输出 desc 动态；BiasAdd 在注册表存在未接线）；ascend-msprof skill（最小采集纪律）。丢弃：三轮 profile 逐条分析命令、竞态排查中间过程（结论在 skill #19-25 与 summary）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 C2 性能攻坚第二轮**（第一轮见 roadmap C2 攻坚段与 summary 2026-09-19_c2-perf-attack-round1：busy 87ms vs 墙钟 700ms 的空隙问题，已排除 PFA/unknown-shape）。第一动作：**最小 A/B 裁决 111 图输出假设**——`GEB_SEG=vision GEB_ATTN=manual GEB_DEPTH=2 GEB_ROUNDS=5 GEB_PER=3` 跑 aux 基线，再加 `GEB_NO_AUX=1` 跑对照（数值会坏——trap，只看时间；两轮各 ~1 分钟）。若 no-aux 显著降：给 LN mean/rstd 找图内 sink（或换无 aux 的 LN 形态）消除 108 输出；若不变：转向 prefix 同病对照与 msprof 最小采集（ascend-msprof skill：GEB_ROUNDS=5 采 15 次执行）。目标：vision/prefix 拉回 ~100ms 量级再判 378ms 验收线。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_c2-perf-attack-round1.md（新文件：C2 性能攻坚第一轮——msprof 定律 busy 87ms/墙钟 700ms、PFA 与 unknown-shape 假设排除、eager 竞态修复致 vision 全深 0.1%、手工 attention 落地）
