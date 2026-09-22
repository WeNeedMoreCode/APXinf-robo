# M3 闭环 0/10 真凶：ada-norm gate 通路整体缺失（+残差基错位）

日期：2026-09-23 凌晨（接 summary/2026-09-22_m3-norm32-matmul-route.md 追记 2）

## 一句话

**"原理性天花板"是误诊——flow expert 的 36 处 attention/MLP 分支输出从未乘过 gate**（openpi `_gated_residual` 语义的 dense(cond) 第三段被引擎显式丢弃），叠加残差基错用归一化值。修复后 golden e2e：step0_x1 13.8%→**0.0%**（f16 量化级）、actions 409%→**0.9%**。

## 破案链（方法论主线：先刑侦后理论）

1. **补完佐证实验**（t200n32 prefix 重烤 → golden）：kvk_l0-16 = 0.7-1.5%（守恒假说方向成立），但 **kvk_l17 跳 29.5%**（NORM32 v2 自己的回归——mm 输出 f16 ssum 在 Gemma l17 大 outlier 行饱和 65504，s=1/32 不够小）。⇒ eval 链应走 t712fix（非 NORM32）前缀。
2. **replay 动作刑侦**（新工具 `GEB_REPLAY_DUMP` + `replay_forensics.py`）：引擎动作**每维 std ≈ 1.00**（噪声分布！torch 动作是结构化 0.32-1.40）、corr≈0.05、各维大 bias——**flow 输出停在噪声尺度，去噪没收敛到数据流形**。这不是"0.8% 级精度漂移"能造出来的形态——上轮"norm 天花板"叙事被推翻。
3. **反证收窄**：pk_gold/style_gold/NORM32 全不动 step0 → 误差源在 flow 内部且与 norm 语义无关；torch 换噪声（动作 100% 不同）仍 8/10 → 行为问题 ≠ "偏离 torch 轨迹"，是策略系统性坏掉。
4. **源码对读定罪**（patched transformers modeling_gemma.py）：
   - `GemmaRMSNorm.forward(x, cond)` 返回 `(normed, GATE)`：`modulation = dense(cond) → chunk3 = (scale, shift, gate)`；`normed·(1+scale)+shift`、gate 直出（无激活）
   - `GemmaDecoderLayer`：`hidden = residual + branch × gate`（**_gated_residual**，两处）
   - **引擎 `e2e_style_pair` 只取前两段，注释自己写着"第三段 [2w:3w] 引擎未消费"**；残差基也错（用 ada 输出而非未归一化 x——CUDA bf16_executor 传的是 input，两个 ascend 镜像都传了 normed）
5. **旁证**：suffix 掩码假设排除（`make_att_2d_masks`：att=[1,0×49] → cumsum 全等 → suffix 全双向 ✓ 引擎对）；embed_suffix = action_in_proj 直出无 time 相加 ✓。

## 为什么所有 parity 都是绿的

GE 图 vs eager 镜像**同 bug**（eager 闭包同样丢 gate + 错残差基）——组件级对拍全绿是假阴性。golden（torch 真链）只接到了段边界（step0_x1/actions），段内从未逐层对拍。**教训：镜像参考系与真参考系共享实现时，对拍只能证一致、不能证正确。**

## 修复（commit ff42d2f，子模块；外层 e547717）

- `e2e_style_pair` → 三元组 (scale, shift, gate)；style_cache 每层 6 段
- 每层新 Data 输入 `l{i}_agate/mgate [1,AW]`（块尾追加——qkv3 eager 偏移 8..15 不动，gate 固定位 16/17、默认 12/13）
- `gatew`：TileD dim0 整行复制（#39 干净方向）+ Mul，attention/MLP 两处分支输出 ×gate 进残差
- 残差基 = xstream（未归一化）与 normed 双轨携带（torch 语义；CUDA runtime 本就 hidden/attention_normalized 双流）
- 四处 style 绑定循环（e2e/bench/replay/serve FlowMech）6-stride + b+16/b+17
- `aops::gate_mul_fp16`（fp16_row_broadcast + aclnnMul）供 eager 镜像
- `ascend_executor.rs:921` 残差基 &normalized → input_b（同款 bug；⚠ 该 M2 eager 路径 gate 仍缺——后续补）
- `GEB_REPLAY_DUMP` 动作刑侦钩子

## 验证（t712fix 链 = 非 NORM32 前缀 + gate 版 flow）

| tap | 修复前 | 修复后 |
|---|---|---|
| flow eager parity | 1.6% | 0.1% |
| step0_x1 | 13.8% | **0.0%**（max_diff 0.00098） |
| actions（golden v3） | 409% | **0.9%** |
| kvk_l0 / x0_vis / kvk_l17 | 0.3% / 0.1% / 3.8% | 不变（prefix 侧） |

## 中途的弯路（记录避免重蹈）

1. **残差单独修（无 gate）方向对但指标反而微变差**（10.1→13.8%）：残差项只贡献 ±3%，gate 项 ~10% 级——单变量修复在多源误差下会"修对了更糟"，判读需配源码对读。
2. **天花板三证据全部有替代解释**：段级守恒（gate 项守恒——它是与 norm 语义无关的常量偏差）、行为敏感度（norm16 patch 恰好也破坏 gate 通路？不——norm16 只动 _norm；但引擎 10% 级 gate 偏差 >> 一切）、replay 饱和（噪声化输出下 rel 无分辨力）。**多源合流指向"原理性"结论前，先做一个分布形态刑侦**（成本 20 分钟，本轮它直接翻案）。
3. 时间感知漂移 2 小时（心算外推 vs date 实测）——CLAUDE.md 纪律"任何一次 date 都能直接算剩余"是有原因的。

## 终审：全量 eval 10/10（2026-09-23 02:17 CST）

**`LIBERO [libero_object] complete: 10/10 successes`（eval_gateall，success_rate 1.0）**——超越 torch 基线 9/10（基线挂 task7；我们 task7 125 步成功；单 trial 差异在采样随机性内）。逐任务步数 122-163 全部健康：

| task | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| steps | 161 | 127 | 122 | 163 | 137 | 129 | 162 | 125 | 155 | 127 |
| 成功 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**M3 双口径达成**：行为 10/10 ≥ 基线 9/10 − 1pp ✓；延迟 model_ms P50 = 325.3ms = 基线 376ms 的 **0.87×**（eval 口径含 serve spool 轮询；纯引擎稳态 bench 310.3ms = 0.82×）。

## 服务器现场（本轮收尾时）

- tl{138..145,147} + tl200n32/t712fix 的 flow 均已重烤为 gate 版（prebake_gate.sh 9 桶并行；tl146/tl148 陈旧 flow 已删走 lazy bake 重烤）
- supervisor 与全部桶引擎已停（stop_serve_gate.sh，芯片回基线 1.3-1.6GB）；⚠ 旧会话残留的 stale ready/pid 文件会让 client 撞死桶挂起（tl143/tl148 两次卡死根因）——**下次起 serve 前先清 serve/tl*/ready+pid+shutdown 只留活桶**；另 tl148 曾带着 pre-gate 陈旧 flow OM 被误 spawn（清理时只删了标记没查 OM——**清桶要连 OM 一起查三件套新鲜度**）
- NORM32 系：tl{n}n32 桶的 flow 仍是旧版（缺 gate）——n32 路线后续要用需重烤 + 修 ssum 饱和（l17 29.5% 回归）
