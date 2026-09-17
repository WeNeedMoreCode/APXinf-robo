#!/bin/bash
# pi05_lerobot NPU 环境搭建（在 apxinf_npu 容器内执行）
# 注意：跳过 ModelZoo requirements.txt（torch-npu==2.7.1 会降级镜像自带的 2.9.0）
set -x
export HF_ENDPOINT=https://hf-mirror.com
export CMAKE_POLICY_VERSION_MINIMUM=3.5
export no_proxy=localhost,127.0.0.1

pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

mkdir -p /data/apxinf/weights
cd /data/apxinf

# 1. clone lerobot v0.4.3（优先走代理，失败回退直连）
if [ ! -d lerobot ]; then
  git clone --depth 1 -b v0.4.3 https://gh-proxy.com/https://github.com/huggingface/lerobot.git \
  || git clone --depth 1 -b v0.4.3 https://github.com/huggingface/lerobot.git
fi

# 2. 安装 lerobot + pi 依赖（不装 [libero]，仿真依赖后置）
cd /data/apxinf/lerobot
pip install -e .
pip install -e ".[pi]"

# 3. 打 NPU 补丁
cd /data/apxinf/pi05_lerobot/patches
python3 apply_patch.py

# 4. 下载权重（modelscope 国内直连）
pip install -U modelscope
modelscope download --model lerobot/pi05_libero_finetuned --local_dir /data/apxinf/weights/pi05_libero_finetuned
modelscope download --model AI-ModelScope/paligemma-3b-pt-224 --local_dir /data/apxinf/weights/paligemma-3b-pt-224

echo "SETUP_DONE"
