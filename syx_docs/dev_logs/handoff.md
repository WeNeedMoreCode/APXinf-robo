# Handoff（2026-09-23 凌晨 NORM32 v2 行为否定 + 佐证实验半程 / 压缩用）

## 状态一句话

**M3 NORM32 v2 全链闭环判决为否定 + 佐证实验半程中断**：rc=-8 最终真身 = **aclmdlLoadFromMem 失败**（编译成功装载失败——t200 bake 撞上 serve 占芯；"编译规模上限"从来不存在，skill #37 已修订）；n32v 14-tap 定罪三 bug 后 rms32 v2 = mm 立方体 fp32 累加全 f16 域（单点 0.13%）；**task0 闭环仍 520 打满**（段级偏差守恒 0.13%×37≈0.8% 同修复前 + 行为敏感度 <0.1-1% + mm 累加序分布性源 ⇒ 行为对标疑似原理性天花板）；**用户已选"先做佐证实验再定"**——t200n32 段级 golden 对拍跑到 vision 级（0.3%/0.1% 与基线同）后因 prefix 桶缺失中断（bake rc=-8 未产出文件、脚本不非零退出致 && 链不短路）。两仓已推平（子模块 a052a21 / 外层 0222390）。serve 系统已全停（芯片回基线）。**下一轮第一动作 = 15 分钟补完佐证实验 → A/B/C 决策**（A 接受天花板改口径 / B 近 bit-exact 冲刺 / C 混合形态）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**佐证实验状态与入口**（t200n32 prefix 缺桶：干净芯片重烤 `bash /data/apxinf/replay/bake_one_n32.sh prefix 200 4` → 确认文件存在 → golden 对拍：GEB_SEG=e2e GEB_TOKENS=200 GEB_OM_DIR=tl200n32 GEB_NORM32=1 GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3.safetensors + 四件套 + GEB_PREFIX_DROP_EMPTY=256 + GEB_CKPT + fusion 开关 env，chip6 已清干净；**基线对照**：t712fix prefix worst 0.8%/kvk_l0 0.3%/step0_x1 10.1%；**守恒假说预测 NORM32 后 prefix 仍 ~0.8% 不降，若显著降则 B 路线有戏**）；**rc=-8 真身**（aclmdlLoadFromMem 失败：grep "model built" 有 + "aclmdlLoadFromMem failed" = 编译过装载挂，烤桶前查芯片空闲；bake_one_n32.sh 不非零退出——判桶完整靠 ls 不靠 rc）；**rms32 v2 形态**（xs=x·s→sq→mm(sq,ones)→rsqrt·k→[1,rows]TileD[mult=w,1]→TransposeD→x·invb·γ，全 f16 + cube fp32 累加，Const 折叠；单点 0.13% = GEB_OPTEST=n32v）；**三 bug 定罪**（Sqrt 漏倒数/ReduceSumD f32 假支持 65504 饱和/TileD 连续平铺腐蚀 8%——skill #38/#39）；**行为证据链**（scope 裁决 expert-only 成功 57 calls vs language 崩 104；NORM32 task0 仍打满；replay rel 193.6% 不降）；**天花板三证据**（段级守恒/敏感度阈值/分布性源）。丢弃：n32v 中间 tap 逐轮输出、预烤引号翻车细节、golden 两次失败的中途日志。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（NORM32 v2 行为否定 + 佐证实验半程，见 summary/2026-09-22_m3-norm32-matmul-route.md 追记 2）**。第一动作：**补完佐证实验**（15 分钟）：`bash /data/apxinf/replay/bake_one_n32.sh prefix 200 4`（chip4 空闲）→ `ls /data/apxinf/om_cache/tl200n32/prefix_real.om` 确认 → golden 对拍（env 见 handoff ①，跑前 `npu-smi info` 确认 chip6 空闲）→ prefix 级 rel vs 基线 0.8% 判读：**不降 = 守恒假说实锤 → 提交用户 A/B/C 决策（A 接受天花板/B AscendC 近 bit-exact/C 混合形态）；显著降 = B 路线值得做**。⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/bench 同芯 chip6/kill 用 pgrep+方括号/长命令带 date/验证档位梯从便宜到贵且算总时长含 bake/烤桶前查芯）。⚠ bake 脚本 rc 不可信（内部失败仍 exit 0）——判成功靠 ls 产物 + grep "OM saved"。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-23_m3-norm32-verdict.md（M3 NORM32 v2：三 bug 定罪 + mm 立方体累加 + 行为否定 + rc=-8 真身 + 佐证实验半程）
