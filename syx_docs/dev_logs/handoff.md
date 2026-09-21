# Handoff（2026-09-21 晚 e2e 稳态 bench 310ms = 基线 0.82× / 压缩用）

## 状态一句话

**M3 延迟验收线达成：全口径稳态 e2e ≈310.3ms/调用（vision 66.82 + prefix 140.39 + flow 103.08 P50×10，chip6，t712fix OM，含全部 host glue——36 路 kv 13MB host 中转、37×2 styles h2d/步、x d2h）= torch 基线 376ms 的 0.82×（快 18%）**；styles host 现算 173ms/步 已改一次性预计算缓存（2.06s/进程，10 步调度固定跨调用不变）；vision +10.7ms aux d2h 保守计入（生产可免，真实 ≈300ms/0.80×）。优化潜力（非阻塞）：pk/pv 设备直连 −15~25ms > styles h2d 批量化 −10~15ms > aux 不下载 −10ms → ~265-275ms。**M3 剩余 = LIBERO 对标**（9/10 基线，验收 ≥9/10−1pp；集成工程 = 真 tokenizer〔当前 placeholder ids〕、图像 patch 管线〔当前 golden patches〕、pyo3/服务链接入 harness、actions 反量化）；parity 已定性 fp16-class 不再追（step0 残差 bisect 结案：PK_GOLD/STYLE_GOLD 两腿全洗清 ⇒ flow 段 fp16 vs torch Gemma RMSNorm fp32 上浮的执行语义差，见 summary 2026-09-21_m3-flow-step0-residual-bisect）。本轮 bench 见 summary 2026-09-21_m3-e2e-steady-bench；addrms 修复前情 = summary 2026-09-21_inplace-addrms-fusion-root-cause（融合开关全程携带）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**稳态 bench 数字**（310.3ms = 66.82+140.39+103.08 P50×10 chip6 t712fix = 376ms 基线 0.82×；设备侧 247.7 + glue 62.6；styles 预计算 2.06s/进程一次性）；**口径**（含 host glue 全口径 vs torch model_ms 同层可比；vision aux d2h 10.7ms 保守，生产 ≈300ms）；**优化排序**（pk/pv 直连 −15~25 > styles h2d 批量 −10~15 > aux 免下载 −10 → ~265-275ms）；**工具**（GEB_E2E_BENCH=N 三段稳态循环、GEB_E2E_PK_GOLD/STYLE_GOLD bisect 旋钮、golden v3b = frame0_v3b.safetensors）；**parity 定性**（fp16-class 结案，裁判 LIBERO）。丢弃：bench 循环代码细节、bring-up 期计时。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（稳态 bench 310ms = 基线 0.82× 已达成，见 summary 2026-09-21_m3-e2e-steady-bench）**。第一动作：**LIBERO 对标集成**——把 C 路线三段 OM 链从 probe harness 接进 LIBERO 评测。缺口清单：① 真 tokenizer（当前 placeholder token ids=1000+i*7；LeRobot 用 PaliGemma tokenizer，权重在 paligemma-3b-pt-224）② 图像 patch 化管线（probe 吃 golden patches [768,588]；生产 = 3 视图 SigLIP patchify + 归一化，可 host 侧仿 golden_gen 语义）③ actions 反量化 + 状态离散化进 prompt ④ pyo3 绑定或独立 serving 进程接 apxinf_robo eval-libero harness。建议先搭"离线 LIBERO 轨迹回放"最小闭环（不起 env，用录制的 obs 序列逐帧调引擎对 actions），再上真 env。运行口径：`GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1` + `GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（**烤图/运行都带，OM 用 t712fix**）+ `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712fix GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3b.safetensors GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned GEB_SEG=e2e GEB_E2E_BENCH=N`。⚠ 纪律：PYTHONPATH 追加勿覆盖；GEB_SAVE 全路径文件名；bench 同芯对照（chip6）；⚠ 外层仓 a01fe66 + 子模块 b8dee4d 的 GitHub push 可能仍挂起（下午网络不通，先 `git push` 验证）；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_m3-e2e-steady-bench.txt（M3 稳态 e2e bench：310ms = torch 基线 0.82×，延迟验收线达成；styles 缓存 + GEB_E2E_BENCH 旋钮）


## ① Compact 参数（贴到 /compact 后）

聚焦保留：**bisect 结案**（PK_GOLD 12.4% / STYLE_GOLD 11.8% 全等基线、cond host-vs-golden 0.0004-0.012 fp16 级 ⇒ 残差 = flow 段 fp16 全链 vs torch Gemma RMSNorm fp32 上浮的执行语义差；abs 视角 0.35 < prefix 1.6、actions 360% = 小分母 + 轨迹混沌放大）；**工具**（GEB_E2E_PK_GOLD / GEB_E2E_STYLE_GOLD 旋钮、golden v3b = v3 ∪ cond_s{0..9}[1024]（frame0_v3b.safetensors）、kvv 对拍曲线 1.1→4.8%）；**性能口径**（三段 OM 稳态 247.7ms 纯设备侧 vs torch 基线 376ms 全口径——不可直比，e2e 稳态 bench 是下一动作）；**addrms 修复前情**（融合开关 GEB_INIT_OPT_ge.fusionSwitchFile + t712fix OM 烤图/运行全程携带）。丢弃：golden 重烤的 PYTHONPATH 报错与 no_grad 小修、两腿 run 的逐行 BISECT 输出。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（parity 定位已全部收口，见 summary 2026-09-21_m3-flow-step0-residual-bisect）**。第一动作：**真实 e2e 稳态延迟 bench**——目标 = 全口径单次推理延迟（vision 56.11 + prefix 115.99 + flow 7.57×10 设备侧 247.7ms + host glue：每步 styles host f32 计算 + h2d 换绑、pk/pv host 中转、x0 构建；bring-up 计时 flow 10 步 1.8-2.2s 含对拍非稳态）；对照 = torch_npu 基线 model_ms P50 376.4（**含模型内 host 的全口径**——torch 的 styles/euler 在 forward 内，我们的 host glue 不含在 247.7 里，直比偏乐观）。方法：ge_model_probe 的 GEB_SEG=e2e 加计时口径（去掉 BISECT 对拍/下载）或专门 bench 模式；拿到数字后按 host glue 大头排优化（styles 10 步预计算批处理、pk/pv 设备直连）。然后 **LIBERO 对标**（9/10 基线，验收 ≥9/10−1pp；parity 残差 fp16-class 定性已结，行为裁判在此）。运行口径：`GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1` + `GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（**烤图/运行都带，OM 用 t712fix**）+ `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712fix GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3b.safetensors GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned GEB_SEG=e2e`（v3b = v3 ∪ cond_s*，bisect 旋钮 GEB_E2E_PK_GOLD/GEB_E2E_STYLE_GOLD 备用）。⚠ 纪律：PYTHONPATH 追加勿覆盖；GEB_SAVE 全路径文件名；bench 同芯对照（chip6）；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_m3-flow-step0-residual-bisect.txt（M3 step0 残差 bisect 结案：输入源全洗清 → flow 段 fp16-vs-torch 执行语义差；裁判移交 LIBERO）

