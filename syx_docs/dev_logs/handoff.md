# Handoff（2026-09-20 M3 起跑完成 / 压缩用）

## 状态一句话

**M3 第一动作完成：真 checkpoint 权重接入三段 OM（GEB_CKPT，子模块 281d703）——{vision,prefix,flow}_real.om 三件套 bench 与合成 r3 打平（55.86/124.61/7.89ms，全模型 ~259ms）= 真权重零延迟代价，GEB_LOAD 验证通过；prefix 真权重漂移 16.8→100%（d2-18，layer0 仍逐位一致、次线性平滑饱和 = outlier 放大 fp16 累加序机制，非 bug）**。M3 剩余：② 三段 OM 接入真实推理链（真嵌入 x0 / 真 style 条件 / pk-pv 直连）→ e2e 延迟 bench；③ LIBERO 对标（9/10 基线）+ prefix 漂移实际影响判定（vs torch_npu golden）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**GEB_CKPT 接入设计**（复用 Pi05Weights::from_safetensors host 解析——LeRobot 前缀归一/[in,out] 转置/Gemma 1+w scale 折叠（g1/g2=ones、折进 q/k/v/gate/up）；probe 侧 t_f16/lw_f16/lb_f16（None bias→zeros）；ada 条件向量 ascl/ash/mscl/msh 与 x0/state/pk/pv 保持合成运行时输入）；**真 OM 结果**（{vision,prefix,flow}_real.om 与 _r3 逐位同字节数=同拓扑；bench 55.86/124.61/7.89ms ≈ r3 打平；GEB_LOAD 全通）；**真权重 parity**（vision 0.1%；prefix d2/4/8/18 = 16.8/59.7/100/100%，layer0 K/V 逐位一致、max_diff 次线性 5.5→36.7 平滑饱和——累加序机制被真 Gemma outlier 放大，e2e 判；flow 37.4% 小分母）；**运行坑**（GEB_LOAD 真 OM 必须配 GEB_CKPT；parity ≥20% 无 GEB_BENCH 静默 exit(1)；checkpoint 加载 61s/进程）。丢弃：16+ 权重位点逐个编辑过程（结论在 summary 2026-09-20_m3-real-weights-into-om + roadmap）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 第二步（真 OM 已就位：{vision,prefix,flow}_real.om 三件套 bench 55.86/124.61/7.89ms，见 summary 2026-09-20_m3-real-weights-into-om）**。第一动作：**三段 OM 接入真实推理链做 e2e**——① prefix x0 = 真嵌入组装（token_embedding 查表（Pi05Weights.vision.token_embedding）+ vision OM 输出过 projector 合流 + state embed，对照 ModelZoo pi05_openpi 的 prefix 组装序）；② flow ada 条件真值 = time_mlp(sinusoidal(t)) → 每层 style 投影（action_layers[i].input_norm/post_attention_norm.style [AW,3AW]）→ ascl=1+s0 / ash=s1（openpi `rms(x)·(1+s0)+s1` 约定，host 变换）；③ pk/pv = prefix OM 的 36 输出直连（18 层 × k/v）；④ 10 步 flow 循环执行换绑定（noise/state 步进，euler 已在图内）。先在 probe 内组装最小 e2e（vision→prefix→flow 链式执行 + 对 torch_npu golden 输出对拍——golden 可用 npu 容器阶段 1 的 translate_parity 工具产出一帧），之后才上 LIBERO（9/10 基线，阶段 1 结论）。注意：OM per-checkpoint；msprof 先缩规模；假设检验最小配置纪律不变。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_m3-real-weights-into-om.md（新文件：M3 起跑——GEB_CKPT 真权重接入三段 OM，_real.om 三件套 bench 打平 r3，prefix 真权重漂移曲线销案）
