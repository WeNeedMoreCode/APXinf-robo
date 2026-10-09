#!/bin/bash
# record_spatial_all.sh — spatial 谱系 v3 校准扩录（goal ③）：
# replay_s{0..3}.safetensors（torch golden 40 帧/任务，record_rollout.py
# 的 REPLAY_SUITE/REPLAY_OUT 参数化路径）。spatial L 谱系 149-156。
# 跑法（apxinf_npu 容器，chip 顺序错开 serve 芯）：bash record_spatial_all.sh
cd /data/apxinf
for T in 0 1 2 3; do
  echo "=== spatial rec task $T start $(date -u +%T) ==="
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=1 \
  REPLAY_SUITE=libero_spatial \
  REPLAY_OUT=/data/apxinf/replay/replay_s{task}.safetensors \
  REPLAY_MAX_STEPS=40 REPLAN=1 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  python3 /data/apxinf/replay/record_rollout.py $T \
    > /tmp/rec_s$T.log 2>&1
  echo "=== task $T rc=$? $(date -u +%T) ==="
  tail -3 /tmp/rec_s$T.log
done
echo "REC_SPATIAL_ALL_DONE $(date -u +%T)"
ls -la /data/apxinf/replay/replay_s*.safetensors
