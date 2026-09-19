# 2026-09-19 C2 后半性能攻坚第一轮（msprof 定位 + 假设排除 + 对拍修复）

## 一句话

三轮 msprof 定律：vision OM ~700ms 中设备 busy 仅 ~87ms，**~600ms 是 81 次/迭代的毫秒级空隙**（形态 `EVENT → ~20ms → MemcopyAsync`）；排除 PFA host 回调与 unknown-shape 拆分两大嫌疑后，头号嫌疑收敛到 vision 独有的 111 图输出（LN aux）。**顺带揪出 eager 参考竞态 bug——C2 的 vision 104%/prefix 30% 漂移是假的，修复后 vision 全深对拍 0.1% 稳定**（fp32 oracle 待办销案）。

## 性能实验矩阵（全部 chip6 同芯）

| 图 | bench | 说明 |
|---|---|---|
| PFA + Data shape（C2 原版） | 723.3ms | 基线 |
| PFA + enableSingleStream | 635ms | ❌ 选项无效（仍 58 流）且数值崩 98.2%（融合选择改变），弃 |
| 手工 attention（bmm+softmax） | 700.7ms | 对拍 0.1%；停顿仍在 |
| 手工 attention + Const shape | **702.1ms** | OM 221MB→16MB；停顿仍在 |

busy 各版本一致 ~87-98ms/迭代。**墙钟被空隙锁死在 ~700ms，与图内容无关。**

## profile 定量（每迭代）

- 空隙 ~600ms = 81 chunks × ~7-20ms；结束于 MemcopyAsync（'other' 型）、开始于 EVENT_RESET
- 算子 busy：TransData 17-21ms（304-465 次）、MatMulV2 19ms（110 次）、LayerNormV3 14.7ms（55×双核）、Transpose 13ms（manual 版 headsplit）、GeluV2 9.5ms、PFA 8.75ms、SoftmaxV2 6.3ms、**BatchMatMulV2 仅 1.1ms（54 次 × 20µs）**
- InnerPFA host launcher 27 次/迭代（GetWorkspaceSize 每执行 host 跑）+ 每执行 447 次 aclCreateDataBuffer（=336 入+111 出，运行时每次执行重建 dataset）

## 假设排除链

1. ~~PFA host 回调~~：手工 attention（BatchMatMulV2+SoftmaxV2，全静态 kernel，ma/ma2 单算对拍 0.26%/0.24%）替换后仍 700ms；且 bmm 比 PFA kernel 快 16×
2. ~~unknown-shape 动态拆分~~：Const 折叠 shape（OM 221→16MB，unknown 标记机制消除）后仍 700ms；**flow OM 带 2683 个 unknown 标记却 70.9ms** ——反例实锤
3. **头号嫌疑（未决）**：111 图输出（LN aux ×108 + 主输出）vs flow 1 输出。隔离实验（GEB_NO_AUX=1 全深）进程卡死无结论——**下轮用 GEB_DEPTH=2 + GEB_ROUNDS=5 最小验证（1 分钟出数）**

## eager 参考竞态 bug（本轮最重要取证）

- 症状：同图同输入 parity 非确定（ref |max| 在 0.014/0.321 间跳）；trace 模式过、非 trace 崩
- 根因①：**同步 d2h（aclrtMemcpy）不等待 compute 流上的生产 kernel**——host_ln 读到未落的 add 输出。PFA 模式被 InnerPFA host 回调天然串行化掩盖，manual（全 device kernel）enqueue 领先时确定性暴露
- 根因②：**eager 闭包中间量 drop 时 kernel 未落**——aclrtFree 非流序，内存回池被 GE 输出 malloc 复用，反向踩烂在途数据
- 修复：host_ln 签名加 stream 先同步；三段 eager 闭包末尾强制 sync。修复后 vision 全深 27 层 0.1% ×3 复跑稳定
- **推论：C2 记录的 vision 全深 104% / prefix 30% 漂移是参考被踩，"静态/运行时 tiling 变体差"理论作废，oracle 口径升级待办销案**

## 新增工具面

- `GEB_ATTN=manual`：手工 attention 路径（attn_manual/attn_manual_gqa + headsplit/headmerge，scale 折进 qkv 权重+bias 的 q 块）
- `GEB_OPT_<key>=<value>`：graph build option 直通；`GEB_INIT_OPT_<key>=<value>`：init 级直通（ge_builder.cpp）
- `geb_add_const_i32` FFI + Rust `add_const_i32` + probe `Seg::const_i32`：Const shape 节点
- `GEB_DBG=1`（层 0 各级绑图输出打印 |max|+head）、`GEB_NO_AUX=1`（跳过 LN aux 绑定）、`GEB_ROUNDS/GEB_PER`（bench 规模参数化——最小验证纪律）
- optest 新用例：asc/asc2/asc3（AttentionScore 死路）、ma/ma2（手工 attention 验证）、bc4（bias 大 shape 验证）
- 新 skill：`ascend-msprof`（最小采集纪律：全量 profile 1.1GB+10 分钟分析，假设检验先缩规模）
- 发现未接线：**BiasAdd 在 310P 注册表存在（legacy 族，elemwiseBroadcast）**——TileD+Add bias 链的潜在单 kernel 替代

## 服务器新增产物

- OM：`/data/apxinf/om_cache/{vision_ss,vision_ma,vision_mc}.om`（单流/manual/manual+const 三实验版）
- profile：`/data/apxinf/prof/{vision,vision_ss,vision_ma,vision_mc}/`（~3GB，可清）
