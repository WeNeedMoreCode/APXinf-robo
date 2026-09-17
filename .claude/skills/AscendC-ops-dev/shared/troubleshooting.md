# 排查方法论与错误码

**何时读此文件**：kernel 行为不符合预期（launch 失败、结果不对、API 异常），需要系统化排查。适用于 kernel 开发和注册两个场景。

## 遇到未知行为时的排查顺序

1. **先跑官方 sample**：确认硬件和驱动正常。Sample 不过说明环境问题。
2. **最小化 kernel**：只保留出错的那一个 API 调用，去掉所有无关代码。
3. **逐步输出**：每步操作后立即输出返回值和结果，不要等到最后。
4. **Host readback**：用 `aclrtMemcpy D2H` 验证 GM 数据是否真的写对了。
5. **独立 buffer**：每个测试用独立的 TBuf，避免 DMA 竞争的干扰变量。
6. **分离事实和假设**：记录"看到了什么"，不是"为什么"。用新实验验证假设。
7. **先查 samples 里有没有对等实现**：`3_libraries` 有 scatter 标量循环，`2_features` 全是规则访问。确认是否有更优方案可用。

## 先查官方样例再自己造轮子

当 API 行为不符合预期时，先查官方 sample/example，再设计自己的解决方案。AscendC 的同步机制、内存序、API 变体有芯片特定要求，光看 API 签名看不出来。

不起作用和真正能用的方案可能只差一个你不知道的参数（比如 `SyncAll()` 无参 vs `SyncAll(syncGM, syncLocal, coreNum)`）。官方 sample 展示了特定硬件的正确调用方式。

## 常见错误码

| 错误码 | 含义 | 常见原因 |
|--------|------|----------|
| 107002 | Kernel launch 失败 | 未调用 `torch.npu.set_device(0)`；缺少设备上下文 |
| 107003 | Stream 不在当前上下文 | `free_resource()` 销毁了共享的 AscendCL context |
| 507014 | AICore timeout | SyncAll buffer 未清零，残留标志导致死锁 |
