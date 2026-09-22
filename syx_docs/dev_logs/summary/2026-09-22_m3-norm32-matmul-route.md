# M3 NORM32 v2：mm 立方体累加路线（rc=-8 销案 + 三个隐藏 bug 定罪）

日期：2026-09-22 晚（接 summary/2026-09-22_m3-closed-loop-eval.md）

## 起点

上轮遗留：NORM32（fp32 方差组合图）depth12 编译通、15/17/18 层"rc=-8 疑编译规模上限"。本轮第一动作攻 rc=-8。

## 结论速览

1. **rc=-8 销案：从来不是编译上限**。stdout 取证（`ASCEND_SLOG_PRINT_TO_STDOUT=1`）显示 depth15 图编译 + task 生成全部成功（`prefix OM built: depth=15`）——真凶是**旧代码 eager 参考构建 panic**（binds 索引错位，陷阱 #29 族，`fp16_nd([576,2048])` 拿到 4 字节 n32 标量 buffer）被误读为编译失败。且**服务器代码滞后于本地**（md5 不一致，早退守卫不在服务器副本上）——上轮 depth 二分的结论全部来自旧二进制。修复后 prefix/flow **depth18 全深度编译+落盘一次通过**。
2. **三个隐藏 bug 被 n32v 数值 tap 矩阵连环定罪**（NORM32 下 parity 跳过、此前只验证过编译——数值验证缺失是教训）：
   - **Sqrt 漏倒数**：rms32 算的是 `x·rms(x)·γ`（注释写了 inv=one/rt 但代码没落图）→ 换 **Rsqrt** 直出倒数（310P opp 有预编译 kernel）
   - **ReduceSumD/ReduceSum f32 假支持**：opp 注册表 json 有 d=1(fp32) key，但 f32 desc 的图被 FE 混精度回退跑 f16 kernel——行和 >65504 **饱和**（t4/t7 实测输出 ≈65504 ≈ host 的 8%）；Cast 的 f32 倒是真语义（f16→f32 直出逐位）。与 AddRmsNorm 假 f32（arm32 案）同族——**310P tbe 的 f32 元素/归约算子大面积假支持**
   - **TileD 连续平铺方向 kernel 腐蚀**：rank-1 `[rows]+multiples=[w]` 与 `[1,rows]+multiples=[1,w]`（flat 连续重复）两种形态**逐位同错 ~8% 散点腐蚀**（编译/执行零报错）；dim0 整行复制方向（生产 bias/γ 链形态）干净
3. **rms32 v2 定稿（全 f16 域 + MatMul 立方体 fp32 累加）**：
   `xs=x·s（s=1/32，防 outlier 平方溢出）→ sq=xs² → ssum=mm(sq, onesᵀ [1,w] Const) → inv=rsqrt(ssum)·k（k=s·√w 折回）→ [1,rows]→TileD[multiples=w,1]→TransposeD(1,0) 广播 → x·invb·γ`
   方差精度走 cube 的 fp32 累加（单点实测 0.05% = f16 量化级），全程 f16 kernel、零 Cast/零 Reduce/零 RealDiv；常量全部 Const 折叠（**不再有 n32 Data 输入**——标量池/死输入/binds[0] 约束连根拔掉，prep_n32 删除）。**n32v 全链 0.13%**。
4. **工具**：`GEB_OPTEST=n32v`（须配 GEB_NORM32=1）——14 级 tap 矩阵一次跑全（t1 Cast 对/t3 全链/t4-t7 归约死路档案/t8 mm 路线/t9 Cast 直出/t10-t14 广播二分），逐级 host fp32 参考 + argmax 定位。这是"只验证编译"教训的直接产物。
5. **GEB_SAVE 修复**：NORM32 早退分支原先跳过 save（烤桶依赖）——现在早退分支内落盘。
6. **scope 裁决（上轮遗留数据翻出）**：`eval_norm16_expert_t0`（torch 只 patch expert）task0 **成功 57 calls**；`eval_norm16_t0`（language/both）task0 **失败 104 打满** ⇒ **行为开关在 language/prefix 侧 GemmaRMSNorm fp32**，expert 侧无关。NORM32 恰好已改 prefix。
7. **replay rel 不降**：tl144n32 vs replay_t0_L144 = **rel P50 193.6%**（对照非 NORM32 的 194%）——与 step0 残差 bisect 自洽（残余由 mm 累加序差等 12% 级源主导，10 步 flow 混沌放大后 ~190% 饱和平台，该指标对 norm 语义修复失去分辨力）。**行为终审 = task0 闭环 eval**（进行中）。

## 服务系统增补

- `bake_one_n32.sh`（replay/）：NORM32 版烤桶（GEB_NORM32=1 → tl<L>n32）
- `supervisor_n32.sh`（serve/）：supervisor 的 n32 变体（bake/OM 目录/env 三处 n32 化，spool 与控制接口复用——python 客户端无感知）；`SERVE_CHIPS="6 4 7 5" nohup` 起在 rust 容器
- tl144n32 三件套已烤（prefix 3.76G / flow 629M / vision=t712fix 复制）；NORM32 引擎轨迹 lazy bake 实测自动烤新 L 桶

## 记分卡

| 项 | 结果 |
|---|---|
| rc=-8 | 销案（伪编译上限，实为旧代码 panic + 服务器代码滞后） |
| NORM32 depth18 编译+落盘 | prefix/flow 全通（n_in=138/216） |
| n32v 单点数值 | 全链 0.13%（t8 mm 0.05% / t14 广播桥 0.08%） |
| replay rel | 193.6%（不降；指标饱和，判读见上） |
| task0 闭环（NORM32） | **失败：520 步打满（replans=104）——NORM32 不修复行为**（eval_n32t0_summary.json，2026-09-22 15:44 UTC） |

## task0 判决与"原理性天花板"假说

NORM32 v2（fp32 方差语义对齐，单点 0.13%）跑 task0 闭环仍 520 打满。三层证据合流的解读：

1. **段级偏差守恒**：v2 把"f16 方差的系统性偏差"换成"f16 乘法舍入的随机偏差"——单点 0.13% × 37 处 norm 复合 ≈ 0.5-1% 段级，与修复前的 0.8% 同量级。修复改变了偏差的**性质**（对齐了 torch 的 norm 语义）但没降段级**总量**。
2. **行为敏感度阈值 < 0.1-1% 量级**：norm16 对照（torch 单变量 f16 方差 → task0 崩）+ torch 自身 replan=1 实验（噪声重采样 → 8/10）共同说明成败边缘的任务对这个量级扰动敏感。
3. **其余偏差源是分布性的**：mm cube 累加序 vs torch 累加序、attention/MLP 的 tiling 变体差（replay rel 194% 的主导源，step0 残差 12% 级）——不是单点可修，是 fp16 执行的实现分布。

**推论：闭环行为对标 torch（≥9/10−1pp）可能存在原理性天花板**——除非引擎输出对 torch 逼近到远低于任务扰动敏感度的程度（近 bit-exact），而静态 OM 的 fp16 执行序差永远存在。

**候选出路**（待用户决策）：
- A. **接受天花板**：M3 行为口径改为"误差量化 + 扰动敏感性分析"（延迟口径已达标 0.82×）；文档收口 M3
- B. **近 bit-exact 冲刺**：AscendC 自研 fused fp32 RMS kernel（f16 in → f32 全内积 → f16 out，单 kernel 唯一舍入点，把 norm 段级压到 ~0.1%）+ 其余源的逐项压缩——工作量大且 mm 累加序等源未必可压到敏感度以下
- C. **混合形态**：关键精度敏感段（norm/flow）留 torch_npu，引擎接管大 matmul（零调度税收益保留）——偏离"原生引擎"目标但保行为

## 陷阱回填

ge-offline-om skill：#35 修法修正（1-D Tile 桥有腐蚀，指向 #39）、#37 修订（rc=-8 定案）、#38 新增（f32 归约假支持 + mm cube 累加替代）、#39 新增（TileD 连续平铺腐蚀 + dim0/TransposeD 桥）。

## 验证梯次序（本轮教训固化）

单点数值（n32v，分钟）→ 组件 golden → **段级 golden 对拍（GEB_E2E_GOLDEN prefix 级，分钟——本轮漏了这档）** → 单任务 eval（~25 分钟）→ 全桶（小时级）。选档时算**总时长**（含 bake/加载等待），不是单步标称耗时。
