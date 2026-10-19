# 四件套清账日：catgu 终审五路全灭 + 舰队 2.7 天趴窝根因（2026-10-19）

## 终局一行

**goal #1（qmd x_scale 静态化终审）判死收线**：第五路「gate/up 同输入权重拼接」（绕开全部算子墙的纯图重构）A/B 实测——SliceD 版 **7.8× 劣化**（视图物化税 ~1.78ms/次复现）、SplitD 版 **中性（−0.4ms ± 噪声 ±2ms）**——量化流水在 m=50 **根本不是瓶颈**（in-op quant µs 级已融进算子二进制），flow ~70ms 设备时间 = 310P 该图的结构性地板。**0.53× 在量化侧无可达路径，五路证据链闭合，触发重新谈判**（goal 原文条款）。**goal #2 半闭环**：舰队自 10-17 09:32（北京）趴窝 2.7 天的根因 = **apxinf_rust 容器被人为 stop/start**（StartedAt=01:32:22Z 与 serve 死亡时刻吻合；docker exec -d 进程不随容器自愈、无人拉起 supervisor）；TBE「main process disappeared」×8 = 子进程对 SIGKILL 的**事后哀鸣**（plog 干净到最后一行 = SIGKILL 特征）。**goal #4 完成**：pool_cap env 化 + 生产 cap 9 部署确认。

## 一、catgu 终审（goal #1 收线）

### 思路

x_scale 静态化本体早已三路判死（10-08：pertensor attr 过校验但执行 bit 级同
pertoken = 输入被忽略；perchannel/pertokenScale 编译拒；10-19 gitcode 上游
盖章 per-token 内核从未存在）。本轮打**第五路**：gate/up 共享 mnorm 输入 →
int8 权重沿 n 拼接 [gate;up] 一发 qmd（[50,1024]×[8192,1024]）→ 输出列半切
回两半——每层每步省一条 in-op 逐 token 量化流水（gud 子集 540→360 op/replan），
不碰任何算子语义。

**smooth 冲突及解**：gate/up 各有独立 s_eff（per-k）→ 公共因子
s_f = 逐列 max(s_gate, s_up)，双矩阵按 s_f 重量化。**真 rel err 实测（修复
[k,n]/[n,k] 错位索引 bug 后）：gate 2.4813%→2.4779% / up 2.3043%→2.3069%**
（±0.003pp，偏离上界 s_f/s_own ≤ 1.490）——**smooth 融合重量化数值代价 ≈ 0**，
golden actions rel=3.7% 与 base 同带。数值面完全可行，死在性能面。

### A/B 判决表（tl160 桶 golden，L=154，同新二进制双臂）

| 臂 | flow 10 步 | actions rel | 判读 |
|---|---|---|---|
| base（2×qmd n=4096） | 93.92ms | 3.7% | 生产复现基准 |
| catgu + **SliceD**×2 | **735.7ms** | 3.7% | 消费者触发运行时视图物化（MemcopyAsync + host 参与）**~1.78ms/次 × 360 次**——vision QKV3 时代 4.5-12ms 停顿同款机制在 flow 形状复现，**判死** |
| catgu + **SplitD**×1 | **93.56ms** | 3.7% | 动态双输出真算子，编译执行全通——**但收益 = 0**（Δ−0.4ms 在 harness 噪声带 ±2ms 内） |

### 物理解读（对 09-30「quant 开销对冲带宽减半」的修正）

拼接把 op 数 2→1、quant 流水 2→1，权重字节两臂恒同（8192×1024 int8）。
SplitD 版净零 ⇒ **per-op quant 流水与 op 固定开销都不是 flow 的瓶颈**——
flow ~70ms 设备时间由权重流带宽 + attention/norm 工作量决定，是这张图在
310P @ m=50 的结构性地板。09-30 的 −5.4ms 净收益缺口应重读为带宽兑现率
问题，非可砍开销。

### 五路全灭总表（0.53× 量化侧证据链闭合）

| # | 路线 | 死因 | 轮次 |
|---|---|---|---|
| 1 | qmd 静态 x_scale | pertensor attr 被忽略（bit 级同 pertoken）；perchannel/pertokenScale 编译拒 | 10-08 |
| 2 | w8a16 WQBMV2 | 310P tiling 模板墙（arch35） | 10-08 |
| 3 | 分解式 w8a8 per-token | 内核不存在（源码声明、二进制缺失；上游 master 已删假门） | 10-08 晚/10-19 |
| 3b | 分解式 static-x | 三算子链 2× 慢 + f16 值域陷阱 | 10-08 晚 |
| 4 | 同输入拼接 + SliceD | 视图物化税 7.8× | 本轮 |
| 5 | 同输入拼接 + SplitD | 中性（量化流水非瓶颈） | 本轮 |

**0.53× 重新谈判建议**：現行 1.09×（243→226ms）为量化侧终点；剩余理论杠杆
均非量化侧且已逐一预检否决（vision int8 −6~7ms 不值、段间融合上界 ~3ms、
TransData 14ms 编译器税 ROI 低）。

## 二、舰队 2.7 天趴窝根因（goal #2 半闭环）

- **现场**：10-19 晨 fleet_watch = chip4 DEAD + **supervisor 本体消失** +
  8 僵尸；ready 停在 10-16 09:58:45Z
- **尸检**：末代 serve（pid 612831，10-16 09:21Z spawn）**健康服役 15.5h**，
  10-17 01:28Z 还在处理 #25 号请求（flow 76.8→84.9ms = 内存压力下 mmap 权重
  页逐出的抖动签名），01:31 死亡；stdout 尾随 TBE「main process
  disappeared」×8 + EOFError；**plog 干净到最后一行**（只有每 10min 例行
  TryToRecycle——零 ERROR = SIGKILL 特征）
- **铁证**：`apxinf_rust` StartedAt=**2026-10-17T01:32:22Z**（死亡后 1 分钟）
  RestartCount=0 = **人为 docker stop/start**；host 未重启（uptime 10-03）
- **机制**：容器重启灭掉 serve+supervisor 全家（docker exec -d 进程不随容器
  自愈）；**无人拉起 → 趴窝 2.7 天**。「无人值守重启风险」不是假设是事实
- **两现象拆分**：① 10-16 08:xx respawn 风暴（TBE 孤儿链，pkill 清场即愈）
  与 ② 10-17 容器重启灭门是**两回事**——后者才是趴窝根因
- **dmesg 前科**：10-12 OOM killer 杀 ge_model_probe（anon-rss 16.6GB）两起
  ——大 rss 进程是 OOM 首选目标，但本次不是 OOM（容器层重启时间戳铁证）
- **运维缺口与提案**：容器重启后无自愈路径。**提案（待用户批，常驻面纪律）**：
  host cron 每 5min `docker exec apxinf_rust pgrep -f serve_range_supervisor
  || bash /data/apxinf/start_gear_supervisor.sh`——一行 crontab，容器重启
  ~5min 内自动复活；不做自动 pkill（TBE 风暴场景仍走人工清场流程）
- TBE 风暴（现象①）的 slog 深挖未做（崩代 plog 在档可查）；运维价值已由
  提案覆盖大半

## 三、pool cap 8→9（goal #4 ✅ 完成）

- `pool_cap: envi("GEB_POOL_CAP", 8)`（PrefixMech 构造，缺省 8 不变）+
  supervisor spawn env 加 `GEB_POOL_CAP=9`
- 部署随本次复活窗口落地：serve stdout `[prefix-pool] ... (lazy, cap 9)` 确认
- 满谱系 9 桶全驻留、LRU 驱逐重装（2.7s/次）根除

## 四、range 观察期（goal #3 进行中）

- 舰队 10-19 11:52 复活（pkill 清场 + start_gear_supervisor，新二进制 =
  catgu 实验版但全 env 门控缺省关 = 生产等价 + cap 9）
- 复活后 spot 三谱系（object:0/spatial:4/goal:9）当日跑（spot1019r）；
  隔日再一轮 + fleet_watch 快照后收尾清理（精确 26 桶 + tl154_v* + ab_catgu
  实验桶 ~1.2GB + dump 目录）
- 复活窗口顺产：warmup flow 10 步 108.9ms @ tl200 桶（P=200 更宽属正常）

## 五、工程副产物（全入库）

- **ge_builder dyn_outputs API**：`geb_dyn_outputs`（OpDesc AddDynamicOutputDesc
  重声明直连 libgraph_base，同 dyn_inputs 手法）+ `geb_set_output_desc_idx`
  （port 版，UpdateDynamicOutputDesc）+ Rust 包装——**多输出 legacy 算子的
  通用接线件**（SplitD/SplitV 类）
- **动态输出三坑**（全实证）：① CreateOperator 不预建 y×N 端口（须先
  dyn_outputs 分配）；② UpdateOutputDesc(flat idx) 被拒（须
  UpdateDynamicOutputDesc(name, idx)）；③ 分配后 link_idx(flat) 可用
- **引擎对齐债**：服务器 cmake 源（/data/apxinf/ascendc/ge_builder/）比仓里
  新（dyn_inputs 重声明块只在服务器）——本轮已拉回对齐入仓
- 探针资产：`bake_catgu_ab_1019.sh`（双/三臂烤制）、`ab_catgu_1019.sh`
  （golden A/B，**run 侧必须同 env——池模式=进程内建图+OM 换柄**）、
  catgu OM 留档 om_cache/ab_catgu/{base,catgu,catgu2}（观察期后清）
- harness 噪声带：同配置两跑 93.9 vs 96.0ms = **±2ms**（A/B 判读下限）

## 六、踩坑（当日实证）

1. **池模式 A/B 的 env 一致性**：烤制 env 必须在 run 侧复现（n_in 307≠289
   断言即此坑）；catgu2 mode 判定 `==1` 漏 `==2` 导致一轮假阴性（93.9 vs
   96.0 实为 base-vs-base 噪声测量——因祸得福拿到噪声带）
2. relerr 诊断的权重布局：loader 原生 [k,n]（quant_w8 内转置）——参考值
   按 (c,r) 取，141% 垃圾数即错位索引
3. docker exec -d 双发 spot：并发对打 serve + 同 jsonl 双写——杀树清 jsonl
   重发单实例（results-jsonl 有记录即跳过纪律对并发不设防）
4. 服务器引擎树无 .git：git apply 免仓可用、checkout 不行——回退用
   `git apply -R`
5. bash `a && b` 末位假值不触发 set -e（AND-OR 列表豁免）——case/if 显式写
