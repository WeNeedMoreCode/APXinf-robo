# Handoff（2026-09-18 收官更新，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**阶段 2 主干已全部贯通**（C executor+runtime / D vla / E 注册 / F bench = M2 完整；真 checkpoint 1.93s 稳态 vs 378ms 基线）；优化待办清单（roadmap 末节 ①-⑤：ada-norm host 读消除 → ACLGraph → launch 批处理）；服务器操作三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；异步生命期纪律（scratch 池 + 延迟释放，ACLGraph capture 窗口注意）；子模块双仓两步提交。丢弃：C-F 各 bug 排查过程（summary/2026-09-18_c-to-f-stages.md + roadmap 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径 ACLGraph 捕获收尾（正确性主干全收；arena/三段式已落地：捕获窗口已干净穿过 vision/embed/prefix/action 层到 denoise step 0 的 euler 区，见子模块 54ceb77）。第一动作：跑 `ascend_graph_capture_smoke`（ASCEND_RT_VISIBLE_DEVICES=5，2GB arena 已设）——当前唯一残留是窗口内 aclnn 内部 h2d（107030），出现在 action_out matmul mark 与 euler mark 之间；取证法：给 `euler_update_fp16` 的 4 个子算子（muls/add/muls/add）逐个加 mark 二分，并检查 aclnnMuls/aclScalar 在捕获模式下的生命周期语义（aclnn 内部 memcpy 是当前最大嫌疑）。捕获跑通后接 replay 对拍（smoke 已写好 max_diff<0.05 断言），再接 checkpoint smoke 稳态对比量化收益。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_c-to-f-stages.md
