# 2026-10-15 op 级热点普查（最小 msprof 采集）

目的：int8+gear 转正后从未做过 op 级重测（最后一次全量在 WCONST 263ms 时代）——把「推断无热点」升级为「实测无热点」。

方法（ascend-msprof skill 最小化纪律）：`GEB_E2E_BENCH=12`（13 次执行 ≈ 2.4 万 task 行）× chip4 直调（生产 env 同款，空芯）× msprof `--application` wrapper；产物 278MB，全流程 ~7 分钟，用毕已删。工具：`probe_dyn/prof_hotspot_1015.sh` + `prof_bench_inner.sh`（push 后需 chmod +x）。

## 结果（÷13 次执行，每迭代 ms / 占设备总时间比）

| op | ms/iter | % | 说明 |
|---|---|---|---|
| **QuantMatmulDequant** | 85.2 | 37% | prefix 7 投影×18 层 + flow 3×18×10 步（int8 主力，~717 次/iter） |
| **AutomaticBufferFusionOp** | 31.7 | 14% | GE buffer-fusion pass 生成的元素融合算子（~962 次/iter）——680 时代 Add 78+Mul 14 的现形态 |
| MatMulV2 | 30.8 | 13% | vision SigLIP f16 mm 为主（~904 次/iter） |
| TransData | 14.0 | 6% | **3961 次/iter 小转换（avg 3.5µs）**——op_summary 溯源 = vision 激活图内 ND→NZ（如 [768,1152]→[72,48,16,16]，每层激活喂 mm 的格式规划税） |
| SoftmaxV2 | 14.0 | 6% | 三段 attention（~224 次/iter） |
| LayerNormV3（vision） | ~14.9 | ~6% | 27 层×2，双核记录（AI_VECTOR+AI_CORE 各半） |
| GeluV2 | 9.4 | 4% | 仅 vision 27 次/iter——**prefix/flow 的 gelu 已被 ABF 融合** |
| Transpose | 7.0 | 3% | vision attention 分段 headsplit/merge |
| BatchMatMulV2 | 6.3 | 3% | attention q·k/v·o（~448 次/iter） |
| TileD + Add + AddRmsNorm + 杂 | ~15 | 7% | 广播/残差/norm 全是零头（AddRmsNorm 3.3ms=1.4%） |

**总量自洽**：设备侧 ~228ms/iter + serve glue ~19 = **247ms ≈ 生产 spot 实测 246.9ms**——调度空隙≈0（GE OM 零税实证）。

## 结论

1. **实测无隐藏热点**：cube 主导（qmd 85 + mm 31 + bmm 6 = 53%）且均为已知最优形态；最大单项 qmd 37% 已是 310P 终点形态。
2. **fusion pass 在干活实证**：元素类从 680 时代的 92ms（Add+Mul）压到 31.7ms 且合体成 ABF 单算子；prefix/flow 的 gelu·mul 也被融掉（GeluV2 只剩 vision 的）——昨天「atc 同款 pass 我们享有」的实测注脚。
3. **唯一新面孔 = TransData 14ms**：vision 激活的图内 ND→NZ 格式规划（编译器自动插），6% 量级、需动编译器格式决策才能免——ROI 低，记观察不立项。
4. norm 族已彻底吃满（AddRmsNorm 3.3ms=1.4%）；rope 族 1.1ms（GatherV2D+ConcatD）。

## 遗留

- 无新增立项；性能线以此普查收口（228ms 设备侧分布健康）
- 复测工具就位（两脚本），换二进制/换 ckpt 后可一键重跑对比
