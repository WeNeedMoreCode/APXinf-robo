# Handoff（2026-09-20 C2 收官 / 压缩用）

## 状态一句话

**C2 全部收官：全模型 2182 → 263.3ms（8.3×）= 378ms 验收线 0.70×，比 torch_npu 基线快 31%，C 路线（GE 原生 OM）达标，进 M3**。本轮三战果：① prefix 25.1% 漂移销案（深度曲线平滑次线性 + layer0 k/v 逐位一致 → fp16 大 K 累加序差，probe 侧结案，M3 e2e 判）；② **NZ 权重税根因**（GE 对每个 ND Data mm 权重每执行插设备侧 ND→FRACTAL_NZ TransData，flow 54% 总时长 ≈ 531µs/层；torch_npu TransData 100ms 同源）；③ **GEB_WCONST 权重 Const 入图**（编译期折叠，单算 wgt 实证 −25%/OM 烤入 8.4MB）三段推广：vision 55.89 / prefix 128.44 / flow 7.90ms/步。OM 产物 {vision,prefix,flow}_r3.om（5.2GB，**per-checkpoint**——缓存 key 须含权重版本，ADR-002 已更新）。陷阱 #30 回填 skill。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**NZ 权重税根因与修法**（每执行 ND→FRACTAL_NZ TransData ~63GB/s，[n,k]→[k/16,n/16,16,16] 签名；Const 入图编译期折叠实证 0.3945→0.2945 ms/mm、OM 烤权重 8.4MB；GEB_WCONST 设计 = binds 全量库存 + data_inputs 映射 + ins()，eager 索引两模式恒同，flow depth2 parity 逐位同验证）；**最终数字**（vision 55.89/0.1%、prefix 128.44/25.1%、flow 7.90/步/1.6%、全模型 263.3ms = 0.70× 线，8.3× 累计；OM _r3.om 三件套 5.2GB per-checkpoint，GEB_LOAD 已验证）；**prefix 漂移销案证据**（depth 2/4/8/18 = 6.0/10.9/15.6/25.1% 次线性无跳变 + layer0 k/v 0.00000 + 首块后 5.6% = fp16 大 K down-proj 累加序指纹；WCONST 后 worst 0.237→0.361 同档微移 rel 不变）；**flow 分解**（ms(d)=0.06+0.975d，成本全图内）；**wgt 实验三变体**（nd/cst/nz——nz desc 直入 310P TBE 编译崩，开放项）；GE 自动融合 matmul+add/mul（AutomaticBufferFusionOp）顺带发现；bench ROUNDS=3 panic 修复（skip 吃光轮次）。丢弃：msprof 分析脚本细节、16 个权重位点逐个编辑过程（结论在 summary round3 + skill #30）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 M3 起跑（C2 已收官 263.3ms = 378 线 0.70×，见 summary 2026-09-20_c2-wrapup-nz-weight-tax）**。第一动作：**真 checkpoint 权重接入三段 OM**——ge_model_probe 的合成权重路径（rand_f16/wt()）换成 LeRobot safetensors 真权重加载（host 解析 → bf16→f16 → wt() Const 路径），三段对拍口径升级为"GE OM vs eager aclnn 同真权重"，产出真 checkpoint 的 _real.om。之后 e2e 延迟 bench + LIBERO 对标（9/10 基线，阶段 1 结论）——同时判定 prefix 25.1% 漂移的实际影响。关键注意：① OM per-checkpoint（ADR-002 已更新缓存 key 约定）；② M2 期已有 ascend_vla/bf16_weights 的 host 权重解析管线可复用；③ vision 段 3 视图 + SigLIP 结构对照 ModelZoo 参考实现核对权重名映射。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-20_c2-wrapup-nz-weight-tax.md（新文件：C2 收官——prefix 漂移销案、NZ 权重税根因、GEB_WCONST 三段 263ms = 378 线 0.70×，C 路线达标进 M3）
