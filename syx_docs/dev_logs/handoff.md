# Handoff（2026-09-17，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：libero_object 成功率差距的现状与二分计划；图像归一化 bug 的教训（uint8→/255）；服务器/容器操作三件套（ssh 长命令、ASCEND_RT_VISIBLE_DEVICES、PYTHONPATH 追加）；syx_docs 文档位置。丢弃：全部排查过程细节（已归档 summary）、诊断脚本内容、历次实验日志数字（summary 有）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf-robo 昇腾 NPU 适配：阶段 0/1 已完成（引擎缝、375ms 基线、CLI/websocket/noise 全通、归一化 bug 已修、有成功集）。当前唯一未结：libero_object 成功率我们 0/10 vs 官方同日 9/10（输入 0.0 差、单帧推理 ulp 级等价）。下一步：把 NpuTorchPi05Policy 接进官方 LiberoEnv 跑二分（成→差异在 env 胶水层逐项移植；败→trace 官方 eval 每步调用）。先读 syx_docs/plans/npu-port-roadmap.md 与 syx_docs/dev_logs/summary/2026-09-17_libero-object-success-hunt.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-17_npu-port-phase1-and-normalization-bug.md
