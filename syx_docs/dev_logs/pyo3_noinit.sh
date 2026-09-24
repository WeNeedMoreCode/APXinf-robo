#!/bin/bash
# python 宿主 GE 障碍 A/B 判决：跳过 aclgrphBuildInitialize（load-only）后
# python 宿主能否活过 open 尾声 + infer 对拍。跑 3 次看存活稳定性。
# 用法: bash /data/apxinf/pyo3_check/pyo3_noinit.sh
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export ASCEND_RT_VISIBLE_DEVICES=2
export PYTHONUNBUFFERED=1
# 判决实验 v2：恢复 aclgrphBuildInitialize（构图需要 OperatorFactory），
# 但用 te 侧 MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile 跳过
# PythonAdapterManager::InitParallelCompilation（forkserver 8 worker——
# "main process disappeared" 元凶）。活着 ⇒ 并行编译是死亡必要条件。
export APXINF_GE_BUILD_INIT=1
export MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile
for i in 1 2 3; do
  echo "=== run$i $(date +%T) ==="
  python3 /data/apxinf/pyo3_check/check.py
  echo "RC_$i=$?"
done
date +%T
