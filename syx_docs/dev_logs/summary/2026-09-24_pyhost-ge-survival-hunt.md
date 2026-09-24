# Python 宿主 GE 存活障碍攻坚：GIL 劫持根因定罪 + 修复终结（✅ 已解）

日期：2026-09-24（凌晨 23:37-02:15 定位链；上午 10:30-11:00 gdb 定罪 + 修复终结）

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

- **子模块 c883290 + 2dbffe9**（fork/ascend-port 已推）：c883290 判决实验版（no-init 默认）→ 2dbffe9 终局版（allow_threads GIL 修复 + forkserver-off 默认 + `APXINF_GE_NO_BUILD_INIT=1` 逃生门）
- **`syx_docs/dev_logs/pyo3_noinit.sh` / `pyo3_segv_diag.sh` / `pyo3_segv_gdb.sh` / `pyo3_stability.sh`**（服务器 /data/apxinf/pyo3_check/ 同步）：判决/定罪/稳定复验脚本链
- 服务器 pyo3_check 目录：修复版 cdylib 已部署

## 下一步（按性价比排序）

~~1. gdb core dump 定剩余死因~~ **✅ 已做（同日上午）——见下"终局"节，GIL 劫持定罪 + 修复终结，A2 剥离工程不再需要**。剩余真实下一步 = **A3 eval 全链 inproc**（9.0.1 libs 拷 /data 供 npu 容器 + torch_npu 剥离=前处理 CPU 化）+ B 动态 L + C 性能余项，见 handoff。

## 终局（同日上午 10:30-11:00）：gdb 一栈定罪 + 两行修复

**core dump 实为空**（容器 core_pattern 走 apport 管道、容器内无 apport → core 从未落盘；"core dumped" 只是 shell 措辞）——改用 **gdb --batch live 跑**（openEuler dnf 装 gdb）。faulthandler 先证 python 主栈停在 `check.py:23`（PyO3 open 帧内），gdb 抓到全栈：

```
#0  get_state () at Objects/obmalloc.c:866        ← CPython pymalloc 内部
#1  _PyObject_Malloc (nbytes=1320)
#3  PyType_GenericAlloc
#4  pyo3 PyNativeTypeInitializer::into_new_object   ← 创建 GeServeModel 返回对象
#6  <GeServeModel as IntoPy>::into_py
#7  GeServeModel::__pymethod_open__
```

**根因（GIL 劫持）**：open 主体持 GIL 跑 → 构图深处的 `aclgrphBuildInitialize` → te fusion py_decouple **static path**（python 宿主里 `dlsym(RTLD_DEFAULT,"Py_Initialize")` 命中宿主符号）→ `HandleManager::Initialize` 见 `PyGILState_Check()!=0`（PyO3 持有）→ **`TE_PyEval_SaveThread()` 偷走 PyO3 的 GIL 并存走 thread state**。open 全部完成后 PyO3 `into_py` 要分配 python 对象 → 解释器状态已烂 → pymalloc `get_state()` SEGV。（forkserver 关闭只是把死点从中途稳定到 open 尾；真正的凶手一直是 GIL 劫持。）

**修复（子模块 2dbffe9，两行根因）**：
1. `GeServeModel::open` 主体包进 `Python::allow_threads`（GIL 释放区）——init 时 `PyGILState_Check()==0`，te **不触发 SaveThread**；te 内部 python 调用自走 `PyGILState_Ensure/Release`，宿主线程状态全程完好
2. `ge_init_once` 默认 `MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile`（forkserver off 固化）；逃生门反转为 `APXINF_GE_NO_BUILD_INIT=1`

**验证**：`open 176.4s` 完整返回 + `infer ×3 max_diff=0.0244 rel=1.0%`（与 spool 桶逐位同）+ per-call 250-262ms（与 spool 稳态同量级）+ `PYO3_GESERVE_OK RC=0`；3 次独立进程稳定复验见 pyo3_stability.sh。

**结构性认识修正**：此前"GE 库内部 exit() / TBE 子进程相克"的推测均不成立——是**可修复的 GIL 协议违反**（te static path 假定自己是宿主里唯一的 python 管理者）。inproc 全链（engine.py → PyO3 → crate GeServe）在 rust 容器内已无障碍。

## 顺带事实

- 服务器收工状态保持：无引擎活体、pyo3 实验进程全部退出（SEGV 退出码可见）
- 9.0.1 容器 python3.12 环境：dlsym(RTLD_DEFAULT) 命中宿主符号成立（判决 1 的 panic 形态侧面证实——C++ 侧防护逻辑走到了 static path 分支的行为）
