# APXinf-robo 昇腾 NPU 适配工作区

- **syx_docs_location**: syx_docs/（非原生项目——APXinf-robo 是别人的仓库，文档隔离存放，不覆盖原作者 `docs/`）

## 项目一句话

把 APXinf-robo（Rust 边缘推理引擎，原生 CUDA-only，跑 PI-0.5 VLA）适配出昇腾 NPU 版推理引擎，目标硬件 Ascend 310P3（Atlas 300I Duo）。

## 关键路径

- 本地仓：`D:\compass\APXinf`（git@github.com:WeNeedMoreCode/APXinf-robo.git）
- `apxinf/` 子模块：git@github.com:WeNeedMoreCode/ApxInf.git 的 `ascend-port` 分支（fork 自 infinigence/ApxInf；Rust 引擎本体，阶段 2 的改动都在这里提交）
- 远程服务器：`root@192.168.13.119`（连接方法见 `syx_docs/setup.md`）
- ModelZoo π0.5 参考实现：`d:\compass\modelzoo\ModelZoo-PyTorch\ACL_PyTorch\built-in\embodied_ai\vla\pi05_openpi\`
- 文档导航：`syx_docs/README.md`

## 子模块纪律（勿踩）

引擎改动两步走，缺一不可：① `apxinf/` 内 commit 并 `git push`（fork/ascend-port）；② 回外层仓 `git add apxinf` bump gitlink 并 commit。只做 ①，队友 clone 下来构建的仍是旧引擎。

## Compact Instructions

- 保留：技术路线决策、Backend trait 移植面分析、服务器/NPU 环境事实、下一步动作
- 丢弃：探索过程、已归档到 syx_docs 的细节
