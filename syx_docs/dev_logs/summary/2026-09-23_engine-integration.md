# 引擎接入主线：执行器库化 + PyO3 面 + engine.py inproc 传输

日期：2026-09-23（接 handoff 主线"引擎正式接入 apxinf-robo 主路径"；含全量 fast 回归收口）

## 一句话

**三步接入落地：① 三段执行器从 example 沉到 crate 库面（`src/pi05/ascend_ge.rs` + `GeServe` 进程内门面，验证梯全过——golden 0.0%/0.9% 与基线逐字同、新旧二进制冒烟 bit 恒等）；② PyO3 `GeServeModel` 绑定（rust 容器 python 直调三段全通，python 宿主内 GE 库存活为已知障碍）；③ engine.py npu-ge 加 `APXINF_GE_TRANSPORT=inproc` 分支（失败自动回落 spool）。顺带全量 10 任务 fast 回归锁定：success 10/10 + per-call model_ms P50 256.3ms = 376 基线 0.682×。**

## 全量 fast 回归终数（gatefastall，此前只 task0 单测）

| | success | per-call model_ms P50 | = 376 基线 |
|---|---|---|---|
| eval_gateall（legacy serve） | 10/10 | 325.3ms | 0.87× |
| **eval_gatefastall（GEB_SERVE_FAST）** | **10/10** | **256.3ms**（min 254.5 / max 260.5，跨任务极稳） | **0.682×** |

10 任务 119-165 步全健康；与 task0 单测 254.3 自洽——**0.68× 全量口径坐实，④A+B 收口**。

## ① 执行器库化（子模块 e7e4cd1）

- `git mv examples/ge_model_probe.rs → src/pi05/ascend_ge.rs`（6206 行整体下沉，git 识别 rename，逐条 pub 化走 Edit）
- **新增 `GeServe` 门面**：`open(be, real, om_dir, tokens, fast)`（走 seg_vision/prefix/flow 完整构装 = 与探针 bring-up 同路径，含首帧 warmup + styles 预计算）+ `infer(be, patches, ids, noise) -> GeServeOut`；**serve_loop 帧体改为调 `pipe.infer`**——spool 与进程内直调共用同一帧实现
- open 钉死拓扑 env（四件套 + PREFIX_DROP_EMPTY=256 + LAYER_OFFSET=0）；**⚠ GEB_DEPTH 不能钉**（分段默认 vision=27/prefix=18/flow=18，全局钉 18 会把 vision 砍成 18 层 → Seg n_in 187 ≠ OM 277，首跑教训）
- example 变薄壳（env 分发 + GEB_CKPT 加载，~40 行）；optest 留库作调试面

### 验证梯执行记录

1. `cargo check/build --features ascend` 一次过（独立 target 目录，不碰生产二进制）
2. golden 对拍（tl200——**flow gate 版重烤**后，新二进制烤，顺验建图+eager parity 0.1%）：**step0_x1 0.0% / actions 0.9%**，与 M3 收官基线逐字一致
3. 冒烟 A/B（tl144 同 OM 同帧）：新二进制 max_diff=0.0244/rel=1.0% 与旧二进制**四位小数全同**（bit 恒等），稳态 254.6-255.9ms
4. 全量回归已由 gatefastall 覆盖（改动前基线）+ 改动后 task0 复测（见下）

## ② PyO3 面（子模块 787730a）

- `apxinf-py --features ascend` 新 `GeServeModel`：`open(om_dir, tokens, ckpt, fast)` + `infer(patches[768,588] f32, ids, noise) -> (actions[50,7] f32, (vision/prefix/flow ms))`——**与 spool 协议逐位对齐**（f32→f16 转换同款、前 7 列切片同款）；`ge_builder::init` OnceLock 守护；直接依赖 apxinf-ascend 接入 feature
- rust 容器 python 直调实测：import ✓ → 三段 OM 全通（n_in 277/138/252 匹配）→ styles 驻留构装 ✓ → **open 尾声进程死亡**
- **已知障碍（未解，记录）**：GE 库在 **python 宿主进程**内于 fmech 构装后杀死进程——无 SIGSEGV/SIGABRT（strace 信号级验证）、无 python Traceback，伴随 TBE 子进程 8 连 "main process disappeared"（GE 的 python 编译子进程，forkserver 模式），死亡点位非确定（run2 flow 尾 / run3 prefix 尾 / run4 flow 尾）。**同一 GeServe 代码在纯 Rust 宿主稳定**（冒烟/烤桶/golden 全过）。疑 GE 的 TBE 子进程生命周期管理与 python 宿主 multiprocessing 相克（华为库内部行为）。绕行候选（未试）：TBE 禁用类 init 选项、GE 侧 exec_pythonPath 指向受控 python、或华为侧咨询
- 附带实况：**9.0.1 toolkit 在 rust 容器镜像层**（docker inspect：非宿主挂载）→ npu 容器想供 cdylib 用须拷贝 libs（部署项，未做）

## ③ engine.py inproc 传输（外层仓）

`npu_ge.py`：`APXINF_GE_TRANSPORT=inproc|spool`（默认 spool）——`_InprocClient`（PyO3 直调，request 签名/字节兼容）+ `_make_client` 工厂（**import/open 失败自动回落 spool 桶**，npu 容器 torch_npu 8.5.1 与 9.0.1 同进程互斥的现状下 eval 不受影响）。`APXINF_GE_OM_ROOT` 可配 OM 桶根。

## 接入形态总结（goal 判据）

```
engine.py (engine="npu-ge")  ←── 阶段 3 起已在主路径（eval_gateall/fastall 10/10 都走它）
  └─ GeServePi05Policy
       ├─ spool（默认生产）：supervisor 桶进程 → ge_model_probe 二进制 → crate 库面 GeServe（=①）
       └─ inproc（可选）：_InprocClient → PyO3 GeServeModel → crate 库面 GeServe（=②③）
```
引擎执行代码**单一实现在 crate**（example/PyO3/spool 三入口同源）——"接入"从脚手架形态（探针 example + 文件轮询独占）升级为库面 + 多入口。

## 运维新坑（本轮新增）

- **`set -u` + `source rust_env.sh` 会炸**（引用未定义变量）——脚本别用 set -u，或 source 前关
- **bash `export` 不接受带点变量名**（`GEB_INIT_OPT_ge.fusionSwitchFile`）——须 `env "NAME=..." cmd` 前缀式
- **ready mtime 竞态第二形态**：`_ensure_ready` 两轮各取新 mark，touch 早于第二轮 mark → 恒判 stale 卡满 timeout；**touch 必须在客户端启动之后**
- cdylib 部署名：cargo 产物 `libapxinf_py.so`，python import 需 `cp` 成 `apxinf_py.so`
- `docker exec -d` 的 stdout 丢弃——脚本必须自己重定向落盘（两次白跑教训）
- 独立 target 目录（CARGO_TARGET_DIR=/data/apxinf/target_libcheck）：eval 期间可安全并行编译不污染生产二进制

## 遗留

- python 宿主内 GE 存活障碍（②的最后一公里，见上）——后续：TBE 禁用选项研究 / 华为渠道
- npu 容器 9.0.1 libs 供给（拷贝 toolkit lib64 到 /data + LD_LIBRARY_PATH）+ torch_npu 剥离（前处理 CPU 化）→ eval 全链 inproc
- ④ 动态 L 定形仍为预置桶集（tl138-148 已备 + tl200 补齐 gate 版）；padding+mask / shape_range 后置
- 性能余项顺路：E msprof vision 65ms 回归源、D int8 单算 probe
