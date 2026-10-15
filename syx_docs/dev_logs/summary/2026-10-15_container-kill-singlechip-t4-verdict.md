# 2026-10-15 容器被杀 → 单芯收缩 → 回退桶判决与 t4 根因链（正向解开工）

一天三段：同事杀容器 → 用户指令收缩单芯+否定回退规避 → t4 数值差异取证定性。

## 一、事故与对账

北京时间 15:30/15:31，apxinf_npu / apxinf_rust 被 SIGKILL（137）。触发背景：同事 `ys_qwen3.8-flash` 容器一小时前上线（本机还有跑了 12 天的 `vllm-ascend`，占 0-3 各 ~19.7GB + 6-7 各 ~32GB）；他们视角看到「不同的卡一直起进程」= 我当天的取证批处理：**chip 2 半小时内 5 次完整模型加载**（帧分解探针×3 + 取证 eval×2，每次 ~200s 加载）+ chip 4 vision dump + LIBERO eval 让 0-3 轮询闪活 + 生产舰队常驻 6 卡（4 gear serve + 7 回退桶）。

**我的责任**：遵守了「用哪张卡」约定（chip 2 = spot 惯例、chip 4 = 空卡）但没考虑**批处理频率**——5 次加载本可合并成一次进程。记入纪律。

**白捡**：2347 僵尸随容器清零；两个 commit（I9/I10）不依赖服务器。

## 二、用户两条指令与执行

1. **「一直占用一到两张卡，不要全铺开」**——gear supervisor 芯表 `0 1 2 3`→`4`；旧 chip0-3 spool 目录归档 `_retired_1015/`；fleet_watch 芯清单参数化（GEAR_CHIPS 可覆写）+ 回退段改「RETIRED/在役」自适应；spot_eval 默认 CHIP 2→4。gear = 单芯多档 OM，单次推理本就单芯（246.9ms 是单芯数字），4 份纯属当年冗余。
2. **「遇到问题正向解，回退桶规避业界闻所未闻」**——预案 B（补回退）作废，改为根因战役（下节）。

## 三、回退桶退役验证：失败（gear 3/5）

static_fallback_llist 摘除、全 L 走 gear、spatial t4 ×5（seed 7，val_spatial_t4_gear_nofb.jsonl）：
**3/5**（trial 0/4 失败 = 520 步打满死走型；1/2/3 过）。门限 ≥4/5 未达 → 当场决策不恢复回退（用户方向），转入正向取证。

## 四、正向取证三连（本日核心产出）

**① 垃圾 payload A/B（ab_dyn_static_1015.py，seed 7 全定死合成输入）**
同 payload 打 dyn 与静态桶：L=152 差 11.56%、**L=144 对照差 14.07%**——「高 L 档 bug」假设**证伪**（分歧不集中事故档）；同时确立**合成输入混沌地板 ~11-14%**（随机占位 token + 随机噪声图下 flow 链混沌放大主导）——此仪器测不出真实分歧，废弃。副产物：**dyn prefix 同 L 比静态慢 13-16ms**（102 vs 89ms，动态 shape tiling 代价——修复红利候选，246.9 里 ~14ms）。

**② golden 逐层 bisect（ab_golden_dyn_static_1015.sh，frame0_v3b L=200 真帧，同芯 chip5 背靠背）**
引擎自带 kvk/kvv 18 层逐层对拍 vs torch golden 自动打印：
- **静态与动态的逐层漂移剖面基本相同**：kvk 3-9%、kvv 4-23%，随层加深、l17 最差（kvv 17-21%）、kvv 一致差于 kvk
- 结论：两路径是**彼此等距的 int8 近似**（各自 vs golden 同量级同形态），互差收敛到 actions 级 ~1%——不是「一条对一条错」
- vision 段 0.3%、x0_vis 0.1%（与既往一致，vision 无嫌疑——与 I10 判决互证）

**③ 静态路径 t4 ×5 对照（授权临时拉桶，量完即拆）**
静态桶（chip 5 错峰 spawn + 单芯 v3 认养）：**5/5 全过**（120/125/404/134/135 步；trial2 挣扎但成功）。
**判决：静态 5/5 vs gear 3/5——回退桶编码的数值差异真实且行为相关**（t4 是刀锋任务，~1% 互差足以翻转 40% 成功率）；不是摆设，但也不是终态——终态 = 把 dyn-vs-static 互差收敛到噪声级。

## 五、终态与下一战役

**终态**：单芯（chip 4）gear serve ×1 + eval 宿主复用；无回退（v3 supervisor 不常驻，OM/spawn 工具全在盘上分钟级可拉）；spatial t4 在 gear 上暂态 ~60%（已知、已记录、未修复）。

**下一战役（正向解，工具全就位）**：
1. 录制 t4 真实帧 golden（L=151 主档，golden_gen 工具链 + t4 prompt）——真数据逐层账本
2. 逐层 **dyn-vs-static 互差**（不只 vs golden）定位互差集中层/算子
3. 根因候选：动态 OM 构建的 tiling/fusion 决策（+14ms 慢提示 dyn 图编译确实不同）——钉死 tiling/fusion 对齐静态，目标互差 ~1% → <0.3%（≈代际噪声地板）
4. t4 ×5 gear 复验 ≥ 静态 → 回退桶真退役 + **白捡 ~14ms/调用**（dyn prefix 对齐静态 tiling）

## 工具与产物（均已提交 probe_dyn/）

`ab_dyn_static_1015.py`（确定性 payload A/B，已证不可用于真实分歧但保留作混沌地板参照）、`ab_golden_dyn_static_1015.sh`（golden 逐层 bisect 双跑）、`val_spatial_t4_gear_1015.sh` / `val_spatial_t4_static_1015.sh`（×5 验证对）、`serve_gear_supervisor.sh`（单芯版）、`fleet_watch.sh`（GEAR_CHIPS 参数化 + 回退段自适应）、`spot_eval.sh`（CHIP=4）。
服务器产物：`serve_gear/val_spatial_t4_{gear_nofb,static5}.jsonl`（3/5 vs 5/5 双证）、`dbg` 系列遗留无害。
