# 昇腾 NPU Docker 开发环境搭建

## 怎么选镜像

从 AscendHub（`swr.cn-south-1.myhuaweicloud.com/ascendhub/`）拉镜像，匹配 **torch 版本 + CANN 版本 + 芯片型号**：

| 镜像名 | 内容 |
|--------|------|
| `torch-onnx-inference:cann8.3.rc1_torch2.1.0-300I-DUO-ubuntu22.04-py3.11-aarch64` | torch 2.1.0 + CANN 8.3 RC1 + 300I DUO |

`docker images` 列出本地已 pull 的镜像。用镜像 ID 或 `REPOSITORY:TAG` 均可。

## 创建容器命令模板

```bash
docker run --name <容器名> -it -d --net=host --shm-size=500g \
    --privileged=true \
    -w /home \
    --device=/dev/davinci_manager \
    --device=/dev/hisi_hdc \
    --device=/dev/devmm_svm \
    --entrypoint=bash \
    -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
    -v /usr/local/dcmi:/usr/local/dcmi \
    -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
    -v /usr/local/sbin:/usr/local/sbin \
    -v /home:/home \
    -v /mnt:/mnt \
    -v /data:/data \
    -v /usr/share/zoneinfo/Asia/Shanghai:/etc/localtime \
    <镜像ID或TAG>
```

要点：
- `--device=/dev/davinci_manager --device=/dev/hisi_hdc --device=/dev/devmm_svm`：NPU 设备透传，缺一个容器里 `torch.npu.is_available()` 就是 False
- `-v /home:/home`：让容器能访问宿主机 `/home` 下的代码和数据（**最重要**的挂载）
- `-v /usr/local/Ascend/driver:/usr/local/Ascend/driver`：挂载驱动（容器镜像自带 CANN toolkit，但 driver 从宿主机来）
- `--net=host --shm-size=500g`：共享宿主机网络 + 大共享内存

## 容器内环境搭建

### 容器自带什么 vs 需要自己装什么

镜像来自 AscendHub 通常自带：
- Python（确认版本是否匹配项目需要）
- torch + torch_npu（已装好，`pip show torch-npu` 确认版本）
- CANN toolkit（`source /usr/local/Ascend/ascend-toolkit/set_env.sh`）
- g++

通常需要自己装：
- conda 环境（如果项目需要特定 Python 版本）
- pip 依赖（`pip install -r requirements.txt`）
- AscendC 自定义内核（`bash run.sh -r npu`）
- `setuptools<70`（如果报 `No module named 'pkg_resources'`——新版 setuptools 移除了它）

### 建 conda 环境（如果需要特定 Python 版本）

镜像自带 Python 可能和项目需求不一致。如果 README 要求特定版本：

```bash
# 接受 conda ToS（如果有）
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 建环境
conda create -n <env名> python=<版本> -y

# 装 torch + torch_npu（版本对齐镜像里的）
<conda路径>/envs/<env名>/bin/pip install torch==<版本> torch_npu==<版本>

# numpy 版本兼容
<conda路径>/envs/<env名>/bin/pip install "numpy<2"  # torch 2.1 不兼容 numpy 2.x
```

**注意**：`pip config list` 看镜像用的 pip 源——通常是 `https://repo.huaweicloud.com/repository/pypi/simple`，torch_npu wheel 从这个源装。

### CANN 容器通用踩坑（共享服务器 / 大陆网络，2026-09 实测）

1. **PYTHONPATH 只能追加不能覆盖**：CANN 镜像自带 PYTHONPATH 含 GE 图编译要用的
   `tbe` 等路径。`export PYTHONPATH=新值` 覆盖后 GE 初始化报
   `No module named 'tbe'` → `AclSetCompileopt error 500001`。必须
   `export PYTHONPATH=你的路径:$PYTHONPATH`。
2. **pip 源选择**：清华源对部分包（setuptools/modelscope）返回 403，用阿里云
   `https://mirrors.aliyun.com/pypi/simple/`。GitHub 直连常失败：git clone 加
   `https://gh-proxy.com/` 前缀；HuggingFace 用 `HF_ENDPOINT=https://hf-mirror.com`。
3. **共享服务器挑空闲芯**：跑前 `npu-smi info` 看显存占用，用
   `export ASCEND_RT_VISIBLE_DEVICES=N` 绑空闲芯——别人容器泄漏/占用的显存不会
   释放，换芯比清显存快。
4. **可编辑安装的包会劫持后续所有 pip 安装**：`pip install -e` 的包若元数据带钉版
   （如 `torch<2.8`），之后**任何** pip install 都会全环境重解依赖，把镜像里配好
   的 torch/torch_npu 版本对连锁降级打坏。解法：改该包 `pyproject.toml` 放宽钉版，
   `pip install --no-deps -e .` 刷新元数据，再装其余依赖；装完 `pip show torch
   torch_npu` 复核版本没被动过。

## 宿主机 ↔ 容器协作

`/home` 两边共享，所以：

```
宿主机：git pull / git clone / scp 文件
容器内：编译 (setup.py build_ext) / 运行 python / 跑测试
```


## 检查清单

跑代码前确认：

```bash
# 1. NPU 设备可见
npu-smi info

# 2. torch 能看见 NPU
python -c "import torch, torch_npu; print(torch.npu.get_device_name(0))"

# 3. CANN 环境
source /usr/local/Ascend/ascend-toolkit/set_env.sh && echo OK

# 4. torch 版本 + ABI
python -c "import torch; print(torch.__version__, torch.compiled_with_cxx11_abi())"
# torch_npu 2.1 通常 ABI=False → C++ wrapper 需要 #define _GLIBCXX_USE_CXX11_ABI 0

# 5. 环境变量
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True  # README 要求的
```
