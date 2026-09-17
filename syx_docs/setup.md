# 环境配置

## 远程服务器（NPU 机器）

### 连接方法（Windows 中文用户名坑）

本地 Windows 用户名是"素玄"（非 ASCII），Git Bash 的 `~/.ssh` 解析会坏掉。所有 ssh 命令必须显式指定 key 和 known_hosts 路径：

```bash
ssh -i /c/sshkeys/id_ed25519 \
    -o UserKnownHostsFile=/c/sshkeys/known_hosts \
    -o StrictHostKeyChecking=accept-new \
    root@192.168.13.119 '命令'
```

- key 位置：`/c/sshkeys/id_ed25519`（ASCII 路径，绕开中文用户名）
- 必须显式 `root@`（`~/.ssh/config` 读不到，否则会用本地用户名连）
- 详细坑见 `.claude/skills/remote-ssh-windows/operations.md`

### 服务器硬件与环境（2026-09-16 实测）

| 项 | 值 |
|---|---|
| 主机名 | admin123 |
| 系统 | Ubuntu 22.04.5 LTS, aarch64 |
| NPU | 8 × Ascend 310P3（Atlas 300I Duo 类卡，每芯 ~44GB） |
| npu-smi | 26.0.rc1 |
| 主机侧 CANN | /usr/local/Ascend 有 develop/driver/firmware |

**共享服务器**：跑着大量别人的容器（vllm-ascend、MindIE 等，见 `docker ps`）。用卡前先 `npu-smi info` 看空闲芯片。2026-09-16 实测：多数芯显存被占（~39/44GB），chip 4/5 相对空闲。计算任务用 `ASCEND_RT_VISIBLE_DEVICES=N` 指定空闲芯。

### 可用容器与镜像

**本项目的容器 `apxinf_npu`**（2026-09-16 创建）：

- 镜像：`mindie:3.0.0.dev202603270000_torch2.9.0-300I-Duo-py3.11-ubuntu24.04-aarch64`（复用现有镜像，免 42G 拉取）
- 环境：Python 3.11.10 / torch 2.9.0 / torch_npu 2.9.0.post1 / CANN 8.5.1 / transformers 4.51.0
- 创建方式：站点标准（privileged + /data /home /tmp 挂载 + driver 挂载），日志与工作区在 `/data/apxinf/`
- NPU 可见性：8 颗全可见，用 `ASCEND_RT_VISIBLE_DEVICES=N` 挑空闲芯（4-7 相对空闲）
- 环境搭建脚本：`/data/apxinf/env_setup.sh`（本地镜像 `syx_docs/dev_logs/remote_env_setup.sh`），日志 `/data/apxinf/env_setup*.log`
- pip 源：**阿里云**（清华源对 setuptools/modelscope 返回 403，实测踩坑）
- HF 源：`HF_ENDPOINT=https://hf-mirror.com`；github 走 `gh-proxy.com` 前缀

### 容器内依赖安装坑（2026-09-16 实测，重要）

1. **lerobot 元数据钉版会连锁降级 torch**：lerobot 0.4.3 声明 `torch<2.8.0`，它是可编辑安装后，**任何** pip 安装都会全环境重解，把镜像的 torch 2.9.0 降到 2.7.1 → 打坏 torch_npu 2.9.0.post1 配对。**解法**：改 `/data/apxinf/lerobot/pyproject.toml`（torch 下界放开、torchvision 放宽到 >=0.16.0）+ `pip install --no-deps -e` 刷新元数据，再装其余依赖
2. **transformers 修复分支被墙**：lerobot [pi] extra 要 `transformers@git+...@fix/lerobot_openpi`，git 直连 GnuTLS -110。**解法**：`pip install "transformers @ https://gh-proxy.com/https://github.com/huggingface/transformers.git@fix/lerobot_openpi"`
3. **pkill 自匹配**：`pkill -f "pip install"` 会杀掉含该字串的自己。用 `pkill -f "pip instal[l]"`
4. ModelZoo 的 `requirements.txt`（torch-npu==2.7.1 + numpy==1.26.2）**不要装**——按我们镜像版本走
5. 权重位置：`/data/apxinf/weights/{pi05_libero_finetuned, paligemma-3b-pt-224}`（modelscope 下载，脚本 `download_weights.sh`）
6. checkpoint 形态（pi05_libero_finetuned）：input = `observation.images.image`(3×256×256) + `observation.images.image2`(3×256×256) + `observation.state`(8) + `observation.images.empty_camera_0`(3×224×224 占位零图)；output = `action`(7)；config 里 `device: cuda`（补丁强制改 npu，无碍）

### 容器内追加安装清单（2026-09-16，重建容器时照此执行）

**pip**（阿里源）：
```bash
pip install websockets msgpack msgpack-numpy   # L3 websocket serving
pip install -U modelscope                      # 权重下载
# lerobot 本体走 /data/apxinf/env_setup.sh + fix_deps*.sh（torch 钉版逻辑见上）
```

**apt**（Ubuntu 24.04 包名，注意不是 libegl1-mesa/libosmesa8）：
```bash
apt-get update
apt-get install -y libegl1 libegl-mesa0 libopengl0 libosmesa6 libgl1   # LIBERO 离屏渲染（MUJOCO_GL=egl，osmesa 兜底）
apt-get install -y cargo                                              # 阶段 2 Rust（1.75.0，FFI 冒烟够用；ACL 头文件在 /usr/local/Ascend/ascend-toolkit/latest/include/acl/，libascendcl.so 在 .../lib64/）
```

**libero 一次性配置**（`~/.libero/config.yaml`，交互 prompt 用 echo 绕过）：
```bash
echo n | python3 -c "from libero.libero import get_libero_path; print(get_libero_path())"
```

**libero benchmark 资产**（hf-libero 的 pip 包不带 bddl/assets，init_files 自带）：
- HF 镜像对大量小文件 429 限流，`download_assets_from_huggingface()` 会静默失败
- 用 `fetch_libero_assets.py`（本地档 `syx_docs/dev_logs/`，snapshot_download max_workers=2 + 重试），目标路径 `/usr/local/lib/python3.11/site-packages/libero/libero/assets`（~400MB）

**容器内 transformers 补丁（2026-09-16，已改为本仓猴子补丁）**

transformers 修复分支（4.53.3 fix/lerobot_openpi）相对 ModelZoo 测试时点有漂移，两处 `logger.warning_once` 会让 TorchAir fullgraph 编译报 `Unsupported: Logger not supported`：

- `transformers/models/gemma/modeling_gemma.py:474`（gradient_checkpointing 警告；checkpoint 带训练期 gradient_checkpointing=True + NPU 补丁删了热路径 .eval() → 该分支被追踪）
- 同文件 ~760 行（inputs_embeds padding 警告；pi05 每次 forward 必经）

**处理（2026-09-16 定稿）**：**不再改容器文件**——`src/apxinf_robo/npu_torch.py` 的 `_silence_transformers_loggers()` 在加载时把 gemma/siglip 模块的 `logger` 换成 `_SilentLogger`（no-op 方法的普通对象，dynamo 可内联追踪）。容器内 transformers 保持原样（曾手工改过，已还原验证）。同时策略加载后显式 `policy.model.gradient_checkpointing_disable(); policy.eval()`（同文件）。**已实测：纯净 transformers + 猴子补丁，TorchAir 编译正常，e2e 稳态 374ms。**

8. **PYTHONPATH 不可覆盖只能追加**：容器自带 PYTHONPATH 含 CANN 的 `tbe`/site-packages 路径（GE 图编译要用）。`export PYTHONPATH=新值` 覆盖后 GE 初始化报 `No module named 'tbe'` → `AclSetCompileopt error 500001`。**必须** `export PYTHONPATH=...:$PYTHONPATH`
9. NPU 任务三件套模板：`export ASCEND_RT_VISIBLE_DEVICES=5; export PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH; cd /data/apxinf`（robo 包 + 引擎纯 Python 前端）

### 帧格式要点（喂 LeRobot preprocess 的正确姿势）

- 图像 **CHW + batch 维 + float32 [0,1]**：`(1, 3, 256, 256)`，uint8 输入须 `/255`（LeRobot 评测链语义，`preprocess_observation` 做同样转换；NPU 补丁 `img*2-1` 假设 [0,1]——**uint8 直喂 = [-1,509] OOD，形状对但行为崩**，已修于 `_to_frame`）
- state `(1, 8)` float32（pos+axis-angle+双指 qpos）；task `["..."]` 列表——state 离散化器和 prompt 拼接都按 batch 维迭代
- wire HWC uint8 → 包装层 `transpose(2,0,1)[None]` + `/255` 转换（已实现于 `NpuTorchPi05Policy._to_frame`）

其他相关容器/镜像见 `docker ps` / `docker images`（vllm-ascend 系列、cann9.0.1、旧容器 syx_dp 等）。

可用镜像（`docker images`，挑重点）：

| 镜像 | 说明 |
|---|---|
| `mindie:3.0.0.dev20260327_torch2.9.0-300I-Duo-py3.11-ubuntu24.04-aarch64` | 42.6GB，MindIE 3.0.0 + torch 2.9 |
| `swr.cn-south-1.myhuaweicloud.com/ascendhub/cann:9.0.1-310p-openeuler24.03-py3.12` | CANN 9.0.1 |
| `quay.io/ascend/vllm-ascend:v0.23.0-310p` 系列 | vllm-ascend，多个变体 |

### GitHub 被墙（服务器拉代码）

大陆服务器直连 github 常失败。用代理前缀：`git clone https://gh-proxy.com/https://github.com/owner/repo.git`，或配全局 `insteadOf`。详见 remote-ssh-windows skill 的 operations.md「远程服务器拉 github 仓」节。

## 本地仓库

| 项 | 值 |
|---|---|
| 路径 | `D:\compass\APXinf` |
| remote | git@github.com:WeNeedMoreCode/APXinf-robo.git（SSH 直连可用） |
| 分支 | main @ 44db03b |
| 子模块 | `apxinf/` = infinigence/ApxInf @ ba968f6（已 init） |

ModelZoo 参考仓：`d:\compass\modelzoo\ModelZoo-PyTorch\ACL_PyTorch\built-in\embodied_ai\`（π0.5 适配在 `vla/pi05_openpi`、`vla/pi05_lerobot`、`vla/pi0`）。

## APXinf-robo 构建要点（CUDA 原版，作参照）

- Rust + maturin 构建 Python 扩展：`maturin build --release --features cuda -m apxinf/crates/apxinf-py/Cargo.toml`
- 需要 nvcc、cuBLAS、CUTLASS（vendored）
- 官方支持：Jetson Thor(sm_110)/Thor-U(sm_101)/Orin(sm_87)/RTX 4090(sm_89)
- 验证：`python scripts/bench_pi05.py --random-weights --precision bf16 --layer l1 --samples 5`
