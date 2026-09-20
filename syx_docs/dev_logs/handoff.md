# Handoff（2026-09-20 M3 第二步 e2e 接线完成 / 压缩用）

## 状态一句话

**M3 第二步完成：三段真权重 OM 接入真实推理链（GEB_SEG=e2e，子模块 c8ca41b）——x0 真嵌入组装（vision_out ‖ token 查表）、styles 真值（time_mlp→style→1+s0 每步换绑）、pk/pv = prefix 36 输出直连、10 步 flow 循环，chip6 bring-up 全通（GE_E2E_PROBE_OK，|x|max 89.9→34.6 单调收敛）**。M3 剩余：golden 对拍（npu 容器产一帧）→ 真实 e2e 延迟 bench → LIBERO 对标（9/10 基线）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**e2e 接线口径**（x0 = cat(vision_out, token_embedding[ids])，视觉前语言后、state 不进 prefix（π0.5 走离散化进 prompt 文本 pi05_prompt）；styles：t=1-step/N → sinusoidal(t,1024,4e-3,4.0) → silu 两层 time_mlp[32] → 每层 style [32,3AW] → ascl=1+s0/ash=s1（executor L714 切分 [0:w]/[w:2w]，第三段未消费）；pk/pv host 中转 ~30MB；euler 图内 x'=0.9x-0.1v）；**e2e 结果**（bring-up 全通、|x|max 单调衰减、vision OM 主输出在 idx0——108 LN aux 必须绑 trap #17；各段一次性墙钟 10/77/9.5s 非稳态）；**运行口径**（须配四件套+GEB_CKPT+GEB_OM_DIR 默认 om_cache 读 *_real.om；GEB_E2E_GOLDEN safetensors 钩子键：patches[768,588]/token_ids/noise[50,32]/actions，f32）；**⚠ 语义开放矛盾**（引擎 VT=768 三视图 vs stage-1 mask 修复后官方链疑似 2 视图、euler c1=0.9 约定 vs math.rs x-=v/10、prompt token 数须 16 倍数——golden 见分晓）。丢弃：编辑过程（结论在 summary 2026-09-20_m3-e2e-chain-wiring + roadmap）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 收尾（e2e 链已通：GEB_SEG=e2e GE_E2E_PROBE_OK，见 summary 2026-09-20_m3-e2e-chain-wiring）**。第一动作：**产 golden 一帧并对拍**——npu 容器（apxinf_npu）写脚本：stage-1 机器（NpuTorchPi05Policy / build_robot_policy(engine="npu-torch")）加载 pi05_libero_finetuned，取一帧（可复用 translate_parity_zero_npu.py 的帧构造），`noise=` 精确注入固定噪声（阶段 1 已有工具语义），dump safetensors：patches[768,588]（pixel_values 归一化后 unfold 14×14，行 (c,kh,kw) 序、patch 序 view-major）/token_ids（须 pad 到 16 倍数——任务文本加填充词）/noise[50,32]/actions[50,32]，落到 /data/apxinf/golden/frame0.safetensors；然后 `GEB_E2E_GOLDEN=... GEB_SEG=e2e ...` 对拍。**同帧裁决三件事**：prefix 100% 漂移实际影响、视图数（768 vs 512——若 2 视图需 GEB_VT 参数化重建 OM）、euler 语义（c1=0.9 引擎约定 vs torch 积分式）。之后：真实 e2e 延迟 bench（host 中转/61s 加载工程化）→ LIBERO 对标（9/10 基线）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_m3-e2e-chain-wiring.txt（新导出：M3 第二步——三段 OM 接真实推理链，e2e bring-up 全通 + golden 钩子就位）

