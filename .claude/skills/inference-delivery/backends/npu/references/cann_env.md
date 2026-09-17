# CANN 环境速查

## 推荐组合

| 组件 | 版本 |
| --- | --- |
| CANN | >= 8.3.RC2 |
| Python | 3.11 |
| NumPy | 1.26.4 |
| ONNX | 1.16.1 |

## CANN / Python 对应关系

| CANN 区间 | Python 建议 |
| --- | --- |
| >= 8.3.RC2 | 3.11（推荐） |
| 8.1.x - 8.3.RC1 | 以官方要求为准，常见 3.10 |

- 先看 CANN 版本，再决定 Python 版本
- 若已有可用 CANN，先查该版本对应的 Python，再决定是否复用

## 安装路径

常见两类：
- `/usr/local/Ascend/ascend-toolkit`（8.3.x）
- `/usr/local/Ascend/cann`（8.5.x+）

## 安装方式分代

### 8.3.RC2 同代（拆包）

组件：`toolkit` + `nnae` + `nnrt` + 对应产品 `kernels`

环境变量：
- `${HOME}/Ascend/ascend-toolkit/set_env.sh`
- `${HOME}/Ascend/nnae/set_env.sh`
- `${HOME}/Ascend/nnrt/set_env.sh`

### 8.5.x 及更新（合并）

组件：`toolkit` + 对应产品 `ops`（必须同时装）

环境变量：
- `${HOME}/Ascend/cann/set_env.sh`

## 何时需要重新核对环境

- `atc` 不在 PATH
- `atc` 执行即报环境错误
- ONNX 优化工具无法导入
- `auto_optimizer` 无法运行
- 同一张图在不同机器上结果不一致
