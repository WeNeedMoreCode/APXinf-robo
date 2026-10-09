#!/bin/bash
# spatial_calib_chain.sh — spatial v3 校准链（goal ③ 数值面）：
# 等 replay_s{0..3} 录制齐 → golden_gen_v3calib（spatial 谱系数据面）→
# int8_factors_v3_sweep（v3o object 因子 transfer 对照 vs spatial envelope）。
# 产物：calib_v3_spatial.safetensors / smooth_calib_v3_spatial{,_flow}.npz /
# sweep_v3_spatial.json —— 全部独立命名，不覆盖 object 谱系资产。
cd /data/apxinf
while [ ! -f /data/apxinf/replay/replay_s3.safetensors ]; do sleep 20; done
sleep 15  # 等最后落盘
echo "=== golden_gen spatial start $(date -u +%T) ==="
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=3 \
CALIB_OUT=/data/apxinf/golden/calib_v3_spatial.safetensors \
REPLAY_FMT=/data/apxinf/replay/replay_s{}.safetensors \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
python3 /data/apxinf/pyo3_check/golden_gen_v3calib.py > /tmp/golden_spatial.log 2>&1
RC=$?
echo "=== golden rc=$RC $(date -u +%T) ==="
[ $RC -ne 0 ] && { tail -20 /tmp/golden_spatial.log; exit 1; }
echo "=== sweep spatial start $(date -u +%T) ==="
CALIB=/data/apxinf/golden/calib_v3_spatial.safetensors \
OUT_P=/data/apxinf/pyo3_check/smooth_calib_v3_spatial.npz \
OUT_F=/data/apxinf/pyo3_check/smooth_calib_v3_spatial_flow.npz \
OUT_JSON=/data/apxinf/pyo3_check/sweep_v3_spatial.json \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
python3 /data/apxinf/pyo3_check/int8_factors_v3_sweep.py > /tmp/sweep_spatial.log 2>&1
echo "SWEEP_SPATIAL_DONE rc=$? $(date -u +%T)"
tail -5 /tmp/sweep_spatial.log
