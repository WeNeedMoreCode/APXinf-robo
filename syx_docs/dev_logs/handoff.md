# Handoff（2026-09-23 凌晨 M3 收官：全量 eval 10/10 / 压缩用）

## 状态一句话

**M3 达成——全量 LIBERO eval 10/10（success_rate 1.0，超越 torch 基线 9/10）+ 延迟 model_ms P50 325ms = 基线 376ms 的 0.87×**。闭环 0/10 真凶 = **ada-norm gate 通路整体缺失**（openpi `_gated_residual` 的 dense(cond) 第三段 gate 被引擎丢弃，36 处分支输出未门控）+ 残差基错用归一化值——修复在子模块 **ff42d2f**/外层 **e547717**，golden e2e step0_x1 13.8%→0.0%、actions 409%→0.9%，task0 132 步、全量 10 任务 122-163 步全成功。破案靠 replay 动作刑侦（std≈1.00 噪声分布推翻"norm 天花板"误诊）+ 源码对读；完整战报 summary/2026-09-23_ada-gate-missing-root-cause.md。serve 系统已停（芯片回基线；下次起 serve 前清 serve/tl*/ready+pid+shutdown，并核对桶内三件 OM 新鲜度——tl148 曾带 pre-gate 陈旧 flow 被误 spawn）。**M3 剩余为可选后置项**：ascend_executor M2 eager 路径补 gate、NORM32 系重估（n32 桶 flow 旧 + rms32 v2 l17 ssum 饱和 29.5%）、pk/pv 设备直连与 styles 设备化（−25~40ms 潜力）、生产化（动态 L 分桶/引擎注册链接入 apxinf-robo 主路径）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**M3 终局数字**（eval_gateall：10/10、122-163 步、model_ms P50 325.3ms=0.87×、task0 单测 132 步 eval_gatet0b；golden：step0_x1 0.0%/actions 0.9%）；**gate 修复形态**（e2e_style_pair 三元组、每层 l{i}_agate/mgate [1,AW] Data（qkv3 位 16/17）、gatew=TileD dim0+Mul 两处、残差基 xstream 双轨、四处绑定 6-stride b+16/b+17、aops::gate_mul_fp16；torch 语义 = dense(cond) chunk3 + _gated_residual residual+branch·gate 两处 + suffix 全双向）；**刑侦方法论**（动作每维 std≈1.00=噪声分布 ⇒ flow 未收敛数据流形；镜像参考系同 bug 时组件 parity 全绿是假阴性；多源合流的"原理性"结论前先做分布刑侦）；**serve 运维坑**（stale ready/pid 让 client 撞死桶；清桶须连 OM 三件套新鲜度一起查；eval 的 L 漂移 lazy bake 每新桶 ~4-5min 串行）。丢弃：supervisor 僵尸清理细节、预烤引号翻车过程、中间 golden 数字。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU（**M3 已收官：10/10 + 0.87×，见 summary/2026-09-23_ada-gate-missing-root-cause.md 终审节**）。下一动作由用户定方向：① 生产化（动态 L 分桶/懒加载/pk-pv 设备直连 −15-25ms/styles 设备化 −10-15ms、引擎注册链接入 apxinf-robo 主路径、M2 eager 路径补 gate）② NORM32 系重估（n32 桶 flow 旧 + l17 ssum 饱和需 s 更小——若 t712fix 链行为已达标则 n32 或可归档）③ 多任务集/多 checkpoint 泛化验证。⚠ 复现 eval 前置：起 serve 前清 serve/tl*/ready+pid+shutdown + 核对桶内三件 OM 新鲜度；eval 命令 run_ge_eval.sh all <tag>（模型加载 ~4min + L 漂移 lazy bake 每~4-5min/桶，全量 ~25-40min）。⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/kill 用 pgrep+方括号/长命令带 date/验证档位梯/服务器脚本走"本地写 → cat > 远端 → nohup 文件"三步）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_ada-gate-root-cause.md（M3 收官：ada-gate 缺失真凶 + 动作刑侦翻案 + 全量 eval 10/10 + 0.87×）
