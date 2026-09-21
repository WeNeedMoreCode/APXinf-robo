# Handoff（2026-09-22 凌晨 离线回放闭环打通 rel P50=194% / 压缩用）

## 状态一句话

**M3 离线轨迹回放闭环打通（见 summary 2026-09-22_m3-offline-replay-closed-loop）**：真 env（libero_object task0）rollout 40 调用录制（真 PaliGemma tokenizer ids〔state 离散化进 prompt〕/SigLIP patches/捕获 noise/torch normalized_actions）→ **真实 token 长度随 state 位数浮动（144/145）= 静态 OM 新约束**，replay_filter 等长过滤 32 帧（L=144，80% 覆盖）→ tl144 OM 重烤（prefix 103.3ms@656 parity 1.0% / flow 7.62ms/步）→ 引擎三段链逐帧回放：**rel P50=194%（170.6-226.9 紧簇无离群，abs 4-5 on |nact|max≈2.3）= fp16 残差 + 10 步 flow 混沌放大（与 golden 363% 同源，stage-1 已证本 checkpoint 噪声实现敏感但成功率同分布）**；逐帧 ≈307ms 与稳态 bench 310ms 自洽。集成四件已通三件（tokenizer/patch 管线/噪声对齐）。前情：延迟验收线已达成（310.3ms = 0.82×，summary 2026-09-21_m3-e2e-steady-bench）；parity fp16-class 结案（summary 2026-09-21_m3-flow-step0-residual-bisect）。两仓已推平：子模块 e9d9335、外层 a40e784。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**回放闭环结果**（32 帧 L=144 rel P50=194% 紧簇；逐帧 65.7+128+113≈307ms 与 bench 自洽）；**token 长度约束**（真实长度随 state 位数浮动 144/145，torch pad 200 + mask，静态 OM 须等长过滤 + 按长重烤；生产三选 = 分桶 OM/动态 shape/定宽 state 格式化）；**工具链**（record_rollout.py 录制〔REPLAN/REPLAY_MAX_STEPS 可调〕、replay_filter.py 等长过滤、bake_one.sh <seg> <L> <chip>、run_replay.sh；GEB_E2E_REPLAY 旋钮须配 GEB_TOKENS/OM_DIR 对应）；**两大新坑**（torchair fullgraph 编译区挂 forward hooks = per-call 重编译撞 8 上限，四轮排除定罪；`export` 带点 env 名 bash 非法须 env 前缀）；**actions 语义**（normalized_actions = x_t 终态 [:, :7]，无 denorm 环节）。丢弃：三轮 dynamo 排除的中间轮次细节、录制脚本演进过程。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（离线回放闭环已打通，见 summary 2026-09-22_m3-offline-replay-closed-loop）**。第一动作：**闭环 env 对标**——把三段 OM 链包成 policy（pyo3 或独立 serving 进程）接 apxinf_robo eval-libero harness 跑真成功率（9/10 基线，验收 ≥9/10−1pp）。要点：① 变长 token 用分桶 OM 按帧挑桶（tl144 已是第一桶；或先跑单长任务子集）② policy 输入语义全在 record_rollout.py（token pad 200+mask、patches reproduce、noise 捕获）③ actions = x_t[:, :, :7] 直接输出 ④ 运行口径：run_replay.sh 同款 env（GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 + 融合开关〔env 前缀不是 export〕+ GEB_PREFIX_DROP_EMPTY=256 + GEB_CKPT + GEB_OM_DIR=tl144）。⚠ 纪律：PYTHONPATH 追加勿覆盖；GEB_SAVE 全路径文件名；bench 同芯对照（chip6）；torchai 编译区禁 hooks/per-call 换闭包；goal 时限纪律见全局 CLAUDE.md。（行为不达标才做 RMSNorm fp32 对齐；后置优化 pk/pv 直连/styles 设备化/懒加载。）

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-22_m3-offline-replay-closed-loop.txt（M3 离线回放闭环：真 LIBERO 输入 ×32 帧对拍 P50=194%；token 长度约束 + tl144 OM + dynamo hooks 坑）

