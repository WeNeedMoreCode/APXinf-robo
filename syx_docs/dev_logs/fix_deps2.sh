#!/bin/bash
# 修复第二轮：git 依赖走 gh-proxy，其余依赖重装
set -x
python3 - <<'EOF'
import tomllib, subprocess, sys
with open('/data/apxinf/lerobot/pyproject.toml','rb') as f:
    d = tomllib.load(f)
proj = d['project']
deps = list(proj.get('dependencies', []))
deps += proj.get('optional-dependencies', {}).get('pi', [])
deps += proj.get('optional-dependencies', {}).get('libero', [])
LOCK = {'torch', 'torchvision', 'torch-npu', 'numpy', 'transformers'}
keep, git_deps = [], []
for dep in deps:
    if 'git+' in dep or '@ git' in dep or '.git@' in dep:
        git_deps.append(dep)
        continue
    name = dep.split(';')[0]
    for sep in ('==','>=','<=','!=','~=','>','<','[',']','@'):
        name = name.split(sep)[0]
    name = name.strip().lower().replace('_','-')
    if name == 'lerobot':  # self-referential extras trigger full re-resolution
        print(f'SKIP (self-ref): {dep}')
        continue
    if name in LOCK:
        print(f'SKIP (locked): {dep}')
        continue
    keep.append(dep)
print('PIP LIST:', keep)
r = subprocess.run([sys.executable,'-m','pip','install'] + keep)
if r.returncode != 0:
    sys.exit(r.returncode)
print('GIT DEPS (via proxy):', git_deps)
for g in git_deps:
    # transformers@ git+https://github.com/huggingface/transformers.git@fix/lerobot_openpi
    branch = g.rsplit('@',1)[1]
    url = f"https://gh-proxy.com/https://github.com/huggingface/transformers.git@{branch}"
    r = subprocess.run([sys.executable,'-m','pip','install',f'transformers @ {url}'])
    if r.returncode != 0:
        sys.exit(r.returncode)
EOF
python3 -c "import draccus, lerobot; print('deps OK')"
echo FIX2_DONE
