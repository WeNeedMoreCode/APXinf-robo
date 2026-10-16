# 2026-10-16 动态图结构消融终裁：「怪 GE 还是怪我们的组装」

handoff goal #1（用户指定）执行闭环。T4R 尾声实验：裁定 13.1% 互差的元凶
是 GE 动态通路固有，还是我们的 dyn 组装选择。

## 一、判决表（t4 真帧 golden frame0_t4v1b，L=154，vs torch）

| 构造 | 隔离维度 | prefix n_in | l0 kvk/kvv | l2 kvk/kvv | actions | 判决 |
|---|---|---|---|---|---|---|
| static 基线（tl154_i8） | — | 260 | 0.9/0.8% | 2.2/5.0% | 4.3% | 参考 |
| **V1** bias 折叠（GEB_ABL_BIAS=1） | 90 悬空行不注册 | 170 | **0.9/0.8%** | **2.2/5.0%** | **4.3%** | **排除** |
| **V2** rope/qswap Data 化（GEB_ABL_ROPE=1） | qswap_c/kswap_c Const→Data | 262 | **0.9/0.8%** | **2.2/5.0%** | **4.3%** | **排除** |
| **V4** smooth Const 化（GEB_ABL_SMCONST=1） | 126 sm Data→Const | 138 | **0.9/0.8%** | **2.2/5.0%** | **4.3%** | **排除** |
| V3 ≡ E1 桶（tl_dyn_g154，-1 dims 两档） | 动态分档通路 | 14 | 1.6/2.2% | —/80.8% | 17.8% | **唯一存活** |
| dyn 全装（tl_dyn，26 档） | 全部 | 14 | 1.7/2.1% | 22.5/55.9% | 13.1% | 参照 |

**三个变体全部与 static 基线 bit 级一致**：vs-torch 的 max_diff 五位小数、
argmax 索引逐一相同；离线互差（cmp_dumps，dump vs dump_static_t4）全层
**0.00% / cos=1.000000**。GE 把这些注册方式差异编译成了完全相同的 kernel。

## 二、终裁：怪 GE 的动态分档编译通路，组装侧无罪

归因链（排除法）：
1. static 与 dyn OM 的全部结构差异 = 五个维度。其中**权重 Const 化
   （原 V0）根本不是差异**——静态桶与 dyn 同在 GEB_WCONST=1 下烤（supervisor
   spawn env 实证；昨晚「权重 Data 化」注释是误标，本晨已纠）。
2. 剩余四维：bias 注册（V1）、rope/qswap Data 化（V2）、smooth Const 化
   （V4）、**desc -1 + dynamicDims 分档（V3/D1）**。前三个逐一在静态图内
   复现 → bit 级不变 → 数值惰性。
3. D1 无法纯净隔离（SetDims 145012：动态图内静态内容 Data 必须 Const 化，
   即 D1 必然携带 D2-D4）——但 D2-D4 既已证惰性，E1 桶（D1+惰性携带）的
   漂移可全权归于 D1；「组合效应」分支排除（惰性维度组合不出漂移，且 E1
   两档 ≈ 26 档同差说明与档表范围无关，是 -1 机制本身）。
4. 机制：-1 desc → MultiBatchClone 逐档特化 → per-档 tiling/算子选择不同
   → int8 累加次序不同 → l0 即 2× 漂移，经 18 层放大到 actions 13%+。
   官方文档「动态图精度表现可能与静态图存在差异」与实测对上，且现在有了
   逐维度排除的证据链。

**dyn 复活路线正式关闭**：一图多档必须 -1 dims（GE 单档烤不出 rc=-7），
走 -1 dims 就有分档特化漂移，组装侧无旋钮可调。**池化（GEB_PREFIX_POOL）
终审盖章**——它绕过的正是且只是 D1。

## 三、副产物

- **接口三态的数值学解释**：260/170/14 的 n_in 差异纯接口化妆，无数值后
  果（V1: 260→170 bit 不变）。GE 编译器对 Const/Data/注册方式差异完全
  等价编译（本图范围内）。
- V4 首跑翻车记录：reg_i8 是 prefix/flow 共用 helper，SMCONST 未限定
  作用域时 flow compose 也吃门控（306→252 ≠ 拷贝的静态 flow OM 306，
  rc=-2）——修复 = `key.starts_with("prefix/")` 判别（flow 是对照组必须
  保持与基线一致）。
- bash 坑：`local a=$1 b=x_$a` 单行多赋值，$b 里的 $a 取外层值（空）——
  首发射 OM 全落 `tl154_`、v2rope 载错 OM 崩（TBE 报错）。逐行 local 修
  复；tl154_v1bias 是从 tl154_ 改名 salvage 的（烤桶本身有效）。

## 四、引擎与工具（全部入库）

- 引擎（apxinf/ 子模块，fork/ascend-port 3e47e8e）：
  - `1ea2ec5` 三门控：GEB_ABL_BIAS（row_bcast/bias 走 gear 式注册）、
    GEB_ABL_ROPE（qswap_c/kswap_c 转 Data）、GEB_ABL_SMCONST（sm 烤 Const）
  - smfix commit：SMCONST 限定 prefix（reg_i8 key 判别）
- 工具：`probe_dyn/abl_struct_1016.sh`（烤+跑一体，支持单变体重跑）
- 服务器留档：om_cache/tl154_{v1bias,v2rope,v4sm}/（各 ~3.1GB，清理候选）、
  golden/dump_v{1,2,4}*、abl_*.log

## 五、遗留

- 三个实验 OM 目录 ~9.3GB 留档未删（判决已提取，可清）
- 池模式例行化（goal #2）不受影响，照旧
