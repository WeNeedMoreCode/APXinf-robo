#!/bin/bash
# 验证安装：transformers 分支、torchair、打 NPU 补丁、pi05 导入
set -x
pip list 2>/dev/null | grep -E "^transformers"
python3 -c "import transformers; print('transformers', transformers.__version__, transformers.__file__)"

python3 -c "import torchair; print('torchair OK', torchair.__file__)"

cd /data/apxinf/pi05_lerobot/patches
python3 apply_patch.py && echo PATCH_OK

python3 -c "
import inspect
from lerobot.policies.pi05 import modeling_pi05 as m
assert hasattr(m, 'format_cast_to_NZ'), 'patch not applied: no format_cast_to_NZ'
assert hasattr(m, 'apply_npu_rope'), 'patch not applied: no apply_npu_rope'
src = inspect.getsource(m.PI05Pytorch.__init__)
assert 'float16' in src, 'patch not applied: precision not fp16'
print('PI05 NPU patch verified OK')
from lerobot.policies.pi05 import PI05Policy
print('PI05Policy import OK')
"
echo VERIFY_DONE
