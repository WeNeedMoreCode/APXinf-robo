#!/bin/bash
# 恢复 torch 2.9.0 + 正确安装 transformers 分支
set -x
pip install torch==2.9.0 2>&1 | tail -3
pip list 2>/dev/null | grep -E "^torch"
python3 -c "import torch, torch_npu; print('pair OK', torch.__version__, torch_npu.__version__, torch.npu.is_available())"

pip install "transformers @ git+https://gh-proxy.com/https://github.com/huggingface/transformers.git@fix/lerobot_openpi" 2>&1 | tail -3
python3 -c "import transformers; print('transformers', transformers.__version__)"
echo FIX_TORCH_DONE
