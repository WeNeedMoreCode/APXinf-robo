#!/bin/bash
# SEGV 诊断：open 尾后段错误的栈定位。
# 环境与判决实验 v2 相同（init 恢复 + forkserver 关闭 = 唯一能走到 SEGV 的形态）。
# PYTHONFAULTHANDLER=1：SEGV 时打印 python 层栈（区分死在 python/PyO3 边界还是 GE 内部线程）
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export ASCEND_RT_VISIBLE_DEVICES=2
export PYTHONUNBUFFERED=1
# 修复验证版：GIL 劫持修复（allow_threads）+ forkserver-off 已内置 cdylib，
# 无需任何 env。fault handler 保持——若再崩看栈。
export PYTHONFAULTHANDLER=1
python3 /data/apxinf/pyo3_check/check.py
echo "RC=$?"
date +%T
