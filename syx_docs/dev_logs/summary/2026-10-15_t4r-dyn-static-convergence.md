# 2026-10-15 深夜 T4R 战役：dyn-vs-static 收敛（根因定位 + 池化修复 + t4 复验）

handoff 菜单 #1 执行闭环。三段：真帧取证 → 根因证伪链 → GEB_PREFIX_POOL 修复。

## 一、真帧 golden + 互差三连（①②）

工具链（probe_dyn/，全部入库）：
- `golden_gen_t4_1015.py`：spatial task4（0 基）trial0 init_state[0]、seed 7、
  10 步 settle 与 run_episode 同源 → pol.infer 全 hook 捕获
- `golden_fix_t4_1015.py`：**剥 pad 重放**——processor 恒 pad 到 200（pad_id=0
  尾置），生产客户端是「截非零前缀」（npu_ge._frame_inputs 同式）→ **t4 真长
  L=154**（Pv=666），10 步 euler 出 actions 参考
- `ab_t4_mutual_1015.sh` + `mk_merged_golden_t4_1015.py`：static dump kv/actions
  → 合并进 golden → dyn 跑时 cmp_mid 即逐层互差（GEB_E2E_DUMP_MID 扩展：
  36 路 kv + ge_actions.f16，引擎侧两 commit）

**判决表（真帧 frame0_t4v1b，L=154）**：

| 口径 | kvk 范围 | kvv 范围 | actions |
|---|---|---|---|
| static vs torch | 0.9-18.4% | 0.8-22.8% | **4.3%** |
| dyn vs torch | 1.6-58.3% | 2.2-69.8% | **12.8%** |
| **dyn vs static（互差）** | 1.7-54.9% | 2.1-69.1% | **13.1%** |

- x0_vis 两路逐位同（0.1% 同 idx）——分岔不在输入
- l0 互差 1.7/2.1% → l2 kvv 55.9% 爆炸 → 随层加深 l17 最差
- **dyVsT ≈ dyVsS 逐层几乎相同：dyn 的漂移 = 互差本身；「彼此等距近似」
  （昨日合成帧结论）在真帧上证伪**——dyn 是更差的近似（3×）

## 二、根因证伪链（③前半）

- **E1（2 档对照）**：现烤 tl_dyn_g154（LLIST=154,200 单值档表）跑同帧——
  l0 1.6/2.2%（与 26 档持平）、l2 kvv 80.8%、actions 17.8%
  → **range-tiling 假设证伪：分歧与档表宽度无关**
- 结论：**动态图结构本身**（-1 维 Reshape / rope·qswap Data 化 / bias 折叠
  差异）改变算子序列与融合机会 → int8 累加次序不同 → ~2% 首层漂移经 18 层
  int8 链放大到 13% actions。GE 编译器黑盒内不可控
- 副产物：GE 单档 dynamicDims 烤不出（rc=-7，≥2 档才行）

## 三、修复 = GEB_PREFIX_POOL（③后半，4 commit）

**设计**：把 flow 池的 per-L 静态模式推广到 prefix 段——单进程单芯保留 gear
全部运维收益，数值/性能直接继承静态桶（t4 5/5 + 白捡 dyn 慢的 13-16ms）。

引擎（apxinf/ 子模块，ascend_ge.rs）：
1. `834cb7b` dump 仪表：GEB_E2E_DUMP_MID 落全部 36 路 kv + ge_actions.f16
2. `6579dbf`+`53d6dfd` probe e2e 的 gear kv 下载修（cur_output_dims +
   host 截断——copy_d2h 整缓冲契约）
3. `9f94cee` **池本体**：PrefixMech 增 pool_graphs/lru/cap8（单只 OM 1.88GB）；
   swap_prefix 换柄执行；routs/binds max 物化全 L 共用（无跨请求状态）；
   download_kv 整缓冲 d2h 后截 OM 声明行数
4. `2c48e2b`+L-check：**gear_mode() 在 POOL env 下压 false**（gear 折叠
   rows==1 bias 少注册 90 个 Data → n_in 170≠260 实证）；set_rope_for 早退门
   改按 flows 池判（HYBRID rope 换装保持）；serve 请求环 L 校验池模式豁免

接线（serve_gear_supervisor.sh）：`GEB_OM_DIR=$OM/tl200_i8`（max 档静态
prefix 做 warmup/预载句柄）+ `GEB_PREFIX_POOL=$OM`；**去掉 GEB_CKPT_SERVE_MIN**
（静态桶 OM 是 260 Data 输入=权重 Data 化，占位权重只够 170 bind）。

**踩坑记录**（全在当晚实证）：run_gear 对静态 OM ≡ run 但 n_in 严格校验；
GE 单档烤不出；ckpt serve_min 与静态桶不兼容；stdout.log 含二进制要 tr -d。

## 四、t4 ×5 复验（④）

val_spatial_t4_pool.jsonl（seed 7，与 gear 3/5、static 5/5 同口径）：
**5/5 全过**（120/124/116/130/127 步，VAL_RC=0；trial0/trial4 = gear 时代的
两个失败 trial，池模式下干净通过——无一步挣扎，static 时代 trial2 挣扎 404
步、池模式最差 137；不同 trial 不同 L（154-157）池 lazy load 按需装载验证 ✓）

**回退桶真退役定案**：数值证据（4.3% 静态漂移 + 行为 5/5）+ 运维面（单进程
单芯、无 supervisor 档表依赖）双达标。

## 五、遗留

- 133-136 档当晚已补烤（/tmp/bake_static.sh，chip5，fg4 同配方=260 接口）——
  下轮跑 goal 谱系前 fleet_watch + spot 验证
- 池 LRU cap=8 未压测（全谱系 eval 若同 run 撞 >8 个 L 会驱逐重载——
  观察 spot 三谱系）
- dyn prefix OM（tl_dyn 1.89GB）保留在 om_cache 作回滚路径，未删；
  tl_dyn_g154（E1 实验桶）2GB 同留档
- 性能红利（~13-16ms/调用）未单独计时验证——下轮 spot_eval 看 model_ms
