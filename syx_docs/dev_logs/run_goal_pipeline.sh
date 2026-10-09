#!/bin/bash
# run_goal_pipeline.sh — goal 泛化一条龙（goal ③）：录制 → golden → sweep
# 顺序执行（sweep 判 transfer：v3o object 因子 vs goal 专属拟合，成立则免重烤）。
cd /data/apxinf/replay
bash record_goal_all.sh > /tmp/rec_goal_all.log 2>&1
bash goal_calib_chain.sh > /tmp/goal_chain.log 2>&1
echo "GOAL_PIPELINE_DONE $(date -u +%T)"
