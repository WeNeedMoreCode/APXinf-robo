# 反向排除法实例：AscendC Ball Query 算子调试

## 背景

Ball Query 算子有两个版本：
- **debug 版本**（带详细诊断输出）：PASS
- **production 版本**（去掉诊断代码）：FAIL

两个版本的差异包括：
1. 诊断变量声明
2. 循环内数据捕获（isDebugQuery 分支内的 GetValue）
3. 循环后诊断写入（Duplicate+SetValue+DataCopy 写到 debugGm）
4. GetValue(0) 依赖

每个差异独立，可以逐个去掉，满足反向排除法的前提条件。

## 排除过程

从 debug 版本（PASS）出发，逐个去掉诊断代码：

1. 去掉循环内数据捕获（isDebugQuery 分支内的 GetValue） → 仍然 PASS
2. 去掉循环后的 Duplicate+SetValue+DataCopy（诊断写入到 debugGm） → **FAIL！**

## 定位结果

去掉诊断写入后 FAIL，说明不是诊断写入本身的问题，而是诊断写入**意外地提供了 DMA 依赖**。

进一步验证：production 版本加一行 `GetValue(0)` 建立读取依赖后 PASS。

## 教训

诊断代码不只是"打印日志"，它可能意外地提供了数据依赖关系，使得原本有 bug 的代码恰好能工作。去掉诊断代码后，隐藏的依赖缺失暴露出来。
