# Handoff（2026-09-22 晚 闭环 0/10 定罪 + NORM32 depth12 通 / 压缩用）

## 状态一句话

**M3 闭环 eval 已跑通并出结果：行为 0/10（全 520 步打满）vs 基线 9/10——管线本身零技术故障**（10 任务 × 104 replans、engine 0.315s/次与稳态 bench 自洽、分桶 OM/lazy bake/死桶守护全实战验证，见 summary 2026-09-22_m3-closed-loop-eval）；**根因已因果定罪 = GemmaRMSNorm 的 fp32 方差上浮差**（norm16 对照：torch 单变量去上浮 → task0 同样打满失败；与 step0 残差 bisect 结论闭环）；**NORM32 修复（组合手搓 fp32 RMS 图）已验证到 depth12 编译全通**——全深度 18 层 rc=-8（规模相关，节点数翻倍）放下一轮。推送状态：⚠ **GitHub SSH 断连中**（18:04 起 >2h，凌晨那款 20 分钟自愈，本次未恢复）——本地 commit 齐全：子模块 7df3674（NORM32）+4e4399f（serve）、外层 0dfddcd（收口）+e510fe0（npu-ge 集成），网络恢复后重推。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**闭环结果**（0/10 全打满 vs 9/10；管线零故障：104 replans/任务、0.315s/次、分桶/lazy bake/守护全实战）；**根因定罪链**（norm16 对照 = torch 去 GemmaRMSNorm fp32 方差上浮 → 同崩；194% rel = 同源系统性偏差）；**NORM32 现状**（GEB_NORM32 组合图：Cast→Mul²→ReduceSumD(axes)→RealDiv(w)→Sqrt→1-D TileD→Reshape→Mul(γ)→Cast；GE IR 五坑定罪：dst_type 是 DataType attr/ReduceSumD attr 名 axes/TileD [rows,1] 域推断扁平化/RealDiv 广播拒/**link 只配 Data 名连算子输出必须 wire**；depth12 通、18 层 rc=-8 规模问题）；**serve 架构**（apxinf_npu torch 前处理 + apxinf_rust serve 进程/桶/supervisor 守护，/data 文件轮询；processor 恒 pad 200 须非零前缀截真长）；**运行坑**（pkill -f 自匹配两变种、kill -0 对 zombie 假阳 + fd 持显存、bash 命令替换子 shell 计数器、ASCEND_SLOG_PRINT_TO_STDOUT=1 抓 GE 编译错误是破局工具）；**下一轮**（rc=-8 攻坚：节点精简/拆 OM 接力 → tl144n32 烤桶 → replay rel 降幅判定 → 全桶 eval 复测）。丢弃：rc=-7 排障的中间轮次、深度二分的逐档输出。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（闭环 0/10 已定罪 RMSNorm fp32，NORM32 depth12 通，见 summary 2026-09-22_m3-closed-loop-eval）**。第一动作：**攻 rc=-8**（NORM32 全深度 18 层编译失败、12 层通 = 规模相关）——候选：① 每处 norm 节点精简（1-D Tile+双 Reshape 换 TransData 或 gamma 折进 Cast 常量；12→~7 节点）② GE 编译内存/超时参数（ASCEND_GLOBAL_LOG_LEVEL=0 看 pass、`ge.` init 选项里 memory/parallel 类）③ 按层拆 prefix OM 接力（M2 多图接力已验证）→ 全深度过后：**tl144n32 烤桶（GEB_NORM32=1 全套 env + GEB_SAVE=/data/apxinf/om_cache/tl144n32/）→ serve 起（supervisor 外手动 env：GEB_OM_DIR=tl144n32 + GEB_E2E_SERVE 独立 spool）→ smoke.py 对拍 replay 帧 rel 降幅**——显著降（<100%？）才值得全桶 + eval 复测；降不动则回查 softmax fp32 等剩余 torch 混合点。⚠ 两仓 push 欠着（GitHub 断连），恢复后 `cd apxinf && git push fork ascend-port` + 外层 push。⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/bench 同芯 chip6/pkill 用 pgrep 取 pid/长命令带 date）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-22_m3-closed-loop-eval.txt（M3 闭环 eval：0/10 定罪 RMSNorm fp32 + NORM32 组合图五坑 + serve 系统五坑）
