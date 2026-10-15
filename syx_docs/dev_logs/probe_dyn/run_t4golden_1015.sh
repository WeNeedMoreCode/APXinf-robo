#!/bin/bash
# run_t4golden_1015.sh — T4R ① 真帧 golden 捕获（apxinf_npu 容器内跑，chip 5）
# PYTHONPATH 只可追加（-e 覆盖式会打死 torch_npu GE init——tbe 丢失）；
# engine_py/apxinf = 编译好的 apxinf PyO3 包（apxinf_robo.envs 触发导入）
cd /data/apxinf/golden
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=5 HF_ENDPOINT=https://hf-mirror.com \
PYTHONPATH=/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  python3 /data/apxinf/golden/golden_gen_t4_1015.py \
  > /data/apxinf/golden/t4gen.log 2>&1
echo "RC=$? $(date -u '+%F %T')" >> /data/apxinf/golden/t4gen.log
