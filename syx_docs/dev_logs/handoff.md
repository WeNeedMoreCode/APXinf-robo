# Handoff（2026-09-18，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：C 阶段大 matmul 卡点的证据链与三条待试假设（mat2 转置 stride 优先）；服务器操作三件套（ssh 长命令、ASCEND_RT_VISIBLE_DEVICES、PYTHONPATH 追加、tar 同步后必 touch）；apxinf_rust 9.0.1 容器与 rust_env.sh；子模块双仓两步提交纪律。丢弃：NZ 排查过程细节（summary 2026-09-18 已归档）、gelu/rope/cat 战役细节（skill + summary 有）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径 C 阶段序列污染排查：四波实验已归档（转置 b 已是生产路径、崩点=op25 down matmul、K 与 PFA 均无罪），剩余 4 个数据搬运类嫌疑。**第一动作：跑已写好的 `matmul_layout_probe` 的 variant 5（全序列复刻，本地已写好、未同步服务器）——tar 同步 apxinf-ascend 后 `cargo run --example matmul_layout_probe --release`，崩在哪个 seg 打印停在哪段，即锁定污染步。** 读 roadmap「C 阶段核心卡点」节 + summary/2026-09-18_executor-mirror-and-nz-battle.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_executor-mirror-and-nz-battle.md
