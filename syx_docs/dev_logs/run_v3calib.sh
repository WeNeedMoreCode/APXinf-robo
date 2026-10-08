#!/bin/bash
# v3 校准 dump 全量跑（docker exec -d 脚本文件形态——内联 bash -c 进程随
# ssh 断连无声死，2026-09-30 取证；FRAME_EVERY=4 → 40 帧约 45min）
cd /data/apxinf
env ASCEND_RT_VISIBLE_DEVICES=3 FRAME_EVERY=4 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  python3 golden/golden_gen_v3calib.py > /data/apxinf/golden/v3calib.log 2>&1
echo "EXIT_RC=$? $(date)" >> /data/apxinf/golden/v3calib.log
