# Handoff（2026-09-18 收官更新，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**阶段 2 主干已全部贯通**（C executor+runtime / D vla / E 注册 / F bench = M2 完整；真 checkpoint 1.93s 稳态 vs 378ms 基线）；优化待办清单（roadmap 末节 ①-⑤：ada-norm host 读消除 → ACLGraph → launch 批处理）；服务器操作三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律（scratch 池 + 延迟释放，ACLGraph capture 窗口注意）；子模块双仓两步提交。丢弃：C-F 各 bug 排查过程（summary/2026-09-18_c-to-f-stages.md + roadmap 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径**性能优化阶段**（正确性主干已收：`ASCEND_CHECKPOINT_SMOKE_OK` 真 checkpoint 全深度 1600/1600 有限、稳态 1.93s）。第一动作按 roadmap「优化待办」①：消除 ada-norm 的 `host_f16_row` d2h+sync（把 (1+style) scale 行与 shift 行在 styles 预备阶段物化成设备 buffer 传入 `adaptive_rms`，删掉每步 540 次流打断），跑 `ascend_checkpoint_smoke` 对比稳态延迟。之后 ②ACLGraph 捕获（先完成 ① 才可能）③ launch 批处理。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_c-to-f-stages.md
