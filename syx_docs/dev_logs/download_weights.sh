#!/bin/bash
# 权重下载（modelscope 国内直连，不依赖 lerobot 安装）
set -x
pip install -U modelscope
mkdir -p /data/apxinf/weights
modelscope download --model lerobot/pi05_libero_finetuned --local_dir /data/apxinf/weights/pi05_libero_finetuned
modelscope download --model AI-ModelScope/paligemma-3b-pt-224 --local_dir /data/apxinf/weights/paligemma-3b-pt-224
echo "WEIGHTS_DONE"
ls -la /data/apxinf/weights/pi05_libero_finetuned | head -20
