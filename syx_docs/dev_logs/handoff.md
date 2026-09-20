# Handoff（2026-09-20 晚 M3 对拍偏差定位 / 压缩用）

## 状态一句话

**M3 314% 漂移已拆解定位：① rope f16-inv_freq 语义差已修（kvk_l0 12.6%→0.4%，t200 OM 重烤，子模块 c7db8c8）；② 引擎语义/权重/attention/MLP 全部教科书级洗清（0.03-0.14%）；③ 剩余偏差钉死在 GE OM 图内数值行为——同一算子链 x0 输入 0.4% vs golden-h1 输入 18.7%（数据依赖、数值级非结构级）**。详见 summary 2026-09-20_m3-parity-drift-bisect（裁决表 + 已排除清单 + 工具链用法）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**bisect 裁决链**（vision 0.3%/x0 0.1%/权重 0.000%/attention+MLP 复刻 0.03-0.14% 全清；rope f16-inv_freq 根因+修复+rope_angle()；剩余=GE OM 数值：h1 输入同链 18.7% vs x0 0.4%，图 k_l1 值随内存计划变 41↔23.7%、中间量输出槽被图内复用覆写 res→norm2 实证）；**golden v2 键**（vision_out/x0/kvk_l{0..17}/m0/h1/step0_x1 + q0i/k0i/v0i；陷阱：paligemma.language_model 直接 .forward() 绕 hook、GemmaModel None mask 会 create_causal_mask）；**probe 新旋钮**（GEB_DEPTH_VISION/PREFIX、GEB_ATTN_PREFIX、GEB_E2E_STOP、GEB_LAYER_OFFSET、GEB_E2E_X0_KEY、GEB_DBG_MID/FULL、GEB_E2E_DUMP_MID、GEB_OUT_PAD）；**分析脚本七件**（l0_bisect/rope_probe/attn_scale_probe/attn_l0_h1/weights_cmp/m0_variants/stage_cmp，服务器 /data/apxinf/ 有同步副本）。丢弃：过程性烤图/跑批命令（模板在 summary 末尾）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 对拍偏差定位（rope 已修、语义全清，剩 GE OM 图内数值级偏差：golden h1 直入同链 18.7% vs x0 0.4%——见 summary 2026-09-20_m3-parity-drift-bisect 裁决表）**。第一动作（按嫌疑序）：① **AddRmsNorm f16 方差/累加在大动态范围输入的精度**——optest 单算子复测（真权重、真 x0/h1 输入，golden h1 已在 frame0.safetensors）；② **WCONST vs Data 权重数值差**——同图关 WCONST 重烤 d2 对比（GEB_WCONST 不设 + 手动喂权重 Data）；③ mm cube 累加精度——GE vs aclnn eager 单算对拍；④ 输出槽复用覆写——需观测节点防复用。修到 kvk 全层 ≤5% → e2e 终态复测 → 延迟 bench → LIBERO（9/10）。⚠ 纪律：不估时间只看 date；PYTHONPATH 追加勿覆盖；golden/分析脚本 syx_docs/dev_logs/ 有镜像；GEB_SAVE 要全路径文件名。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_m3-parity-drift-bisect.txt（M3 偏差定位：bisect 工具链 + rope 根因修复 + GE OM 数值残留）
