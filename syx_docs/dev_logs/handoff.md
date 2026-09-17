# Handoff（2026-09-18，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：C 阶段大 matmul 卡点的证据链与三条待试假设（mat2 转置 stride 优先）；服务器操作三件套（ssh 长命令、ASCEND_RT_VISIBLE_DEVICES、PYTHONPATH 追加、tar 同步后必 touch）；apxinf_rust 9.0.1 容器与 rust_env.sh；子模块双仓两步提交纪律。丢弃：NZ 排查过程细节（summary 2026-09-18 已归档）、gelu/rope/cat 战役细节（skill + summary 有）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径 C 阶段：executor 镜像（B）已完成且真权重冒烟跑通前 3 算子，当前卡点是大矩阵 matmul（aclnnMatmul ND 路径 MTE 越界、WeightNz 310P 不支持）。第一动作：按 roadmap「C 阶段核心卡点」节的三条假设排查——先试 mat2 转置 stride（shape [N,K] + stride [1,K] 同一块内存），再开日志跑 torch_npu 同 shape matmul 拿 kernel ground truth。读 syx_docs/plans/npu-port-roadmap.md 卡点节 + summary/2026-09-18_executor-mirror-and-nz-battle.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_executor-mirror-and-nz-battle.md
