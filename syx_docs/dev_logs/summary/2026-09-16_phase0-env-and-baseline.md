# 2026-09-16：阶段 0 环境搭建 + 375ms 基线复现 + 阶段 1 API 打通

> session 归档（中途记录，compact 时可并入正式 summary）。三层标注见 syx-doc-system 写作原则。

## 事实结果

### 环境与资产

- 远程服务器 `root@192.168.13.119` 连通（8×Ascend 310P3，共享机，空闲芯用 `ASCEND_RT_VISIBLE_DEVICES` 挑）
- 容器 `apxinf_npu` 创建（复用镜像 `mindie:3.0.0.dev20260327_torch2.9.0-300I-Duo`，torch 2.9.0 + torch_npu 2.9.0.post1 + CANN 8.5.1 + py3.11）
- π0.5 权重下载完成：`/data/apxinf/weights/pi05_libero_finetuned`（7.0G，LeRobot 格式，modelscope）+ `paligemma-3b-pt-224`（11G）
- LeRobot v0.4.3 可编辑安装 + ModelZoo NPU 补丁应用 + transformers `fix/lerobot_openpi` 分支（4.53.3，走 gh-proxy）
- 本地仓库 D:\compass\APXinf（含 apxinf 子模块 init）

### 测试数字（chip 5，FP16，合成帧）

| 项 | 数字 |
|---|---|
| 模型加载 | 175–181 s（一次性，含 458 层 FRACTAL_NZ 转换） |
| TorchAir 首次图编译 | 105–123 s（一次性） |
| smoke 稳态 P50（裸 select_action 路径） | **375.8 ms**（ModelZoo 官报 375 ms） |
| e2e 稳态（apxinf_robo wire API 全链路） | model_ms 378 / total_ms 395 |
| bench 30 样本（`bench_pi05_npu.py`） | model_ms P50 376.4 / P90 378.7；total_ms P50 383.8 / P90 385.8 |
| 输出 | `actions (50, 7) float32`，数值量级正常 |

### 代码产出

- `src/apxinf_robo/npu_torch.py`（新，~260 行）：`NpuTorchPi05Policy`，实现 apxinf `Policy` Protocol
- `src/apxinf_robo/engine.py`：`load_policy` 加 `engine=` 路由（"apxinf" 默认 / "npu-torch"）
- `scripts/bench_pi05_npu.py`（新）：NPU 版 bench，L2 语义，JSON 输出
- 服务器同步：`/data/apxinf/robo_src`（robo 包）+ `/data/apxinf/engine_py/apxinf`（引擎纯 Python 前端）

### 踩坑记录（全部实测，解法见 setup.md）

1. 清华 pip 源 403 → 换阿里云
2. lerobot `torch<2.8.0` 元数据连锁降级 torch → 改 pyproject 钉 `torch==2.9.0/torchvision==0.16.0` + `--no-deps` 刷新
3. `lerobot[transformers-dep]` 自引用 + 无上界 torchvision → pip 选 0.29 要 torch 2.14 → 硬钉 + 过滤自引用
4. transformers git 直连被墙（GnuTLS -110）→ `git+https://gh-proxy.com/...`
5. numpy 被升 2.2.6 破坏 pandas → 钉回 1.26.4（ModelZoo FAQ 同款问题）
6. pkill -f 自匹配 → `pip instal[l]` 模式
7. LeRobot 帧要 CHW + batch 维（NPU 补丁按视频解码布局假设）；wire HWC 需包装层转置
8. gemma 两处 `logger.warning_once` 炸 TorchAir fullgraph（transformers 分支 7 月后漂移）→ 删调用保留逻辑 + 加载后 eval/关 gradient checkpointing
9. 容器 PYTHONPATH 含 CANN `tbe` 路径，覆盖会导致 GE 初始化失败（`No module named 'tbe'`）→ 只能追加 `:$PYTHONPATH`

## 严格推理

- model_ms(378) ≈ smoke P50(375.8) + 同步开销：e2e 的 model 计时含 predict_action_chunk 内部图像预处理，与 smoke 口径一致（定义推出）
- total_ms - model_ms ≈ 17ms 为 Python 侧 wire→frame 转换 + preprocess 流水线，占比小

## 推测（未严格证明）

- 375ms 与官报完全一致，推断我们容器（CANN 8.5.1 vs 官方指导 8.5.2、torch 2.9 vs 2.7.1）对性能无可观影响
- gemma warning_once 崩溃是 ModelZoo 测试时点（7 月）后 transformers 分支漂移引入，他们没遇到是版本差异而非流程差异

## 下一步（未做）

- bench_pi05.py 接 `--device npu`；与 ModelZoo 输出数值比对（精度对齐）；LIBERO smoke
- `noise=` 精确注入
- 阶段 2（Rust apxinf-ascend）技术相异点逐个过
