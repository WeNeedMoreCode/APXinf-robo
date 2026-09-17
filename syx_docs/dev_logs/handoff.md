# Handoff（2026-09-18 深夜更新，compact 用）

## ① Compact 参数（贴到 /compact 后）

聚焦保留：E 阶段任务（注册链：accelerator Device::Ascend 分派 → load → Pi05AscendVlaRuntime + py 暴露）；服务器操作三件套（ssh、ASCEND_RT_VISIBLE_DEVICES=5、tar 同步后必 touch）；apxinf_rust 9.0.1 容器与 rust_env.sh；子模块双仓两步提交；异步生命期纪律（aclrtFree 不按 stream 排序——scratch 池 + 延迟释放两机制，ACLGraph 接入时注意 capture 窗口内 flush）。丢弃：matmul 战役细节（roadmap + skill 13.4 + summary 已归档）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU Rust 路径 **E 阶段：注册链**（D+F 已完成——`Pi05AscendVlaRuntime` 走 VlaRuntime trait，`ASCEND_RANDOM_BENCH p50=197.5ms` depth 2/2/2 = M2 运行半达成）。第一动作：读 `apxinf-model/src/auto.rs` 与 `accelerator.rs` 的 CUDA 注册链（`load_registered` + `LoadedModel::Vla`），给 `Device::Ascend` 镜像同构注册（synthetic + safetensors 两条加载路径 → StaticBf16Pi05Weights::from_host(ascend) → Pi05AscendRuntime → Pi05AscendVlaRuntime），然后 apxinf-py 暴露。完成后跑全深度 random bench + 真 checkpoint（/data/apxinf/weights/pi05_libero_finetuned）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-18_c-to-f-stages.md
