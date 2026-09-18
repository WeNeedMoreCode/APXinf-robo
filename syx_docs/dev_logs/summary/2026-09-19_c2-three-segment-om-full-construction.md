# 2026-09-19 C 路线 C2 三段 OM 全量落地

## 一句话

C2 ⑤⑥⑦ 全部落地（f0787fa）：vision(27 层)/prefix(18 层+KV 输出)/flow(18 层单步) 三段静态 OM 编译+运行+落盘全通；flow 全深对拍 1.6%；**bench 全模型 ~2182ms 距 378ms 验收线 5.8×——不达标**，慢源待 msprof 定位。七项新 GE 陷阱取证回填 skill #12-18，顺带发现生产 eager 的 qkv 切分数学 bug。

## 分项

| 项 | 结果 |
|---|---|
| ⑤ 三段 OM | 全部编译+运行通；vision 336 输入 / prefix 195 输入 36 输出 / flow 276 输入 |
| ⑥ OM 缓存 | GEB_SAVE/GEB_LOAD 通；/data/apxinf/om_cache/{vision,prefix,flow}.om |
| ⑦ bench | vision 723.3ms / prefix 750.0ms / flow 70.9ms/步（×10）≈ **2182ms** vs 线 378ms |
| 对拍 | flow 1.6% ✓；vision/prefix 组件级逐位（LN/gelu/TileD/Reshape/PFA batch 全 0.000x）但全深漂移 104%/30%（tiling 变体差，oracle 口径待做） |

## 排障主线（七新陷阱，全部取证定罪，skill #12-18）

1. **BroadcastToD** 310P kernel 编译崩（TBE task_distribute 空错误）→ TileD（multiples attr）替代，数值逐位
2. **ConcatD DYNAMIC_INPUT 端口工厂不预建**（GetDynamicInputNum=0；TF parser 手动 AddDynamicInputDesc）且 toolkit 无 op_desc.h → **libgraph_base 符号直链**（OpDescUtils::GetOpDescFromOperator + OpDesc::AddDynamicInputDesc，pre-CXX11-ABI 匹配）；端口名 **x0/x1 从 0 起**
3. **Reshape 输出绑图输出 → 模型输出 desc 动态 [-1,-1,-1]**、size ~1e16 → malloc 207001 → 图输出只绑静态 desc 节点（prefix 的 k/v 改绑 rope 的 rank-2 ad 输出）
4. **AddLayerNorm 在 [768,1152] kernel 级 ~100× 放大**（行方差正常；eager aclnn 与 GE 一致地错）→ LayerNormV4（normalized_shape 张量输入），0.00098
5. **LayerNormV4 的 mean/rstd 死端会让 y 爆**（65504；与 AddRmsNorm 死端无害相反）→ 全部绑图输出（aux，parity 跳过）
6. **Reshape→SliceD / mm(rank-3 out)→下游 组合编译崩**（各自单算过）→ 全链 rank-2：mm(rank-2)→SliceD(rank-2)→Reshape(rank-3 桥)→PFA（数值逐位）
7. **GE vs eager 全层多层逐层漂移 ~2%/层**（层 0 逐位）= 静态/运行时 tiling 变体差 → 多层对拍口径升级 fp32 oracle

## 其他记录

- **生产 eager 的 qkv/gate_up take_rows 切分是数学错误的**（fused 输出 [m, q|k|v] 列交织，take_rows 的 flat 切分取错段；全部历史 smoke 只查"输出有限"从未数值对拍——C1 单层对拍输入就是切好的 q/k/v 绕过了它）。probe 的 eager 参考用三独立 matmul。修复后置（eager 降级回退路径）
- probe 数据纪律：LCG 高 16 位 mod 200 有短周期结构（曾误导排查方向）→ splitmix64；vision 链幅度 div=300/30000/12000
- chip 间行为差异实证：chip 4 数值 diverge / chip 6 正常（同二进制）——bench 一律用同芯对照
- OM 落盘三件 + GEB_LOAD 缓存加载路径已通（编译分钟级 → 秒级加载）
- 性能疑点（下一轮 msprof 战场）：TileD/SliceD/Reshape 拷贝类 kernel 开销、LN 辅输出 108 个、数百输入的 dataset 绑定、编译器融合率
