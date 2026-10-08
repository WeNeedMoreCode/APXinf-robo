# Handoff（2026-10-09 校准 v3 收官 → 下一轮压缩用）

## 状态一句话

**校准 v3 全验收达成（2026-10-09 凌晨，全数字见 summary/2026-10-09_calib-v3-multiframe-behavior-pass.md）**：多帧包络（40 帧真 env rollout，v2 是单帧）修复 flow int8 行为退化——per-matrix 量化误差 flow 2.3× 改善，**actions 10.1%→3.1%（P50 3.3%×32 帧 replay，<8% ✓）+ 全量 10/10（flow int8 开启，task0/1 双通过）+ per-call ≈232ms（flow int8 -5.4ms 回收）**。根因定罪：v2 单帧因子对 flow 激活分布错配（actions% 不预测行为，per-matrix sim 误差才是预测指标——入 memory）。量化侧（上轮全线收束）+ 行为面（本轮）双双闭环。上上轮（分解式 w8a8 出局）见 summary/2026-10-08_qbmv3-pertoken-template-wall.md。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**结论与入口，不保数字**（数字全在 summary/2026-10-09_calib-v3-multiframe-behavior-pass.md）——① 终局：多帧包络修复 flow int8 行为（10/10 + actions 3.1%）；施工链 = golden_gen_v3calib.py（40 帧 + per-step [10,C] 包络 + sim 采样）→ int8_factors_v3_sweep.py（离线 α×envelope 扫描，胜者 prefix=α0.5 / flow=late_α0.6）→ convert ×2 → bake_v3_fleet.sh（11 桶）→ mini_sup_i8_v3.sh（**当前 serve_i8 隔离根运行的就是 v3 位**）→ eval_v3_t0/all.sh；② 纪律新增：pgrep -f 自匹配自杀（字符类 `prob[e]` 规避，入 memory）；per-step s 不可行论证（权重静态耦合 + f16 值域）；③ 服务器状态：v3 supervisor + 全谱系 v3 桶热（隔离根）；**共享生产根未动（prefix v2 + flow f16 回滚位）——切换须用户决策**。丢弃：施工迭代过程——战报已全文记录。

## ② Post-compact 首句（贴到压缩后第一句）

**状态**（2026-10-09，见 summary/2026-10-09_calib-v3-multiframe-behavior-pass.md）：校准 v3 收官——**flow int8 行为修复 + 10/10 + actions 3.1%**，量化侧+行为面双闭环；serve_i8 隔离根现为 v3 位（prefix v3 多帧 + flow int8 v3 gud，全谱系桶热），生产根仍在回滚位。外层仓已推平（脚本 + 战报 + docs；引擎本轮零改动）。

**下轮 goal 建议（抄一项即可）**：
1. **v3 生产化切换**（用户决策项：生产 supervisor 僵尸 Sep 24 起未处置 + tl138-148 生产桶重烤 v3 + supervisor env 切换 + 切换后全量复验）——收益 = 生产流量吃到 flow int8 -5.4ms + 3.1% 精度
2. **task7 segfault 取证 + 149-156 扩桶**——py-spy 已装；spatial 谱系桶并入管理（⚠ 共享 supervisor 僵尸须用户决策，与 1 合并执行）
3. **spatial 泛化 v3**——golden_gen_v3calib.py 换 REPLAY 源扩录 spatial 帧后同法出因子（校准 v3 目前仅覆盖 libero_object 谱系）

**纪律**：手烤 OM 必带 fusion off env；qmd smooth = 1/s 乘法约定；int8 eval 用隔离根 serve_i8 + mini_sup_i8_v3.sh（**现为 v3 位**——回退 = kill v3 sup + 换回 mini_sup_i8.sh + f16 flow OM）；A/B 隔离 = 等价生产根（全谱系桶 + supervisor）；eval timeout ≥1800；杀进程先 supervisor 后 serve、pgrep -f 用字符类规避自匹配。

## ④ 性能优化方向清单（2026-10-09 更新）

现状锚点：**v3 位 per-call ≈232ms（model_seconds/replans 归一）= 376ms 基线的 0.62×**（prefix int8 v3 + flow int8 v3 gud + vision f16 C1 后）；直调口径上轮 225.1ms = 0.598×。量化侧（G 行）已终审收束、行为面（校准 v3）已闭环——**剩余杠杆全部在生产化/泛化面，无新算子面项**。

| # | 方向 | 状态/预期 | 备注 |
|---|---|---|---|
| A-F | 段间直连/inproc/vision glue/prefix int8/生产配套 | ✅ 均已落地（历史行从略，见 roadmap） | — |
| G | 量化侧新算子 | ✗ 全线收束（2026-10-08 双轮终审） | qmd per-token = 终点形态 |
| H | **flow int8 行为修复（校准 v3）** | ✅ **本轮收官：10/10 + actions 3.1% + -5.4ms 回收** | 待生产切换（用户决策） |
| I | 生产化余项 | v3 生产切换 / task7 取证 / 149-156 扩桶 / OM 懒加载 / spatial 泛化 | 全部非性能项 |

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-10-09_calib-v3-multiframe.txt（多帧包络修复 flow int8 行为：40 帧数据面 + 离线扫描 + 10/10）
