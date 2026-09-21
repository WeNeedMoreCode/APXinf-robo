# Handoff（2026-09-21 下午 InplaceAddRmsNorm 融合根因终结 + 修复落地 / 压缩用）

## 状态一句话

**M3 addrms 污染已终结：根因 = `InplaceAddRmsNormFusionPass` 把 AddRmsNorm 融合成原地算子 `InplaceAddRmsNorm`（310P/910b 注册表同构：outputs 名就叫 x1/x2——结果写回输入 buffer 本体），别名与静态内存计划在读在图中间量时污染；Data 输入因用户 buffer 全程受保护而免疫**（与上轮 16 步证据全兼容）。修复 = **init 级 `ge.fusionSwitchFile` 关该 pass**（JSON 在 /data/apxinf/fusion_off_inplace.json，镜像 syx_docs/dev_logs/fusion_off_inplace.json）。修复效果：MIN 图 11.041→0.159%、全量 attn 图 45.224→0.159%、e2e **kvk_l1 45.2→0.4% / kvk_l17 84→3.8%**（0.3→1.4→3.8% 教科书 fp16 累积曲线）；prefix 段 worst 100%+→0.8% 且 124.61→**115.99ms（快 7%）**、flow 37.4→4.4% 且 7.89→7.57ms、vision 不变——**零代价净赚**。生产缓存 = /data/apxinf/om_cache/t712fix（**烤图/运行必须全程带融合开关**，融合状态烤在 OM 里，旧 t712 不携带修复）。残余（与 addrms 无关）：step0_x1 11.8% / actions ~360%（小分母；noise 同源已证——probe 从 golden 载 `noise` 键起步）——候选 host styles 计算（段内对拍抵消盲区）> prefix 主路 hidden 残差 > flow 段 4.4%。详见 summary 2026-09-21_inplace-addrms-fusion-root-cause。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**根因与修复**（InplaceAddRmsNormFusionPass 原地别名污染 + `ge.fusionSwitchFile` init 级关闭 + t712fix OM 缓存 + 全部修复前后数字 kvk_l1 45.2→0.4/kvk_l17 84→3.8/prefix 0.8%/flow 4.4%/prefix 反快 7%）；**取证工具**（`DUMP_GE_GRAPH=3 DUMP_GRAPH_PATH=<dir>` 逐 pass 图 dump = 发现融合的破局点；GE 开源仓 `D:\compass\ge` 选项归属索引：`ge.*` 名 init 级 / atc 短名 build 级、bufferOptimize 合法值 `off_optimize` 非 off；disableReuseMemory=1 与 bufferOptimize=off_optimize 均无效的实验）；**e2e 残余**（kvk 链已净成 0.3→3.8% 平滑 fp16 曲线；step0_x1 11.8%/actions ~360% 独立残差——noise 同源已证、styles 盲区假说）；**运行口径**（四件套 + GEB_INIT_OPT_ge.fusionSwitchFile + GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712fix GEB_E2E_GOLDEN=frame0_v3 GEB_CKPT）。丢弃：选项 rc=-7/-1 试错过程、dump 文件清单。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（addrms 污染已修复，见 summary 2026-09-21_inplace-addrms-fusion-root-cause）**。第一动作：**flow step0 残差 bisect**——step0_x1 11.8% 与 addrms 无关（修复前后同量级），noise 同源已证（probe 从 golden 载 `noise` 键起步）；候选排序：① **host 侧 styles 计算**（sinusoidal→time_mlp→style 在 probe host f32 算——flow 段 4.4% parity 是 vs eager 同 host glue，styles 偏差段内抵消、只在 vs golden 显形）② prefix 主路 hidden 残差（kvk_l17 3.8% 类）喂 flow cross-attn ③ flow 段自身 4.4%。方法：golden 的 styles/pk-pv/x1 渐进替入定位最大贡献者（GEB_E2E_X0_KEY 系旋钮 + GEB_E2E_GOLDEN 键）。修完 → 真实 e2e 稳态延迟 bench（现有计时含 OM 加载/host glue 非稳态）→ LIBERO 对标（9/10 基线）。运行口径：`GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1` + `GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json`（**烤图/运行都带，OM 用 t712fix**）+ `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712fix GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned GEB_SEG=e2e`。⚠ 纪律：PYTHONPATH 追加勿覆盖；GEB_SAVE 全路径文件名；bench 同芯对照；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_inplace-addrms-fusion-root-cause.txt（M3 addrms 污染根因终结：InplaceAddRmsNorm 融合原地别名 + fusionSwitchFile 修复 + e2e kvk 全净）

