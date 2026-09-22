# Handoff（2026-09-22 深夜 NORM32 v2 落地 + 行为否定 + 天花板假说 / 压缩用）

## 状态一句话

**M3 NORM32 全链闭环完成且判决为否定**：rc=-8 销案（伪编译上限——实为旧代码 eager panic + 服务器代码滞后，depth18 编译+落盘全通）；n32v 14-tap 数值矩阵定罪三 bug（Sqrt 漏倒数/ReduceSumD f32 假支持/TileD 连续平铺腐蚀）后 rms32 v2 = **mm 立方体 fp32 累加全 f16 域**（单点 0.13%）；tl144n32 烤桶 + supervisor_n32 全谱系 lazy bake 实战；**task0 闭环判决：仍 520 打满——NORM32 不修复行为**。三层证据（段级偏差守恒 0.13%×37≈0.8% 同修复前 / 行为敏感度 <0.1-1%（norm16 对照+replan=1）/ mm 累加序等分布性源主导 replay 194% 不降）⇒ **"闭环行为对标 torch"疑似原理性天花板**。两仓已推平（子模块 a052a21 / 外层 18d84a9）。**下一步 = 用户决策**（A 接受天花板改口径 / B 近 bit-exact 冲刺 / C 混合形态，见 summary 2026-09-22_m3-norm32-matmul-route 追记节）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**本轮判决链**（rc=-8=伪编译上限：ASCEND_SLOG_PRINT_TO_STDOUT 取证 OM built 成功+Rust panic；服务器代码滞后教训——先 md5 对比再信二进制；三 bug：Sqrt 漏倒数→Rsqrt、ReduceSumD/ReduceSum f32 假支持（FE 混精度回退 f16 累加 65504 饱和）→mm cube fp32 累加替代、TileD 连续平铺（rank-1 与 [1,n] flat 同错 8%）→dim0 复制+TransposeD 桥）；**rms32 v2 形态**（xs=x·s(s=1/32)→sq→mm(sq,ones)→rsqrt·k(k=s·√w)→[1,rows]TileD[mult=w,1]→TransposeD→x·invb·γ；全 f16 kernel；Const 折叠无 Data 输入）；**GEB_OPTEST=n32v**（14-tap 数值矩阵+argmax 定位，须 GEB_NORM32=1）；**行为证据**（scope 裁决：expert-only patch task0 成功 57 calls/language patch 崩 104——行为开关在 language 侧；NORM32 引擎 task0 仍 104 打满；replay rel 193.6% 不降）；**天花板假说三证据**（段级偏差守恒/敏感度阈值/分布性源）；**工具链**（bake_one_n32.sh、supervisor_n32.sh、tl{n}n32 桶×9）；**skill #35 修正/#37-39**。丢弃：n32v 中间 tap 轮次的逐次输出、预烤命令引号翻车细节（教训已入 memory）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3（NORM32 v2 已落地且行为判决为否定，见 summary/2026-09-22_m3-norm32-matmul-route.md）**。第一动作：**等用户对 M3 出路的三选决策**（A 接受天花板：行为口径改误差量化+敏感性分析，延迟 0.82× 已达标；B 近 bit-exact 冲刺：AscendC fused fp32 RMS（skill AscendC-ops-dev 的 ada-norm fused kernel 基建已在）+ 逐源压缩；C 混合形态：敏感段留 torch_npu+引擎接管大 matmul）——决策前不自行开工大项。可选低成本佐证实验（决策谈话的弹药）：t200n32 桶 + GEB_E2E_GOLDEN 段级对拍（验证"段级偏差守恒"预测的 ~0.8% 不降）。⚠ 纪律照旧（PYTHONPATH 追加/GEB_SAVE 全路径/bench 同芯 chip6/kill 用 pgrep+方括号技巧/长命令带 date/验证档位梯从便宜到贵且算总时长含 bake 等待）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-22_m3-norm32-matmul-route.txt（M3 NORM32 v2：rc=-8 销案 + 三 bug 定罪 + mm 立方体累加 + 行为否定 + 天花板假说）
