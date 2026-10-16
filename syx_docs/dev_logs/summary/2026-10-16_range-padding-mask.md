# 2026-10-16 Range padding + mask 化：桶粗化 26→9（表外 L 根除）

handoff goal #1（用户拍板）执行闭环。动机：精确分桶是对观测 L 全集的过拟合
（L=136 事故类），正解 = bucketed padding——桶取 stride-8 网格，请求向上
取整 pad 到桶界，pad 键列由 softmax 加性 mask 遮蔽。

## 一、引擎改动（apxinf/ 子模块，fork/ascend-port 98e5362）

1. **GEB_ATTN_MASK=1**：attn_manual_gqa 的 softmax 前加广播 Add
   （scores [bh,sq,skv] + mask [1,1,skv]——pad 键列 −30000，真列 0）。
   prefix mask [1,1,p]、flow mask [1,1,p+HOR]（键布局 = cache 行在前
   [真|pad] + flow HOR 行恒真）。全层共用一只 padmask Data 输入。
2. **GEB_POOL_GRID=8**（+MIN 136/MAX 200）：`pool_grid_p()` L→桶界 P，
   **引擎侧实现，客户端零改动**——PrefixMech token 补 0（embedding[0]）
   + mask 随 token 变化填；FlowMech **OM 按桶界换柄、rope 按真 L 换装**
   （flow 位置 = vis+真L+i 与 P 无关）。
3. cmp_mid 截断比前缀（桶版 OM 出 P 行、golden 真 L 行——真行恰为前缀）；
   GEB_E2E_PAD_TOKENS = probe A/B 支持。
4. **修了颗老地雷**：names/binds 在 WCONST 下不对齐（wt Const 分支与 i8
   占位槽只 push binds）——bind_of 按名查 names 是错位索引（c1/c2 事故：
   3200B 灌进 4MB 权重 bind）。新增 bind_names 与 binds 严格平行（11/11
   push 点），bind_of 改查它。

## 二、数值验收（t4 真帧 golden，L=154 → 桶 160，④）

| 口径 | 数值 | 判读 |
|---|---|---|
| l0 kvk/kvv vs torch | **0.9/0.8%（与 static 逐位同 argmax）** | mask 数学精确首层实证 |
| l1/l2 mutual vs static | 0.7%/1.3% | ulp 级种子（softmax 归约树宽度 672 vs 666） |
| l17 mutual vs static | 12.8/13.0% | int8 链混沌放大（同 static-vs-torch 18% 机制） |
| **actions vs torch** | **3.7%**（static 4.3%） | 落在 static 漂移带内 |
| **actions mutual vs static** | **3.8%** | 等效量级新数值个性，非语义错误 |

数学依据：mask 精确（x+0 恒等、exp(−30000+max) 下溢恰 0、加零不改浮点
和）→ 真行输出数学上与精确 L 版等价；实测 l0 bit 级一致、深层 ulp 放大
与既有漂移带同量级。按消融结论属「静态图内可控改动，GE 等价编译」。

## 三、生产切换与行为验收（⑤）

- 基线 spot（切换前，①）：object:0/spatial:4/goal:9 = **3/3**
  （139/118/121 步）——133-136 补烤档随 goal 谱系 lazy load 验证 ✓
- **意外发现**：L 在局内也漂移——基线 serve 日志 goal:9 一局连载
  137/138/139/140 四只、object:0 载 142/143（此前「局内恒定」仅 t4 成立：
  其状态位数恰好稳定）。**range 模式这些 L 全落 144 桶，局内零额外装载**
  （精确桶模式下每次 2.7s）；LRU cap8 焦虑随九桶全驻留消失
- 切换：start_gear_supervisor.sh → serve_range_supervisor.sh（grid8 九桶 +
  GEB_POOL_GRID/ATTN_MASK env；回滚 = 改回 serve_gear_supervisor.sh，
  26 只 tl{L}_i8 留档未删）
- **t4 ×5 = 5/5**（116/127/121/128/127 步，无挣扎；pool 时代同款），
  **全程仅 1 次 lazy load（154-157 → 160 桶一装到底）**——局内 L 漂移
  归一的直接实证
- 三谱系 spot 复验：**3/3**（object/spatial/goal 各 success_rate=1.0，
  与切换前基线完全对照）；grid 桶按谱系落位（object 152/goal 144/
  spatial 160）

## 三b、切换当日踩坑追加（serve 侧三连）

1. **fill_mask 等长断言崩**：按桶长写 722 行撞 copy_h2d 等长断言（bind
   按 max 762 物化）——改全长度填充（本桶 flow 行 0、pad 及以远 −30000、
   本桶外未读区无害）。send_gear_req.py 合成请求最小复现定位（154→160/
   137→144/200 三发验证全中）
2. **supervisor 死亡循环**：连续三代 serve ~3min 静默死（无 panic）——
   TBE 孤儿进程链式毒害重启风暴（10-12 重启风暴同款现象）；pkill 清场
   耐心重发即愈。前台直跑同 env 全绿，证明二进制/OM 无罪
3. fg 复现时客户端握手需 spool ready 文件（supervisor 平时负责 touch）

## 四、收益与税

- 表外 L 根除（任意 L≤200 有归属，L=136 事故类连根拔）
- 桶 26→9：磁盘 49→17GB；局内 L 漂移零装载；LRU 焦虑消失
- 税：+0.6% prefix ≈ +0.5ms/replan（14ms 红利的 1/28）+ 每层一个 Add
  （GE 融合吸收，实测 prefix 时长待 spot 对账）

## 五、踩坑（全在当日实证）

1. `local a=$1 b=x_$a` 单行多赋值 $a 取外层空值（消融轮已知，本轮脚本
   逐行写规避）
2. c1/c2「binds 尾两位」位置式假设被 padmask 追加打破 → 按名定位 →
   踩 names/binds 不对齐地雷 → bind_names 根治（三连修）
3. probe 路径两处 PAD 缺口：golden-load 断言、flow rope 相位（须按真 L）
   + flow padmask 填充——serve 路径无此三坑（fill_mask 一直在）

## 六、遗留

- 精确桶 26 只（om_cache/tl{L}_i8）+ grid8 九桶并存（~66GB）——观察
  一两天稳定后可清精确桶（回滚保险期）
- supervisor 启动偶发慢（~8min 到 ready）与 TBE 孤儿死亡循环的根因
  （10-12 重启风暴同款）未深挖——清场重发即愈的 workaround 已入战报
- 局内 L 漂移的成因细节（状态离散化逐步进 prompt）未深挖——range 模式
  下已无运维后果
