UniXNU v5 完整控制与实际 iOS 组件续建（草稿，等待 C8）

这份配置认证复用固定 C6 的 host Rust archive/Mesa/IR3 工具，避免再次编译222MB host桥接库；完整29a host suite、额外Q4/P6、实际iOS Turnip/Rustbridge/plugin和真实签名仍执行。不得把复用步骤记成新build成功，不得声称原eae Q未经修改通过。

发布前硬条件：C8 run41455386223/commit3b5ce10d768edd78da2009c2ae5b03adfc47be5e 中reviewed Q4与original P6实际全部通过；本草稿独立源码审查通过。当前没有该运行通过声明，没有发布或执行本草稿。

主变化：Q仅原eae一处artifact_misses==artifact_writes==72改为固定miss72且write48，绑定1f933适配SHA/6b24 diff和实际C7日志。固定C6源/仓库/运行/ZIP摘要与八项输入逐个SHA验证；真实Mac SDK26.5/Apple compiler/profile/current codesign/SPIRV依赖验证；IR3全部368+12原控制重新执行并记录stdout/stderr字节边界和散列。原C6 host-report不改写为新build。

Mesa source/tool setup严格取原device compiler脚本到clean_env定义之前的哈希绑定prefix：准备真实源/11patch/venv固定依赖/Bison3.8.2，停止于任何Mesa configure/ninja前。桥接源使用作者原生--target host --manifest-only检查24patch/tree并生成public AIR/manifest后在Cargo前退出。新iOS目标仍须真正冷构建，不能用Mac archive替代；不承诺总耗时固定。

完整host suite会重建小hostshim/smokes，之后Q/P身份必须等于新runtime，cached Mesa/hostbridge/IR3/锁仍保持原SHA。原输入传输、只读挂载、owner清理15个函数/类与C6逐字一致。所有原库/SDK/缓存/RD均不上传；失败仅新增固定case/last日志路径。下载错误不序列化URL/请求，GitHub令牌不进入构建子进程。

v5协议与标记的精确字段见manifest-protocol-shape.json；该文件含$动态占位，只是协议说明。实际候选只有全部控制与iOS生产/4KiB页签名/资源封印/信任CDHash都过才生成v5清单和待实机资格标记。硬件/安装资格始终false。接收器必须用新v5协议及新run/head/artifact绑定。

部署：除manifest-protocol-shape.json、original-input-unchanged-evidence.json和host-reuse-ready-for-review.json等本地证据外，Python/JSON依赖放ci/；unixnu-gpu-full-qualification.yml映射.github/workflows/unixnu-gpu-only.yml；README可保留仓库根。source-c6固定checkout7af1cc59c8241393e381ddafe20590d47e9db53d。仅contents:read/actions:read。

精确触发消息：Build UniXNU OS17 GPU with authenticated C6 host reuse and reviewed Q cache layout 20261102。根代理独占发布，C8通过前禁止触发。本地未运行构建、测试、CI或设备。
