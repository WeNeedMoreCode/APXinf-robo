# Handoff（2026-09-23 凌晨 ada-gate 缺失真凶落网 + task0 eval 复测 / 压缩用）

## 状态一句话

**闭环 0/10 的真凶 = ada-norm gate 通路整体缺失（"原理性天花板"是误诊）**：openpi `_gated_residual` 的 dense(cond) 第三段 gate 被引擎显式丢弃（36 处 attention/MLP 分支输出未门控）+ 残差基错用归一化值——修复（子模块 **ff42d2f** / 外层 **e547717**）后 golden e2e **step0_x1 13.8%→0.0%、actions 409%→0.9%**。破案链：replay 动作刑侦（新工具 GEB_REPLAY_DUMP + replay_forensics.py：引擎动作每维 std≈1.00=噪声分布 → 推翻 norm 天花板叙事）→ pk/style_gold/NORM32 全不动的反证 → patched transformers modeling_gemma.py 源码对读（dense(cond)→chunk3=(scale,shift,gate)、hidden=residual+branch·gate；引擎注释自供"第三段引擎未消费"）。t712fix 链（非 NORM32 前缀 + gate flow）全绿；tl{138..147} flow 已重烤 gate 版。**task0 闭环 eval（eval_gatet0）进行中——下一动作 = 读 eval_gatet0_summary.json：成功 → 全量 10 任务；失败 → replay forensics 复跑看分布形态**。⚠ NORM32 系 tl{n}n32 桶 flow 仍旧版且 rms32 v2 有 l17 ssum 饱和回归（29.5%，s=1/32 不够小）——n32 路线后续再修。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**gate 修复内容与验证**（e2e_style_pair→三元组 (scale,shift,gate)、每层 l{i}_agate/mgate [1,AW] Data 输入（块尾追加——qkv3 eager 偏移 8..15 不动，gate 固定位 16/17/默认 12/13）、gatew=TileD dim0 整行复制+Mul 两处分支输出、残差基 xstream（未归一化）与 normed 双轨携带、四处 style 绑定循环 6-stride + b+16/b+17（e2e/bench/replay/serve FlowMech）、aops::gate_mul_fp16（fp16_row_broadcast+aclnnMul）、ascend_executor.rs 残差基同修（⚠ 该 M2 eager 路径 gate 仍缺——后续补）；验证 = t712fix golden step0_x1 0.0%（max_diff 0.00098 f16 量化级）/actions 0.9%/flow eager parity 0.1%）；**torch 语义真身**（patched GemmaRMSNorm：_norm fp32 → ·(1+scale)+shift，gate 直出无激活；GemmaDecoderLayer 两处 _gated_residual residual+branch·gate；suffix 掩码 = att[1,0×49] → cumsum 全等 → 全双向 ✓ 引擎本就对）；**刑侦方法论**（动作分布形态判据：每维 std≈1.00 = 噪声分布 = flow 没收敛到数据流形 vs torch 结构化 0.32-1.40；镜像参考系同 bug 时组件 parity 全绿是假阴性——golden 才是真参考；多源合流指向"原理性"结论前先做分布刑侦，20 分钟翻案）；**eval 现场入口**（supervisor 已起 SERVE_CHIPS="6 4 7 5" /tmp/supervisor_gate.log、tl138-147 全 ready gate 版、eval_gatet0 进行中、成功 → run_ge_eval.sh all gateall）。丢弃：gate 修复前中间 golden 数字、supervisor 僵尸清理细节、预烤两轮引号翻车过程。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（ada-gate 缺失真凶已修复，见 summary/2026-09-23_ada-gate-missing-root-cause.md）**。第一动作：**查 task0 eval 结果** `cat /data/apxinf/serve/eval_gatet0_summary.json`（eval_gatet0 起于 2026-09-23 01:04 CST，约 15-25 分钟出）——成功（<520 步）→ 立即 `docker exec apxinf_npu bash -c "nohup bash /data/apxinf/serve/run_ge_eval.sh all gateall > /data/apxinf/serve/eval_gateall_stdout.log 2>&1 &"` 全量 10 任务（~40-60min，桶已全备）；失败 → `GEB_REPLAY_DUMP=/data/apxinf/replay/dump_gate.bin` 复跑 replay（chip7 tl144）+ forensics（python3 /data/apxinf/replay/replay_forensics.py）看动作分布是否已结构化（std 应≈torch 0.3-1.4 而非 1.0）。⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/kill 用 pgrep+方括号/长命令带 date/验证档位梯从便宜到贵）；⚠ 服务器脚本改动用"本地写文件 → cat > 远端 → nohup 文件"三步，勿在 docker exec 里嵌 heredoc。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_ada-gate-root-cause.md（M3 闭环 0/10 真凶：ada-norm gate 通路缺失 + 残差基错位——动作刑侦翻案 + 修复全绿）
