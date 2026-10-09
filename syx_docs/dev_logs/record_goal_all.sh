#!/bin/bash
# record_goal_all.sh — libero_goal 谱系 v3 校准录制（泛化轮 goal ③）：
# replay_g{0..3}.safetensors（torch golden 40 帧/任务，record_rollout.py
# 的 REPLAY_SUITE/REPLAY_OUT 参数化路径）。goal 谱系 L 分布由本录制实测
# （顺带产出 goal ① 预置范围策略的需求数据）。
# 跑法（apxinf_npu 容器，chip1 避开生产 serve 轮转芯 6425）：bash record_goal_all.sh
cd /data/apxinf
for T in 0 1 2 3; do
  echo "=== goal rec task $T start $(date -u +%T) ==="
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=1 \
  REPLAY_SUITE=libero_goal \
  REPLAY_OUT=/data/apxinf/replay/replay_g{task}.safetensors \
  REPLAY_MAX_STEPS=40 REPLAN=1 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  python3 /data/apxinf/replay/record_rollout.py $T \
    > /tmp/rec_g$T.log 2>&1
  echo "=== task $T rc=$? $(date -u +%T) ==="
  tail -3 /tmp/rec_g$T.log
done
echo "REC_GOAL_ALL_DONE $(date -u +%T)"
ls -la /data/apxinf/replay/replay_g*.safetensors
