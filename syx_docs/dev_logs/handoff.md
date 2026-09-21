# Handoff（2026-09-21 下午 flow step0 残差 bisect 结案 / 压缩用）

## 状态一句话

**M3 parity 定位全部收口：step0_x1 11.8% 的三个候选输入源两腿正交替入全洗清**——PK_GOLD（pk/pv←golden kvk/kvv）12.4% 不动、STYLE_GOLD（cond←golden cond_s{step}）11.8% 与基线全等且 host-vs-golden cond 差仅 0.0004-0.012（fp16 量化级，语义正确）⇒ **残差 = flow 段执行语义：我们 fp16 全链 vs torch 混合精度（Gemma RMSNorm fp32 上浮）**；绝对量视角 step0 abs 0.35 < prefix l17 abs 1.6（rel% 是小分母假象），actions 360% = 小分母 + 10 步轨迹混沌放大（noise 敏感同源）。**裁判 = LIBERO（≥9/10−1pp），不再追 parity**。工具沉淀：GEB_E2E_PK_GOLD / GEB_E2E_STYLE_GOLD 旋钮 + golden v3b（frame0_v3b.safetensors = v3 ∪ cond_s{0..9}[1024]）。**M3 剩余 = ① 真实 e2e 稳态延迟 bench（host glue 是大头：styles 每步 host 算+h2d、pk/pv 中转；torch 基线 376ms 是含模型内 host 的全口径，我们 247.7ms 只是设备侧）② LIBERO 对标 ③（不达标才做）RMSNorm fp32 上浮对齐**。前情：addrms 融合污染已修复（summary 2026-09-21_inplace-addrms-fusion-root-cause，t712fix OM + 融合开关全程携带）；本轮见 summary 2026-09-21_m3-flow-step0-residual-bisect。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**bisect 结案**（PK_GOLD 12.4% / STYLE_GOLD 11.8% 全等基线、cond host-vs-golden 0.0004-0.012 fp16 级 ⇒ 残差 = flow 段 fp16 全链 vs torch Gemma RMSNorm fp32 上浮的执行语义差；abs 视角 0.35 < prefix 1.6、actions 360% = 小分母 + 轨迹混沌放大）；**工具**（GEB_E2E_PK_GOLD / GEB_E2E_STYLE_GOLD 旋钮、golden v3b = v3 ∪ cond_s{0..9}[1024]（frame0_v3b.safetensors）、kvv 对拍曲线 1.1→4.8%）；**性能口径**（三段 OM 稳态 247.7ms 纯设备侧 vs torch 基线 376ms 全口径——不可直比，e2e 稳态 bench 是下一动作）；**addrms 修复前情**（融合开关 GEB_INIT_OPT_ge.fusionSwitchFile + t712fix OM 烤图/运行全程携带）。丢弃：golden 重烤的 PYTHONPATH 报错与 no_grad 小修、两腿 run 的逐行 BISECT 输出。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（parity 定位已全部收口，见 summary 2026-09-21_m3-flow-step0-residual-bisect）**。第一动作：**真实 e2e 稳态延迟 bench**——目标 = 全口径单次推理延迟（vision 56.11 + prefix 115.99 + flow 7.57×10 设备侧 247.7ms + host glue：每步 styles host f32 计算 + h2d 换绑、pk/pv host 中转、x0 构建；bring-up 计时 flow 10 步 1.8-2.2s 含对拍非稳态）；对照 = torch_npu 基线 model_ms P50 376.4（**含模型内 host 的全口径**——torch 的 styles/euler 在 forward 内，我们的 host glue 不含在 247.7 里，直比偏乐观）。方法：ge_model_probe 的 GEB_SEG=e2e 加计时口径（去掉 BISECT 对拍/下载）或专门 bench 模式；拿到数字后按 host glue 大头排优化（styles 10 步预计算批处理、pk/pv 设备直连）。然后 **LIBERO 对标**（9/10 基线，验收 ≥9/10−1pp；parity 残差 fp16-class 定性已结，行为裁判在此）。运行口径：`GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1` + `GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（**烤图/运行都带，OM 用 t712fix**）+ `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712fix GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3b.safetensors GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned GEB_SEG=e2e`（v3b = v3 ∪ cond_s*，bisect 旋钮 GEB_E2E_PK_GOLD/GEB_E2E_STYLE_GOLD 备用）。⚠ 纪律：PYTHONPATH 追加勿覆盖；GEB_SAVE 全路径文件名；bench 同芯对照（chip6）；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_m3-flow-step0-residual-bisect.txt（M3 step0 残差 bisect 结案：输入源全洗清 → flow 段 fp16-vs-torch 执行语义差；裁判移交 LIBERO）

