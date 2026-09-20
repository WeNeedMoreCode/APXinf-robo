# Handoff（2026-09-20 M3 第二步 e2e 接线完成 / 压缩用）

## 状态一句话

**M3 第二步完成：三段真权重 OM 接入真实推理链（GEB_SEG=e2e，子模块 c8ca41b+d960a9b）——x0 真嵌入组装（vision_out ‖ token 查表×√2048）、styles 真值（time_mlp→style→1+s0 每步换绑）、pk/pv = prefix 36 输出直连、10 步 flow 循环 + LeRobot 语义对齐（euler c1=1.0），chip6 bring-up 全通（GE_E2E_PROBE_OK）**。M3 剩余：golden 对拍（npu 容器产一帧）→ 真实 e2e 延迟 bench → LIBERO 对标（9/10 基线）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**e2e 接线口径**（x0 = cat(vision_out, token_embedding[ids]×√2048)，视觉前语言后；styles：t=1-step/N → sinusoidal(t,1024,4e-3,4.0) → silu 两层 time_mlp[32] → 每层 style [32,3AW] → ascl=1+s0/ash=s1（executor L714 切分）；pk/pv host 中转；**euler 已换绑 c1=1.0/c2=-0.1（LeRobot x'=x+dt·v 式，binds 尾两位 Data 输入）**；state 确证无通路（pi05 LeRobot 跳过 state_proj，suffix=50 纯 action）；视图数 768 确证（缺失相机=-1 pad 图+mask=0 占位））；**e2e 结果**（bring-up 全通、vision OM 主输出 idx0（108 LN aux 必须绑 trap #17）；各段一次性墙钟 10/77/9.5s 非稳态）；**运行口径**（四件套+GEB_CKPT+GEB_OM_DIR 读 *_real.om；GEB_E2E_GOLDEN 键：patches[768,588]/token_ids/noise[50,32]/actions f32）；**golden 待裁决**（suffix att_masks [1]+[0]*49 语义、prefix 漂移实际影响、patch 行序实证）。丢弃：编辑过程（结论在 summary 2026-09-20_m3-e2e-chain-wiring + roadmap）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 对拍偏差定位（首帧 golden 对拍已执行：max_diff=3.32/314%——链路全通量级正常但系统偏差，见 summary 2026-09-20_m3-e2e-chain-wiring；t200 OM 三件套 + golden 已就位）**。第一动作：**段边界 bisect 钉第一分岔点**——golden_gen.py 扩 dump：vision_tower 输出（post-projector 前的 vision 输出过 projector 后的 768×2048）、embed_prefix 输出 x0（968×2048）、prefix 首层 k/v、flow step0 输出 x1，同帧重跑存 frame0_full.safetensors；probe e2e 各段后加 GEB_TRACE 式对拍打印（vision_out/x0/kv0/step0 vs golden 逐段 max_diff）——第一分岔段即凶手。已知候选排序：① suffix att_masks `[1]+[0]*49`（modeling_pi05 L752——action tokens 只有第 1 个可被 prefix 侧看见？make_att_2d_masks 语义要读源码，引擎 cross-attn 是全拼 kv 无此 mask）② prefix 100% 漂移放大（GE vs eager 已知，对 golden 是首次实证）③ patch 行序 (c,kh,kw) ④ time/ada-cond 细节（te 维度 1024 已对齐）。之后：修正→对拍≤5% 量级 → 真实 e2e 延迟 bench → LIBERO 对标（9/10 基线）。⚠ 纪律：不估时间只看 date；PYTHONPATH 追加勿覆盖；golden 脚本在 syx_docs/dev_logs/golden_gen.py。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_m3-e2e-chain-wiring.txt（新导出：M3 第二步——三段 OM 接真实推理链，e2e bring-up 全通 + golden 钩子就位）

