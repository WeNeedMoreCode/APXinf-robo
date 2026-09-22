# M3 闭环 LIBERO eval：管线打通 + 行为 0/10（RMSNorm fp32 对照进行中）

日期：2026-09-22（白班）　前置：[离线回放闭环](2026-09-22_m3-offline-replay-closed-loop.md)（160/160 帧对拍 rel 179-223%）

## 一句话

**闭环 eval 管线全链打通并全程无技术故障**（10 任务 × 104/104 replans，engine 0.315s/次与稳态 bench 自洽，分桶 OM/lazy bake/死桶守护全实战验证）——但**行为 0/10（全部 520 步打满）**，与离线 replay 的系统性 actions 偏差（rel 179-223%，abs 4-5 on |nact|max≈2.3）一致；torch 基线本身是 f16 模型（9/10），行为崩坏的主源嫌疑 = **Gemma RMSNorm 的 fp32 方差上浮差**（torch 在 f16 模型里仍 fp32 算方差，引擎 AddRmsNorm 全 f16——与 2026-09-21 step0 残差 bisect 定罪同源），因果对照实验（torch 去上浮跑 eval）进行中。

## 架构（GEB_E2E_SERVE 闭环）

```
apxinf_npu（eval 进程）                     apxinf_rust（常驻 serve）
  env（MuJoCo EGL）                          supervisor.sh（守护 + lazy bake）
  torch 前处理宿主（9/10 同码：               └ tl{L}/ ge_model_probe ×N
    _to_frame/preprocess/                        （单进程单桶：三段 OM 机械
    _preprocess_images/postprocess）                常驻，req/resp 文件轮询）
  非零前缀截真长 ids → 按帧挑桶 ──/data 共享──→  vision→prefix→flow→actions 前 7 列
```

- **为什么文件轮询不是 socket**：引擎二进制绑定 rust 容器 9.0.1 GE，eval 需要 npu 容器 torch/libero 栈，唯一公共传输 = /data 挂载。每请求开销 ~1.8MB 写 + 1ms 轮询（相对 0.315s 推理可忽略）
- **processor 输出恒 pad 200**（max_length padding，pad_token_id=0 + mask=0）——静态 OM 全可见 ≠ 被 mask，须**非零前缀截真长**（replay_filter 同式）；直接喂 pad 全可见会让 embedding[0] 投影进 attention（语义污染）
- **分桶机制实战**：token 真长随 state 离散化位数漂（引擎轨迹走出 140-148 谱系，比 torch 录制的 144-146 宽——actions 分岔 → 新状态 → 新位数）；每桶 prefix+flow OM ~4.4GB，lazy bake ~8 分钟/桶

## 工程战果（bring-up 五连坑，全取证修复）

| # | 坑 | 根因 | 修 |
|---|---|---|---|
| 1 | serve 进程被反复重启、双 engine 抢目录 | engine 启动清理删光 spool（含 supervisor 的 pid 判活依据 + 自己正写的 stdout.log——删打开中的文件 = 日志进黑洞） | 清理白名单化（只删 req_/resp_/.tmp/ready/shutdown） |
| 2 | eval 重启后请求全超时 | engine 的 last_seq 门限 vs python seq 回卷到 1 | 去门限（处理最小现存 req；单客户端串行下即正确序） |
| 3 | 桶全挤一颗芯 OOM | `c=$(next_chip)` 命令替换子 shell 内 ci 自增不回传 | 主 shell 自增 + cut 查表；SERVE_CHIPS 四芯轮转 |
| 4 | kill 后显存不释放、桶判活假阳 | kill -0 对 zombie 返回 0；docker exec 起的进程 PID 1 不收割 → fd 持有 NPU 显存 | alive() 读 /proc state 排 Z；僵尸积压时容器重启清零 |
| 5 | engine 间歇加载崩（aclmdlLoadFromMem rc=-3） | 并发启动风暴下资源瞬态 | supervisor 守护循环（死桶 60s 退避自动 respawn）+ python ensure/请求两级重试 |

另：`pkill -f` 自匹配两变种（命令行含目标字样；`[h]` 字符类的 `.` 还能匹配字面 `[`）——杀进程一律 pgrep 取 pid 再按数字 kill。

## 行为结果与证据链

- **0/10 全 520 步打满**（非"挂 1-2 个"的随机失败集——torch 各 replan 配置失败集 ≤2 且互不相同）。模式一致性指向系统性偏差
- 离线 replay 已证：**系统性** actions 偏差（160 帧紧簇 rel 179-223%，无离群 = 无集成 bug 形态；abs 4-5 on |nact|max≈2.3 ≈ 2 倍信号量级）
- **torch 基线 = f16 模型跑 9/10** ⇒ 差异不在"f16 模型"整体，而在执行语义细节；step0 残差 bisect（2026-09-21）已定罪唯一残余 = **RMSNorm fp32 方差上浮差**（PK_GOLD/STYLE_GOLD 两腿正交全洗清）
- **因果对照（norm_f16_probe.py，已定罪 ✅）**：monkey patch GemmaRMSNorm._norm 去 fp32 上浮（单变量）→ torch task0 **520 步打满失败**，与引擎 0/10 形态完全一致（原版 torch 143 步成功）。**RMSNorm fp32 方差上浮 = 行为成败开关，引擎修复方向对症**。修复路径：GE 图 AddRmsNorm fp32 化（Cast 包绕或算子 fp32 模式），先单算验证 dtype 支持 → tl144 单桶 A/B → replay rel 降幅判定 → 全桶复测 eval。注意 torch 侧尚有 softmax fp32 / ada-norm fp32 scale·shift 等混合点——RMSNorm 修掉后剩余残差实测再判。

## NORM32 修复进展（当晚续，修复方案已验证到 depth12）

**AddRmsNorm fp32 desc 假支持**（arm32 单算 f32/f16 输出逐位同——GE 自动 Cast 归一回 f16 kernel）→ 组合手搓 fp32 RMS（Cast→Mul 平方→ReduceSumD→RealDiv(w)→Sqrt→1-D TileD(w)→Reshape→Mul(γ)→Cast 回）。

**GE IR 五坑全定罪**（n32c 单算矩阵 + 逐 pass dump + ASCEND_SLOG_PRINT_TO_STDOUT 抓 ERROR——最后这个是破局工具）：
1. Cast.dst_type 是 DataType 类型 attr（int 猜枚举值 rc=-7）——ge_builder 追加 `geb_set_attr_dtype`（ParseDtype 同管道）
2. ReduceSumD 的 attr 名是 **"axes"** 不是 "axis"
3. TileD 直接吃 [rows,1] 输入会被 infershape 扁成 [1,rows*w]（[1,x] 输入域才可靠）
4. RealDiv 广播 [m,w]÷[m,1] kernel 拒（mul E80013 同族报错）
5. **g.link 只配 Data 名——连算子输出必须 g.wire**（自动分派 link/link_out；误用会让拓扑静默错乱，症状 = `GetInputDesc of node[x0] invalid index 1..6`，pass 停在 OptimizeSubgraph 前）

广播正解 = **1-D Tile 域 + 双 Reshape 桥**；eps 省略（真实方差 O(1)，1e-6 相对贡献可忽略）。

**当前卡点（放下一轮）**：depth 2/4/8/12 编译全通（拓扑/形状/算子全对），**depth 15/17/18 rc=-8**——规模相关（每处 norm +~12 节点，prefix 图几乎翻倍；rc=-8 疑编译资源/节点上限）。下一轮候选：精简节点（TileD×2/Reshape×2 可合并方案）、GE 编译内存参数、或按层拆 OM 接力（M2 期已验证多图接力）。**收益判定顺序不变**：烤 tl144n32 桶 → serve → replay 对拍 rel 降幅 → 显著降才全桶 + eval 复测。

## M3 记分卡（当前态）

| 项 | 状态 |
|---|---|
| 延迟验收线 | ✅ 310.3ms = 0.82×（summary 2026-09-21） |
| 离线回放闭环 | ✅ 160/160 帧，管线一致性（summary 2026-09-22 凌晨） |
| 闭环 eval 管线 | ✅ 全程无技术故障（本轮） |
| **闭环成功率** | ❌ **0/10 vs 基线 9/10**——根因定罪 RMSNorm fp32（norm16 对照）；NORM32 修复 depth12 已通，全深度 rc=-8 下一轮 |


## 工具

- 服务器 `/data/apxinf/serve/`：supervisor.sh（SERVE_CHIPS="6 4 7 5" nohup 起在 rust 容器）、run_ge_eval.sh `<tasks> <tag>`（npu 容器）、norm_f16_probe.py、smoke.py、parse_eval.py
- OM 桶：`/data/apxinf/om_cache/tl{138..148}`（十桶，L 谱系随轨迹扩张按需补）
- 本地镜像：`syx_docs/dev_logs/{serve_supervisor,run_ge_eval,norm_f16_probe,serve_smoke,parse_eval}.*`
