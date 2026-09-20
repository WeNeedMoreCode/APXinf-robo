# Handoff（2026-09-20 M3 第二步 e2e 接线完成 / 压缩用）

## 状态一句话

**M3 第二步完成：三段真权重 OM 接入真实推理链（GEB_SEG=e2e，子模块 c8ca41b+d960a9b）——x0 真嵌入组装（vision_out ‖ token 查表×√2048）、styles 真值（time_mlp→style→1+s0 每步换绑）、pk/pv = prefix 36 输出直连、10 步 flow 循环 + LeRobot 语义对齐（euler c1=1.0），chip6 bring-up 全通（GE_E2E_PROBE_OK）**。M3 剩余：golden 对拍（npu 容器产一帧）→ 真实 e2e 延迟 bench → LIBERO 对标（9/10 基线）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**e2e 接线口径**（x0 = cat(vision_out, token_embedding[ids]×√2048)，视觉前语言后；styles：t=1-step/N → sinusoidal(t,1024,4e-3,4.0) → silu 两层 time_mlp[32] → 每层 style [32,3AW] → ascl=1+s0/ash=s1（executor L714 切分）；pk/pv host 中转；**euler 已换绑 c1=1.0/c2=-0.1（LeRobot x'=x+dt·v 式，binds 尾两位 Data 输入）**；state 确证无通路（pi05 LeRobot 跳过 state_proj，suffix=50 纯 action）；视图数 768 确证（缺失相机=-1 pad 图+mask=0 占位））；**e2e 结果**（bring-up 全通、vision OM 主输出 idx0（108 LN aux 必须绑 trap #17）；各段一次性墙钟 10/77/9.5s 非稳态）；**运行口径**（四件套+GEB_CKPT+GEB_OM_DIR 读 *_real.om；GEB_E2E_GOLDEN 键：patches[768,588]/token_ids/noise[50,32]/actions f32）；**golden 待裁决**（suffix att_masks [1]+[0]*49 语义、prefix 漂移实际影响、patch 行序实证）。丢弃：编辑过程（结论在 summary 2026-09-20_m3-e2e-chain-wiring + roadmap）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 收尾（e2e 链已通 + 语义对齐 + golden 一帧已产出：/data/apxinf/golden/frame0.safetensors，见 summary 2026-09-20_m3-e2e-chain-wiring）**。第一动作：**解 token 对齐死结 → 对拍**——golden 侦察实锤 input_ids=200（tokenizer pad 到 max，真实 prefix=968 且非 16 倍数；actions 是 (50,7) 切片）。三步：① rust 容器试 `GEB_SEG=prefix GEB_TOKENS=200 GEB_DEPTH=2`（四件套+GEB_CKPT，最小深度）看 GE 静态 OM 是否接受 M=968 非 16 倍（eager aclnn 会崩，GE 未必）——能编则 golden 脚本改任务文本填满 200 全真 token（消 pad——引擎无 mask，pad token 不能进）重产 golden，再 `GEB_TOKENS=200 GEB_SAVE` 重烤 prefix/flow OM 后 `GEB_E2E_GOLDEN=... GEB_SEG=e2e` 对拍（probe 侧比较须取前 7 列 vs golden actions (50,7)——需要小改 golden 比较段）；② 编不过则备选：host pad x0 到 976（图仍按 976 建，末 8 行用任意重复 token——但 torch 侧锁 200 不可行 → 改走"引擎 M-padding 规则泛化"路线论证；③ 对拍通过后：真实 e2e 延迟 bench → LIBERO 对标（9/10 基线）。同帧还裁决：suffix att_masks [1]+[0]*49、prefix 100% 漂移实际影响、patch 行序。⚠ 时间纪律：不估时间只看 date；PYTHONPATH 追加勿覆盖（golden 脚本已踩）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_m3-e2e-chain-wiring.txt（新导出：M3 第二步——三段 OM 接真实推理链，e2e bring-up 全通 + golden 钩子就位）

