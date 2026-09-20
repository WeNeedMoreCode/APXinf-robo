# Handoff（2026-09-21 凌晨 M3 empty_camera 语义根因 / 压缩用）

## 状态一句话

**314% 真根因 = empty_camera 视图语义（golden 9/10 语义只喂 2 真实视图，empty 走 missing 路径 pad=0：遮蔽 + 位置塌缩；引擎/replay 都当一等公民）——已修 `GEB_PREFIX_DROP_EMPTY=256`（x0 剔除空视图行 968→712，数学等价 theory_check 0.128%）；golden v3 自洽重产（frame0_v3）**。修复后 x0_vis 0.1% / kvk_l0 0.3% / step0_x1 10.1%；**剩余漂移精确定位：层内 {o_proj mm + res + addrms} 跨度 ~2.8% 执行误差（m0 0.52% 输入传播上界仅 0.03%、torch 同链 f16 全程 0.03%——真执行误差非累积序；down/act 只 3.05/3.15% 无罪，gate/up 槽系覆写垃圾）**，逐层复合至 l17 84% → final actions 323%。详见 summary 2026-09-21_m3-empty-camera-mask-root-cause。性能：prefix 115.62ms@712 / flow 7.64ms/步 → **稳态 e2e ≈ 248ms（378 线 0.66×）**。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**empty_camera 根因链**（golden v2 混世界：infer-hook 键 vs 968 全开 replay 键——m0_gold 偏全开 35.31% 偏 causal 94.31% 属第三世界 = pad 遮蔽+位置塌缩；修复 GEB_PREFIX_DROP_EMPTY=256 + golden v3 + t712 OM）；**修复后指标**（x0_vis 0.1/kvk_l0 0.3/kvk_l1 45.2 净图 24.7 dbg 图/step0_x1 10.1/actions 323 复合）；**剩余定位**（MLP 段：slot_cmp712 槽位判读 m0_vis 0.52 → norm2 2.82 → h1(cur) 35.53——图槽判读法 + t712dbg OM + DUMP_MID）；**golden v3 键**（x0_vis/m0_vis/h1_vis/kvk_l* 全 712 语义 + infer 侧原键；golden_gen_v3.py，自洽 0.03-0.12%）；**方法论教训**（golden 与被测须同 forward 语义；先证 golden 自洽再怪引擎——AddRmsNorm/WCONST/mm/槽位复用四嫌疑全被 golden 不自洽假象浪费排除）。丢弃：过程性脚本中间版（八件新脚本在 summary 列全）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（empty_camera 语义已修 + golden v3 自洽，剩余 = 层内 {o_proj mm + res + addrms} 跨度 ~2.8% 执行误差：m0 0.52% 传播上界仅 0.03%、torch 同链 f16 0.03%——见 summary 2026-09-21_m3-empty-camera-mask-root-cause）**。第一动作：**manual attention 链孤立对拍**（真 x0_vis 输入跑 [norm1→qkv→rope→GQA→merge] 最小图，对拍 golden m0_vis——oproj 单算已证 GE mm 逐位干净、addrms 无行缩放无罪 ⇒ 2.82% 产自图内 attention 链真实输出 ≠ m0 槽回读 0.52%，"槽与消费值不一致"再现；通道结构误差指向 headsplit/headmerge 重排或 bmm 累加）；② GEB_OPTEST=arm 的 GE run rc=-3 顺手查。修到 kvk_l1 ≤5% → 全层 → e2e 终态 → LIBERO（9/10）。运行口径：e2e 四件套 + `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712 GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors`；槽位判读 = t712dbg + GEB_DBG_MID/FULL + GEB_E2E_STOP=prefix + GEB_E2E_DUMP_MID=<dir> + slot_cmp712.py（gate/up 槽值不可信）。⚠ 纪律：PYTHONPATH 追加勿覆盖；golden/脚本 syx_docs/dev_logs/ 有镜像；GEB_SAVE 全路径文件名；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_m3-empty-camera-mask-root-cause.txt（M3 真根因：empty_camera 视图语义 + 712 修复 + MLP 段剩余定位）

