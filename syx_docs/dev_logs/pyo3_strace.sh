#!/bin/bash
# PyO3 check + strace 信号跟踪：捕获主进程死亡信号（SIGSEGV/SIGABRT）与来源
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export ASCEND_RT_VISIBLE_DEVICES=2
export PYTHONUNBUFFERED=1
strace -f -qq -e trace=signal -o /data/apxinf/pyo3_check/signals.txt python3 /data/apxinf/pyo3_check/check.py > /data/apxinf/pyo3_check/run4.log 2>&1
echo "STRACE_RC=$?"
grep -E "SIGSEGV|SIGABRT|SIGKILL|SIGBUS|killed" /data/apxinf/pyo3_check/signals.txt | tail -8
date
