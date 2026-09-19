# C2 性能攻坚第二轮：切片视图运行时物化——根因捕获与三段修复（5.06×）

日期：2026-09-19（第二轮，接 summary/2026-09-19_c2-perf-attack-round1.md）

## 结论一句话

**~600ms 空隙的根因 = SliceD 列切视图触发运行时 MemcopyAsync 物化**（每视图 1 次
~380µs 拷贝 + 前置 ~4.5-12ms host 停顿）。三段同病：vision 融合 qkv 切 q/k/v（81 次/
执行）、prefix 叠加 rope 内部 lo/hi 半宽切（70 次）、flow 同构。三个图组织修复
（qkv 独立投影 / flat rope 行交换 / 手工 attention）把全模型 **2182ms → ~431ms（5.06×）**，
距 378ms 验收线 14%。

## A/B 裁决链（最小验证纪律：GEB_DEPTH=2 + GEB_ROUNDS=5 GEB_PER=3）

| 实验 | 结果 | 裁决 |
|---|---|---|
| 111 图输出假设（GEB_NO_AUX） | depth2：aux 46.4ms / noaux **710.5ms** | **反向击毙**——aux 不是成本反而在阻止病态（死端 mean/rstd 换 LN 动态变体更糟） |
| 两个 depth-2 OM 对比 | 尺寸 1.41 vs 1.35MB，kernel 同族 | 排除编译产物差异 → 病在运行时 |
| vision_ma（上轮 profile）重挖 | 82.4 次 MemcopyAsync/执行，全在执行流 s370，每次前 4.5-12ms 全局空隙 | 空隙 98.8% 终结于此 |
| 邻接分析 | 24518/24518 次 MemcopyAsync 的下一 kernel = 同一个 te_transpose（headsplit，81 次/执行） | 拷贝挂在 q/k/v 切片消费者前 |
| PFA 模式同数 | round-1 InnerPFA staging 也是 27×3=81/执行 | 共同因子 = 每层 3 个 q/k/v 张量，非 attention 实现 |

机制：SliceD 输出是列视图（stride ≠ 连续），下游 kernel 要连续物理布局 → GE 运行时
每次执行插 D2D 物化拷贝（~1.77MB/次 ≈ 380µs DMA），且该拷贝走 host 慢路径（每
次 ~5.5ms host 停顿，aclmdlExecuteAsync 内部走走停停提交——api_statistic 证明
688ms 全程占满 host，tiling 类 API 总量极小）。

flow 反例解释：flow 编译走 unknown/动态路径（2683 标记），切片被物化为真实 kernel
而非视图——所以 flow 没付这个税（也解释了为何 flow 带unknown标记却只有 70.9ms）。

## 三段修复（全部 env 门控，默认关闭保持旧行为）

| 修复 | env | 内容 | 效果 |
|---|---|---|---|
| qkv 独立投影 | GEB_QKV3=1 | 3×mm + 独立 qw/kw/vw/qb/kb/vb 输入替代融合 qkv mm + SliceD×3（权重 host 切一次；qkv3 下不注册无消费者的 qkvwt/qkvb 防 GE 摘除输入导致 dataset 错位；eager 层内索引 12/10 项 → 16/14 项偏移） | vision 723→~145；prefix 750→550 |
| flat rope | GEB_ROPEFLAT=1 | rope2 的 slice2×2+ConcatD（lo/hi 半宽列切）→ 换视图行交换：Reshape[p,wd]→[p·h·2, d/2] → GatherV2D(相邻行 swap，**Const 索引**) → mul/mul/add → Reshape back（表 = 段级 flat cos/sin 输入，eager 同款；GatherV2D 310P 仅 axis=0，故必须换 flat 视图做行交换） | prefix 550→188 |
| 手工 attention | GEB_ATTN=manual | 三段统一：headsplit + bmm+SoftmaxV2+bmm（prefix/flow GQA 版 k/v TileD 广播 + cross 长度），scale 折进 q 权重/bias | vision 顺带消 PFA host launcher；prefix/flow 各 -2%~-75% |

最终（全深，ROUNDS=30 PER=10 median/10，chip6）：

| 段 | 修前 | 修后 | 对拍 |
|---|---|---|---|
| vision (27 层) | 723 | **68.06** | 0.1% |
| prefix (18 层, P=832) | 750 | **187.75** | 25.1% ⚠ |
| flow/步 (18 层) | 70.9 | **17.51** | 1.6% |
| 全模型 | **2182** | **~431** | — |

OM 产物：/data/apxinf/om_cache/{vision,prefix,flow}_r2.om（GEB_LOAD 可载）。

## 顺带修复：flow eager 段级索引陈旧 bug

round-1 把 shape 张量 data_i32→const_i32 后 4 个输入槽消失（ainwt 16→12、pk_i
18→14），flow eager 硬编码索引没跟着改——[832,256] 读到 qkvwt 触发 tensor.rs size
断言 panic（伪装成 TBE task_distribute 崩溃）。flow 自 const 改造后没重跑过所以
一直没暴露。已修（索引 + 注释指明当前注册序）。

## 遗留

1. **prefix 25.1% 对拍漂移**（open）：vision(INTER=4304)=0.1% / flow(4096)=1.6% /
   prefix(16384)=25% 随 MLP 宽度单调——假设大 K 下 fp16 累加序差（GE tiling vs
   eager split-k），与 trap #18 同类；e2e 影响待 M3 LIBERO 判定。深挖可用
   fp32 oracle 或 GEB_DBG 层级定位首个分岔层。
2. msprof 导出在新采集上静默失败（end_info/host/sqlite 俱在、无 CSV；上轮产物正常）
   ——本轮用 host ge_info.TaskInfo ⋈ device hwts-rec.db(HwtsBatch) 恢复了部分
   数据（**注意主链 stream 的任务不在 HwtsBatch，在未导出的 aicore.data**）。
   修法待查；skill 已记。
3. GEB_NO_AUX 死端病理（LN 动态变体 710ms）未深挖——已被主线绕开。
4. BiasAdd 接线、eager take_rows、ARPE、OM 缓存 key 化（后置不变）。

## 下一步

- prefix 剩余 188ms 里 MLP matmul busy ~145ms 是算力下限附近；flow 17.5ms/步仍有
  ~1ms/层非算力开销可挖
- 全模型 ~431ms vs 378ms 线（1.14×）→ 判定会谈进 M3 或先收 flow 尾巴
- 文档/陷阱回填：ge-offline-om #28-30、ascend-msprof 导出恢复路径
