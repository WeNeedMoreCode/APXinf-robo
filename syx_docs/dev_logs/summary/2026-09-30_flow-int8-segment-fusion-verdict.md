# goal ① flow int8 落地 + 段间融合判决（2026-09-30）

## 终局一行

flow 段 int8 走完全部**数值面**验证梯（对拍 ALL_OK 零翻转 / golden step0_x1 0.1%、actions 9.7-10.0% / serve 稳态 flow 81→**75.6ms**、sum 225.1 = **0.598×**），但**行为面翻车**：task0、task1 连续 520 步打满（Sep 28 同 seed 同协议基线 10/10）——**生产回滚 flow f16**（全桶已回滚 + mini_sup 撤 flow int8 env；回滚位配置 = prefix int8 v2 + flow f16，即 Sep 28 已验收的 10/10 @ 238.9 配置）。A/B 隔离实验受 infra 三连阻（详见行为判决节）未独立终裁，回滚位配置的 task0 复验即合并判决。「段间融合」（10 步单 OM）被 serve 分解**取证否决**——flow 绝对大头 sync=70.6ms 纯设备时间（enq 仅 3.0ms），unroll 收益上界 ~3ms。0.53× 缺口的真正杠杆留档：**qmd 执行面（x_scale 静态化）+ 行为面修复（校准 v3 flow 侧多步因子）**。

## 实现面（子模块 50024cb）

- **引擎**（ascend_ge.rs）：`flow_int8()` + seg_flow 预注册 pass（reg_i8 ×7/层，dump 标签 F{nn}_{proj}）+ mm_or_qmd 建图 + int8 槽 16B dummy bind 占位——**层内 18 槽布局与 f16 恒同**（serve/e2e 的 style 硬编码偏移 b+0/+1/+10/+11/+16/+17 不漂移，FlowMech/style_residency 零改动）；int8 模式跳过 eager/parity（prefix 先例）；probe 补 GEB_QMD_M/K 形状旋钮
- **与 prefix 的关键差异**：action 层 loader **无 Gemma (1+g) fold**（weights.rs 只 take）→ 图内激活天然 torch 域，**s_eff = s_npz 直取、无 g 表**——prefix 的两域回图不适用，转换脚本更简
- **校准管线**（pyo3_check 四脚本）：`golden_gen_v2calib_flow.py`（expert 18 层 ×4 站点 pre-hook，**10 步 euler 全程跨步 per-channel amax 包络**；⚠ pwe.forward 的实例级 torchair 编译须 `del pwe.forward` 绕过——钩子里的 amax 无 fx2ge converter）→ `int8_flow_factors.py`（smooth npz + int8 权重 npz 金标准一并产出）→ `convert_smooth_engine_flow.py`（引擎 safetensors，smooth=1/s 乘法约定）→ `compare_int8_dump_flow.py`
- 因子域：126 矩阵，s ∈ [1.9e-4, 29.1]，smooth=1/s ∈ [0.034, 5322] f16 安全；反量化 rel_rms 中位 1.02%（prefix 谱同量级）

## 验证梯

| 阶 | 结果 |
|---|---|
| 量化对拍 int8_weights_flow_v1.npz | **ALL_OK：126 矩阵零翻转**（action 层无 fold → 引擎与 npz 完全同数学路径，比 prefix 878/24 亿还干净）；q 投影 fscale 比值钉 0.0625 |
| e2e golden（tl200 语义，prefix v2 int8 + flow gud int8） | step0_x1 **0.1%**（prefix int8 v2 的 kvk_l0 是 0.9%——flow 单步更干净）；10 步欧拉累积后 actions **9.7%（全 7）/ 10.0%（gud 子集）** vs prefix-only 10.1%——flow int8 没有放大总漂移 |
| task0（prefix+flow int8，serve_i8 spool） | **FAIL：520 步打满**（226s；Sep 28 同 seed 基线 134 步 success）——行为翻车第一证 |
| task1（同上，套件第 2 任务） | **FAIL：520 步打满**（10min）——连续两任务失败 vs 基线 10/10，flow int8 行为退化先验坐实方向 → **生产回滚** |
| 回滚位配置（prefix int8 v2 + flow f16）task0 复验 | **待跑**——2026-09-30 服务器链路断 ~50min，回滚链（全桶 f16 flow + mini_sup 撤 env + serve 重启）已启动但复验未及执行；恢复后跑 task0 预期回到 134 步 success 形态（若仍打满 = 非 flow int8 因素，升级重查） |

## 行为判决与回滚（本轮最重要结论）

- **数值-行为剪刀差**：golden actions rel 10.0%（vs prefix-only 10.1%）看起来无害，但 flow 侧的 per-step 0.1% 误差经 10 步欧拉轨迹混沌放大后在行为面翻车——**flow 是动作生成的直接路径，其对量化漂移的行为容限远低于 prefix**（prefix 的 k/v 只影响 cross-attn 上下文）。与 M3 时代「actions rel 与行为解耦」教训同源：**行为面只有 LIBERO 有裁判权**
- **A/B 隔离三连受阻**（每阻都取证）：① 手起 serve（docker exec -d bash -c 内联形态）ready 后无声死——换脚本文件形态 watchdog 解决；② 客户端要求 ready 文件**新鲜**（mtime ≥ ensure 时刻）——watchdog touch 保鲜解决；③ **单桶 serve_ab 根过不了 L 漂移**（task0 轨迹漂 138 → 无桶无看门狗 → `_ensure_ready` 干等到 timeout）。结论：**A/B 隔离根必须全谱系桶 + supervisor**，与生产根等价——A/B 即回滚，合并执行
- **回滚执行**：tl138-148+200 全桶 flow OM 换 f16（146-148 的 f16 flow 在 spatial 轮清场时已删，补烤 3 个）+ mini_sup_i8.sh 撤 GEB_FLOW_* env + serve 全体重启。回滚位 = Sep 28 验收配置（10/10 @ 238.9），复验 task0 即闭合
- **flow int8 资产全部保留**：引擎代码（env 开关关死即 f16）、因子四件套（激活 dump/npz/引擎 safetensors/对拍脚本）、tl 桶 int8 OM 的烤制配方（战报存档）——行为面修复后一键重启

## perf 判决链（本轮最大取证产出）

1. **带宽模型预期 ~30ms**：flow 步 M=50 无法摊销权重读，每步全量流式 f16 622MB（≈7.9ms/步 @79GB/s 有效带宽自洽）→ int8 311MB 应省 ~2.5ms/步
2. **实测只 -5.4ms**（serve 口径 81→75.6）：legacy 口径 f16 112.2 / 全 7 int8 108.6 / **gud 子集 106.75**
3. **单算 probe 定罪**（GEB_QMD_M=50 五 shape，qmd vs f16 mm 同 shape）：全部 50-100µs 打平（down 快 20µs）——qmd 无 pathology，但 L2 热域单算测不到冷流差异
4. **结论**：**qmd per-op 的 per-token quant 执行开销**（M=50 算不满，126 op/步 × ~30µs 量级）对冲了带宽减半。q/k/v/o 的 qmd 净零（全 7 vs gud 差 1.9ms）→ 生产收窄 gud 子集
5. **段间融合否决**：serve 分解 `[ft] kv=0.50 h2d=0.37 enq=3.03 sync=70.57 dl=0.21`——**sync（纯设备 10 步）70.6ms 是绝对大头**，enq+host 间隙仅 3.4ms；10 步单 OM 只能收 ~3ms，需 seg_flow+FlowMech 大改 + 10× 图编译时长，不值当

## 运维事件（全取证）

- **GEB_INT8_PROJS 共享踩坑**：子集实验把 prefix 段一起切掉 → OM 输入数 189≠260 rc=-2 → 新增 `GEB_FLOW_PROJS` 独立 env（缺省回落共享值）
- **L 漂移冷桶撞 timeout**：task0 首跑 L 漂到 138（object 谱系下沿，此前无 tl138_i8 桶）→ 冷烤 prefix 3min + spawn → `timeout 1500` 差 1 分钟被杀（py-spy 定位主线程在 _ensure_ready 无进展 + ps 得 99% CPU 忙等）；桶热后重跑通过。**教训入 memory**：批量前核谱系桶全烤好 + timeout ≥1800
- **tl140 OM 双写竞态复验**：mini_sup respawn 的 tl140 烤与手动重烤循环同桶并发——干净重烤一次销案
- sshd 全天闪烁（共享机负载/连接限流）——重试退避模式作业，不影响 detached 进程

## 遗留与下一步

- **0.53×（200ms）缺口 ~25ms 的诚实分解**：flow 设备 70.6ms（qmd 执行面是主体）+ vision 57.9（int8 小账 ~2.5ms）+ prefix 86-87（已 int8）。**唯一够大的杠杆 = qmd x_scale 静态化**（per-token → 静态校准 scale，砍 quant 流水；IR 面未探明，310P 该 op 的 x_scale/x_offset 输入编译行为留档）→ 若成，flow 或到 ~50ms、sum ~200 达标；若不成，0.53× 需重新谈判（结构下限证据链已齐）
- vision int8：SigLIP 权重流 ~400MB→200MB 省 ~2.5ms，LayerNorm+bias 全有实现面大——收益/成本比差，后置
- probe_fi8 目录残留 flow_gud/flow_all7/flow_real 三份实验 OM（服务器 /data/apxinf/om_cache/probe_fi8/）
- PyO3 inproc int8 open 挂（AclError -2）仍未动（非生产路径）
