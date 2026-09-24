#!/bin/bash
# 修复后稳定性复验：3 次独立进程 open+infer（昨晚死亡点位非确定，3 连才算稳）
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export ASCEND_RT_VISIBLE_DEVICES=2
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1
for i in 1 2 3; do
  echo "=== run$i $(date +%T) ==="
  python3 /data/apxinf/pyo3_check/check.py 2>&1 | grep -E "open |try|OK|Error|error|Fatal|Segmentation"
  echo "RC_$i=$?"
done
date +%T
