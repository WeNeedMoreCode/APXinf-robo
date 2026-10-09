#!/bin/bash
# goal_calib_chain.sh — goal v3 校准链（泛化轮数值面）：
# 等 replay_g{0..3} 录制齐 → golden_gen_v3calib（goal 谱系数据面）→
# int8_factors_v3_sweep（v3o object 因子 transfer 对照 vs goal envelope 拟合）。
# 产物：calib_v3_goal.safetensors / smooth_calib_v3_goal{,_flow}.npz /
# sweep_v3_goal.json —— 全部独立命名，不覆盖 object/spatial 谱系资产。
cd /data/apxinf
while [ ! -f /data/apxinf/replay/replay_g3.safetensors ]; do sleep 20; done
sleep 15  # 等最后落盘
echo "=== golden_gen goal start $(date -u +%T) ==="
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=3 \
CALIB_OUT=/data/apxinf/golden/calib_v3_goal.safetensors \
REPLAY_FMT=/data/apxinf/replay/replay_g{}.safetensors \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
python3 /data/apxinf/pyo3_check/golden_gen_v3calib.py > /tmp/golden_goal.log 2>&1
RC=$?
echo "=== golden rc=$RC $(date -u +%T) ==="
[ $RC -ne 0 ] && { tail -20 /tmp/golden_goal.log; exit 1; }
echo "=== sweep goal start $(date -u +%T) ==="
CALIB=/data/apxinf/golden/calib_v3_goal.safetensors \
OUT_P=/data/apxinf/pyo3_check/smooth_calib_v3_goal.npz \
OUT_F=/data/apxinf/pyo3_check/smooth_calib_v3_goal_flow.npz \
OUT_JSON=/data/apxinf/pyo3_check/sweep_v3_goal.json \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
python3 /data/apxinf/pyo3_check/int8_factors_v3_sweep.py > /tmp/sweep_goal.log 2>&1
echo "SWEEP_GOAL_DONE rc=$? $(date -u +%T)"
tail -5 /tmp/sweep_goal.log
