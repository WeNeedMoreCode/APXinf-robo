# Python 宿主 GE 存活障碍攻坚：死因链定位 + 死亡点推进到 open 尾后 SEGV

日期：2026-09-24（凌晨 23:37-02:15，接 handoff 优先级 A；2:30 时限收档）

## 一句话

**三步判决实验把"python 宿主内 GE 杀进程"从黑盒推进到精确机制链：① 不调 `aclgrphBuildInitialize` → 进程不死（构图 panic 证明构图依赖 FE init）；② GE 源码定罪链 = init → `TbeInitialize` → `PythonAdapterManager`，其中 **forkserver 并行编译**是 open 中途静默死亡的必要条件；③ `MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile` 关掉 forkserver 后 **open 三段全部完成**，死亡点推进到 open 返回前后的**显式 SEGV（RC=139，带 core dump，可 gdb）**。**

## 判决实验链（每步都是干净 A/B）

| # | 实验 | 结果 | 结论 |
|---|---|---|---|
| 1 | pyo3 cdylib 跳过 `ge_builder::init`（逃生门 `APXINF_GE_BUILD_INIT=1`，c883290） | 进程**不再被杀**，`geb_add_data 'patches'` panic（OperatorFactory 未就绪，C++ 侧"phantom input desc 0"防护拒绝） | 死因在 `aclgrphBuildInitialize` 内部；且**构图依赖 init**（Data/Operator 创建需要 FE adapter 注册表就绪） |
| 2 | init 恢复 + `MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile`（进程 env，te 侧直读） | **forkserver 完全不初始化**（无 8 连 "main process disappeared"）；open 三段全通（in[251] 构装 / styles 预计算 / 10 步 flow / GEB_SERVE_FAST master） | **并行编译 forkserver = 中途死亡的必要条件**；剩余死因独立存在 |
| 3 | 同 2 的运行尾声 | `open` 完成后 **SEGV + core dumped（RC=139）**——此前形态是中途静默死（strace 无信号） | 死亡点推到最后一公里（open 返回前后）；**core dump 可 gdb**，剩余嫌疑 = te 模块 import 注入宿主解释器 / HandleManager GIL 操作 / GE 内部收尾 |

## GE 源码机制链（本地开源仓 D:\compass\ge 逐文件核实）

```
aclgrphBuildInitialize（geb_init 无条件调）
  → FE OpStoreAdapterManager::Initialize（无条件，ops_store_info 来自 Configuration ini）
  → TbeOpStoreAdapter::InitializeTeFusion（无开关可跳过）
  → TbeInitialize（te_fusion.so, dlsym 进来）
      ├─ SignalManager::Initialize —— 只碰 SIGINT/QUIT/TERM（清 kernel temp dir），已排除
      ├─ PythonAdapterManager::Initialize：
      │    ├─ HandleManager（py_decouple.cc）：
      │    │    dlsym(RTLD_DEFAULT, "Py_Initialize") —— **python 宿主里命中宿主符号 → static path**
      │    │    → 操纵宿主解释器（TE_PyEval_SaveThread 释放 GIL、TE_Py_Finalize 等）
      │    │    （rust 宿主走 dynamic path：dlopen 独立 libpython，与宿主零交叉 —— spool 稳定的根源）
      │    ├─ InitPyModuleAndApiCall：**无条件** import te_fusion.fusion_manager/fusion_util/
      │    │    compile_task_manager + te.platform.cce_policy 四模块**进宿主解释器**
      │    └─ InitParallelCompilation：仅当 `!IsDisableUbFusion() || !IsDisableOpCompile()`
      │         → te_fusion.parallel_compilation.init_multi_process_env
      │         → multiprocessing forkserver 8 worker（= "main process disappeared" 报错源）
      │         首参数 = !IsPyEnvInitBeforeTbe()（宿主解释器复用标志，python 宿主恒 0=复用）
      └─ 开关：MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile（te_config_info.cc
         ParseCompileControlParams，env 直读非 init option）→ isParallelCompileInit_=false
```

**结构性认识**：构图需要 init 成功，init 成功 ⇒ te python 适配层必然激活（`InitPyModuleAndApiCall` 无条件）——"init 但完全不碰 python"在选项面上不存在（forkserver 除外）。python 宿主天然走 static path（宿主符号被 dlsym 命中），与 rust 宿主（dynamic path）行为分叉——这就是"同一 GeServe 代码纯 Rust 稳定、python 宿主死"的根源。

## 交付物

- **子模块 c883290**（fork/ascend-port 已推）：`ge_init_once` 默认跳过 init（inproc 快速失败可诊断，优于死进程）+ `APXINF_GE_BUILD_INIT=1` 逃生门；注释含完整死因链与战报指针
- **`syx_docs/dev_logs/pyo3_noinit.sh`**（服务器 /data/apxinf/pyo3_check/ 同步）：判决脚本（当前形态 = 逃生门 + forkserver 关闭；跑 3 连）
- 服务器 pyo3_check 目录：新 cdylib（no-init 默认）已部署

## 下一步（按性价比排序）

1. **gdb core dump**：容器 core pattern 确认落点，`gdb python3 core` 看栈——最后一公里的直接证据（te import 注入 vs GIL vs GE 收尾，一栈定罪）
2. **若 te import 注入是根因**：尝试让 `te_fusion` 包 import 失败（PYTHONPATH 屏蔽）——但 init 会整体失败（构图又需要 init），死结；真正的出路在工程形态：
3. **构图/python 宿主剥离**（工程方向，下轮主候选）：
   - a. inproc worker 子进程化：multiprocessing fork 一个 worker 做 init+构图+open，主进程 pipe 通信（语义 = spool 的进程隔离 + pipe 传输，免文件轮询 ~15ms）
   - b. binds 与构图解耦：`geb_model_load` 已 CacheIo（OM introspection 有 IO size/dims）——load-only 模式跳过构图、binds 从 OM introspection 来，则 init 整个不需要（no-init 路径已验证不死）
4. **华为渠道**：素材已齐（复现器 + 机制链 + core），可精确提问"GE aclgrphBuildInitialize 在 python 宿主（libpython 已加载）内的 te fusion static path 支持性"

## 顺带事实

- 服务器收工状态保持：无引擎活体、pyo3 实验进程全部退出（SEGV 退出码可见）
- 9.0.1 容器 python3.12 环境：dlsym(RTLD_DEFAULT) 命中宿主符号成立（判决 1 的 panic 形态侧面证实——C++ 侧防护逻辑走到了 static path 分支的行为）
