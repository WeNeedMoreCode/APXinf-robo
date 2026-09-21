# M3 剩余漂移根因终结：InplaceAddRmsNormFusionPass 原地融合污染在图中间量

日期：2026-09-21（下午班）　前置：[上轮定罪](2026-09-21_ge-addrms-ingraph-corruption.md)（[在图中间量→AddRmsNorm] 污染、内存重叠嫌疑、修复留下轮）

## 一句话

**上轮嫌疑"GE 静态 OM 内存计划重叠活 buffer"的实体找到了：`InplaceAddRmsNormFusionPass` 把 AddRmsNorm 融合成原地算子 `InplaceAddRmsNorm`（注册表 output0 名就叫 `x1`、output2 叫 `x2`——结果写回两个输入 buffer 本体），原地别名与静态内存计划的交互在读"在图中间量"时污染数值；关掉该融合 pass 后 MIN 复现图 11.041%→0.159%、全量 attn 图 45.224%→0.159%，全部转净（fp16 噪声底）。**修复 = init 级选项 `ge.fusionSwitchFile` 指向 JSON 开关文件（官方文档明载该 pass 可关，仅"功能使用风险"）。机制细粒度（具体哪个别名与哪段计划冲突）未钉死——标注为推测：别名 buffer 的计划复用；Data 输入免疫因用户 buffer 全程受保护。

## 定位链（本轮，用户提示"查 demo 实现"成为破局点）

| # | 动作 | 结果 | 裁决 |
|---|---|---|---|
| 1 | `GEB_OPT_ge.bufferOptimize=off` 跑 MIN 图 | rc=-7 编译拒 | build 级选项 map 不收 `ge.*` 名 |
| 2 | 同名默认值 `l2_optimize`、atc 短名 `buffer_optimize` | 均 rc=-7 | 排除"值无效"——是层级传错 |
| 3 | init 级 `GEB_INIT_OPT_ge.bufferOptimize=off` | init rc=-1 | 层级对了但值 `off` 非法 |
| 4 | **查本地 GE 开源源码仓 `D:\compass\ge`**（用户建议查 demo） | `ge_ir_build.cc` CheckGlobalOptions：bufferOptimize 从 **global_options（init 级）**读；合法值 **`off_optimize`**；正上方就是 `ge.exec.disableReuseMemory` | 选项归属权威索引确立（atc main_impl.cc 的 SetAtcTuningOptions 全进 init map） |
| 5 | `disableReuseMemory=1` / `bufferOptimize=off_optimize` 跑 MIN | **均逐位不变 11.041%** | 复用类开关无效——但注意二者都不管 Const 别名；排除法价值仍在 |
| 6 | **`DUMP_GE_GRAPH=3 DUMP_GRAPH_PATH=...` 逐 pass 图 dump**（机制见 ge 源 graph_utils.cc NoNeedDumpGraph） | 最终 Build 图里 AddRmsNorm 变成 **`InplaceAddRmsNorm`**，attr 溯源 `InplaceAddRmsNormFusionPass` | **融合 pass 实锤** |
| 7 | dump 对照干净图 wmm4（Data 输入） | 同样被融合但仍干净 | 融合单独不定罪——需要"中间量输入"触发 |
| 8 | 源码查 fusion 开关机制（fusion_config_parser.cc） | JSON 4 层结构，第 4 层字符串 "on"/"off"；`ge.fusionSwitchFile` init 级 | 修复件 = fusion_off_inplace.json |
| 9 | **决定性实验：`GEB_INIT_OPT_ge.fusionSwitchFile=...` 跑 MIN 图** | **11.041% → 0.159%** | **根因终结** |
| 10 | 全量 attn 图（非 MIN）同开关 | **45.224% → 0.159%**（h1_vis 0.032%） | 修复在全图成立 |
| 11 | 910b stub + **310P 本机注册表**（`aic-ascend310p-ops-info-nn.json`）查 InplaceAddRmsNorm 语义 | 两边同构：inputs {x1, x2, gamma}、outputs {**x1**, rstd, **x2**}——输出端口名=输入端口名 | 原地写回解剖学证据（310P 已验，非推断） |

## 修复件

```bash
# /data/apxinf/fusion_off_inplace.json（本地镜像 syx_docs/dev_logs/fusion_off_inplace.json）：
{ "Switch": { "GraphFusion": { "InplaceAddRmsNormFusionPass": "off" }, "UBFusion": {} } }

# 使用：init 级（不是 build 级），env 名带点要包引号
GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json
```

生产 e2e 运行口径从"四件套"变"四件套 + 融合开关"（OM 必须带开关重烤——融合状态烤在 OM 里，旧 t712 缓存不携带修复；新缓存目录 /data/apxinf/om_cache/t712fix）。

## 与上轮 16 步洗冤链的全兼容性

- 五类屏障/端口变体逐位不变：屏障全在 x1 侧，不动融合决策与别名 buffer 计划 ✓
- 同值 Data 输入干净（wmm4）：用户 buffer 全程受保护，原地别名无冲突面 ✓
- 小图 [mm→addrms] 干净（wmm5）：计划随图而变，小图未踩中别名冲突 ✓
- 图形状强敏感（net 45.2/dbg 24.7/垫M 24.66/MIN 11.0/RES_GOLDEN 78.6）：内存计划随形状变 ✓
- `disableReuseMemory`/`bufferOptimize` 无效：Const 别名不在其管辖 ✓
- 生产影响面吻合（kvk_l0 净=x0 是 Data；l1 45%/l17 84%/actions 323% 逐层复合；flow 小 shape 1.6%；vision 无 AddRmsNorm 净）✓
- eager aclnnAddRmsNorm 干净：eager 无 GE 计划器参与 ✓

## 生产验证（e2e + 性能）

**三段重烤（t712fix，融合开关全程携带；parity vs eager 参考，GEB_BENCH=1 GEB_ROUNDS=5 GEB_PER=3）**：

| 段 | parity（修复前 → 后） | bench（修复前 → 后） |
|---|---|---|
| vision（27 层，无 AddRmsNorm） | 0.1% → 0.1%（不变） | 55.86 → 56.11 ms（打平） |
| **prefix（18 层，36 处 addrms）** | 真权重 d=18 时 100%+ → **worst 0.8%**（36 输出全 0.3-0.8%） | 124.61 → **115.99 ms（快 7%）** |
| **flow（18 层，HOR=50）** | 真权重 37.4% → **4.4%**（ref \|max\|=1.016 小分母 + fp16 累加序残余，非 addrms） | 7.89 → **7.57 ms/步** |

全模型估算 ≈ 248ms 持平（修复零性能代价，反而净赚——非原地版无别名约束，内存计划更自由）。OM 三件套 5.2GB 已落 /data/apxinf/om_cache/t712fix/。

**e2e 全链对拍（golden v3，t712fix OM + 融合开关）——addrms 修复全面落地**：

| 中间量 | 修复前 | 修复后 |
|---|---|---|
| vision_out / x0_vis | 0.3% / 0.1% | 0.3% / 0.1% |
| kvk_l0 | 0.3% | 0.3% |
| **kvk_l1** | **45.2%** | **0.4%** |
| kvk_l2..l16 | 深度复合 | 0.4→1.4% 平滑次线性（教科书 fp16 累积曲线） |
| **kvk_l17** | **84%** | **3.8%** |
| step0_x1 | 10.1% | 11.8%（小分母 \|max\|=2.953） |
| actions | 323% | 363.6%（\|max\|=1.055 小分母） |

**残余定性**：step0_x1/actions 与 addrms 无关（修复前后同量级 11.8%/~350%）。noise 已确认同源（probe 从 golden safetensors 载 `noise` 键起步）⇒ 11.8% 是真残差。候选：① prefix 主路 hidden 残差（kvk_l17 3.8% 同类）喂 flow cross-attn ② **host 侧 styles 计算**（sinusoidal→time_mlp→style 链在 probe host f32 算——flow 段 4.4% parity 是 vs eager 同 host glue，styles 偏差会在段内抵消、只在 vs golden 显形）③ flow 段自身 4.4%。**下轮第一动作：bisect flow step0**（golden styles/pk-pv/x1 渐进替入，定位 11.8% 的最大贡献者）。

## 教训（方法论追加）

1. **"内存计划类" bug 的最快解法是让编译器把决策亮出来**：`DUMP_GE_GRAPH` 逐 pass 图 dump 一眼看到融合改写；比猜选项 A/B 快一个数量级。
2. **编译选项传错层与选项不存在同症状**（rc=-7/-1）——归属权威索引 = 开源 GE 仓 `CheckGlobalOptions`（init 级）+ atc `main_impl.cc`（哪 个 map）；`ge.*` 名 init 级、atc 短名 build 级。
3. **inplace 系融合（输出名=输入名的算子）与自管输入绑定的图天然有冲突面**——凡走 GE 离线 OM 且用 AddRmsNorm 类算子，先关对应 Inplace 融合或验证中间量对拍。
4. 用户提示"去查查 demo 实现"直接命中破局点：本地 `D:\compass\ge` 开源仓 = 选项注册表/融合解析/dump 机制的 ground truth，比黑盒扫 strings 快得多。
