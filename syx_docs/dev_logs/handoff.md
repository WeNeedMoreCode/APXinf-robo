# Handoff（2026-09-21 上午 GE 图内 AddRmsNorm 污染定罪 / 压缩用）

## 状态一句话

**M3 剩余漂移（kvk_l1 45.2%）已定罪：GE 静态 OM 图内 AddRmsNorm 读"在图中间量"时数值被污染（内存计划重叠嫌疑）——同值作 Data 输入 0.073% 干净（wmm4 决定性实验），去 addrms 0.036% 干净（L1=mm），五类屏障/端口变体逐位不变，小图 [mm→addrms] 干净（wmm5），图形状强敏感（net 45.2/dbg 24.7/垫M 24.66/MIN 11.0/RES_GOLDEN 78.6）**。attention 链/gate 宽 N mm/down 大 K mm/MLP 尾组合/权重折叠/GQA 簇/rope/M 对齐/auto-bind/dual-role 全部洗清；最小脏图 ~13 算子（`GEB_OPTEST=attn GEB_ATTN_MIN=1` = 11.041%）。生产影响面 = prefix 每层 2 处 [add→addrms]×18 + flow（1.6% 同病小 shape）→ kvk_l17 84%/actions 323%。详见 summary 2026-09-21_ge-addrms-ingraph-corruption。性能不变：e2e ≈248ms（0.66×）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**定罪签名**（[在图中间量→AddRmsNorm] 11-13% 脏 vs 同值 Data 输入 0.073% 净 vs 去 addrms 0.036% 净；行剖面平坦、通道结构扁平 4×、逐位确定性）；**16 步洗冤链**（attention 0.229/oproj 消费 0.089/MLP 尾组合 0.032/折叠 0.032/gate 宽N 0.057/down 大K 0.017/wmm5 小图 addrms 0.058——组合矩阵见 summary 表格）；**内存重叠收敛证据**（五变体逐位相同 max_diff=1.08594 + 大 buffer 尺寸变化即变值 + `ge.bufferOptimize` 选项已在 libge_compiler.so 确认待试）；**复现/裁决旋钮**（GEB_OPTEST=attn 全家 + wmm~wmm5 + GEB_ATTN_* 变体 + dump 落 /data/apxinf/{attnmin,wmm}/）；**坑**（图输出按模型 introspection 分配：绑 addrms y 触发 rstd/x_out 自动补绑 → n_out 不匹配 rc=-3——arm 模式 rc=-3 同根因已结案）。丢弃：各中间 dump 与一次性 sed 变体脚本。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（剩余漂移已定罪 GE 图内 AddRmsNorm 读在图中间量被污染，见 summary 2026-09-21_ge-addrms-ingraph-corruption）**。第一动作：**`GEB_OPT_ge.bufferOptimize=off` 跑 MIN 复现图**（`GEB_OPTEST=attn GEB_WCONST=1 GEB_ATTN_MIN=1 GEB_CKPT=... GEB_E2E_GOLDEN=frame0_v3`，判 kvk1 是否从 11.041% 转净——选项已确认存在于 libge_compiler.so，env 名带点要 `env "GEB_OPT_...=..."` 包引号）；无效则 ② libge strings 扫全部 ge.* 内存选项逐一 A/B ③ ReduceSum/Rsqrt 分解 norm 绕开 AddRmsNorm（先验 310P GE 注册表）④ 显式 TransData ⑤ MLP 大 buffer 布局扰动二分重叠对。〔历史：上轮第一动作 manual attention 链孤立对拍已做——**attention 链 0.229% 无罪**〕（真 x0_vis 输入跑 [norm1→qkv→rope→GQA→merge] 最小图，对拍 golden m0_vis——oproj 单算已证 GE mm 逐位干净、addrms 无行缩放无罪 ⇒ 2.82% 产自图内 attention 链真实输出 ≠ m0 槽回读 0.52%，"槽与消费值不一致"再现；通道结构误差指向 headsplit/headmerge 重排或 bmm 累加）；② arm 的 rc=-3 已结案（addrms y 绑图输出触发 rstd/x_out 自动补绑 → 输出数不匹配）。修到 attn 图 kvk1 ≤0.1% → 生产 prefix/flow 全 [add→addrms] 处应用修复 → kvk_l1 ≤5% → 全层 → e2e 终态 → LIBERO（9/10）。运行口径：e2e 四件套 + `GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/t712 GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors`；槽位判读 = t712dbg + GEB_DBG_MID/FULL + GEB_E2E_STOP=prefix + GEB_E2E_DUMP_MID=<dir> + slot_cmp712.py（gate/up 槽值不可信）。⚠ 纪律：PYTHONPATH 追加勿覆盖；golden/脚本 syx_docs/dev_logs/ 有镜像；GEB_SAVE 全路径文件名；goal 时限纪律见全局 CLAUDE.md。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-21_ge-addrms-ingraph-corruption.txt（M3 剩余漂移定罪：GE 图内 AddRmsNorm 在图中间量污染 + 16 步洗冤 + 内存重叠收敛）

