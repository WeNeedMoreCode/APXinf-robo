# 2026-09-16（晚）：阶段 1 收尾四项 + 猴子补丁改造

> 承接同日早间的阶段 0/1 归档。三层标注按 syx-doc-system。

## 事实结果

### 四项收尾全部完成

| 项 | 结果 |
|---|---|
| CLI `--engine` 暴露 | `serve` + `eval-libero` 均支持 `--engine {apxinf,npu-torch}`，`--precision` 增 fp16；serve 的 npu-torch 分支跳过 Rust 引擎 preflight |
| L3 websocket | serve 起服务 + 最小 msgpack 客户端：metadata 正确、`actions (50,7)` 回传；稳态 infer 384ms / policy 409ms |
| `noise=` 注入 | 临时替换 `model.sample_noise`（零填充到模型内部 32 维 padded 空间）；同 noise max diff 2^-10，异 noise 0.25 |
| LIBERO smoke | 520 步 / 104 replan / summary JSON 落盘；success 0/1；model_ms 1378（异常慢，见待查） |

### transformers 兼容改为本仓猴子补丁（用户要求，替代容器文件修改）

- 实现：`npu_torch.py::_SilentLogger` + `_silence_transformers_loggers()`——把 gemma/siglip 模块级 `logger` 换成 no-op 普通对象，dynamo 可内联追踪
- 容器内手工改过的 `modeling_gemma.py` **已还原为原版**，用猴子补丁路径重跑 e2e 验证通过（稳态 374ms，与改文件时一致）
- 原理：dynamo 对 `logging.Logger` 实例的方法调用直接 Unsupported；普通对象方法会被内联为 no-op

### 新发现的事实

1. LeRobot pi05 的 flow matching 噪声在**模型内部 32 维 padded 动作空间**采样（`sample_noise((1,50,32))`），输出时切回 7 维
2. 状态约定冲突：LIBERO wire 7 维（pos+axisangle+grip，openpi）vs LeRobot checkpoint 8 维（pos+quat+grip）——需 `_axis_angle_to_quat` 展开（已实现于包装层）
3. Ubuntu 24.04 包名：`libegl1/libegl-mesa0/libosmesa6`（不是 libegl1-mesa/libosmesa8）
4. hf-libero pip 包不带 bddl assets；HF 镜像对 586 个小文件 429 限流，需 snapshot_download(max_workers=2)+重试
5. 仿真依赖链已全通：MUJOCO_GL=egl + 装齐 GL 库后 robosuite OffScreenRenderEnv 正常出图

## 严格推理

- 同 noise 两次 max diff = 2^-10 恰为 fp16 最后一位 ulp 量级 → aclnn 算子调度级非确定性（数学上 fp16 表示间隔），非注入逻辑缺陷；异 noise 0.25 >> 2^-10 → 注入确实生效

## 推测（未严格证明）

- LIBERO 单步 1378ms（bench 376ms 的 3.7 倍）的候选原因：① task 0 prompt 比 bench 短句长（token 多 → prefill 变大）；② 持续推理负载下 NPU 时钟/供电策略变化；③ 主机 CPU 与 robosuite/EGL 渲染争用拖慢下发。三者均未验证，排查方法：固定 obs 在 eval 进程内单独计时 + 对比 token 长度

## 工程产物

- `src/apxinf_robo/npu_torch.py`：+`_SilentLogger`、+`_axis_angle_to_quat`、+noise 注入、+state 7→8 适配、+`model_type/device` 规范化、+`tokenizer_path` 别名、+`discrete_state` metadata
- `src/apxinf_robo/engine.py`：engine= 路由（不变）
- `src/apxinf_robo/cli/serve.py`、`cli/eval_libero.py`：--engine 接线
- 服务器脚本（本地档 syx_docs/dev_logs/）：`ws_client_pi05_npu.py`、`test_noise_injection.py`、`fetch_libero_assets.py`
- 容器供给清单已固化到 setup.md「容器内追加安装清单」
