#!/bin/bash
# gdb live 抓 SEGV 全栈（python + C）——open 尾后段错误定位
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export ASCEND_RT_VISIBLE_DEVICES=2
export PYTHONUNBUFFERED=1
export APXINF_GE_BUILD_INIT=1
export MIN_COMPILE_RESOURCE_USAGE_CTRL=ub_fusion,op_compile
gdb --batch \
    -ex "set pagination off" \
    -ex "handle SIGSEGV stop print" \
    -ex "handle SIGPIPE nostop noprint pass" \
    -ex run \
    -ex "thread apply all bt 25" \
    --args python3 /data/apxinf/pyo3_check/check.py 2>&1 | tail -120
date +%T
