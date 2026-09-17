#!/bin/bash
# 修复依赖安装：锁死 torch 全家桶，--no-deps 装 lerobot，其余依赖白名单安装
set -x
ps aux | grep "pip instal[l]" && pkill -9 -f "pip instal[l]"; sleep 1

pip install --no-deps -e /data/apxinf/lerobot

python3 - <<'EOF'
import tomllib, subprocess, sys
with open('/data/apxinf/lerobot/pyproject.toml','rb') as f:
    d = tomllib.load(f)
proj = d['project']
deps = list(proj.get('dependencies', []))
deps += proj.get('optional-dependencies', {}).get('pi', [])
deps += proj.get('optional-dependencies', {}).get('libero', [])
# 锁死不许动的包（版本变动会破坏 torch_npu/torchair 配对）
LOCK = {'torch', 'torchvision', 'torch-npu', 'numpy', 'transformers'}
keep = []
for dep in deps:
    name = dep.split(';')[0].split('==')[0].split('>=')[0].split('<=')[0].split('!=')[0].split('~=')[0].split('>')[0].split('<')[0].strip().lower().replace('_', '-')
    if name in LOCK:
        print(f'SKIP (locked): {dep}')
        continue
    keep.append(dep)
print('INSTALL LIST:')
for k in keep:
    print(' ', k)
r = subprocess.run([sys.executable, '-m', 'pip', 'install'] + keep)
sys.exit(r.returncode)
EOF

python3 -c "import lerobot; print('lerobot OK', lerobot.__path__)"
