---
name: control-edu33212a
description: 通过本机上位机连接、查询及控制 Keysight EDU33212A 波形发生器，设置波形、CH2 正弦扫频和通道输出开关。用于真实仪器控制任务；不用于 DL350 采样或其他型号。
---

# EDU33212A 波形发生器控制

## 本机执行入口

- 项目：`<项目目录>`；Python：该目录 `.venv\Scripts\python.exe`。
- 上位机：`generator_app.py`，也可双击 `启动上位机.bat`。启动只连接与查询，不开启输出。
- 客户端：项目中的 `generator_client.py`。所有操作必须通过正在运行的上位机接口，不直接调用 `edu33212a.py`，不模拟点击界面，不另开 VISA 会话。
- 核对型号 EDU33212A。实际序列号通过 EDU33212A_SERIAL 配置，必须由用户提供或从设备连接信息读取，不能猜测；USB 地址由上位机枚举。

## 工作流程

1. 调用客户端 `status` 获取连接状态和时间；必要时调用 `refresh` 获取新回读，断开则 `connect`。若上位机未运行，可在用户已要求控制本仪器的范围内启动项目上位机，后台启动时隐藏终端；连接失败只做诊断，不反复重试输出命令。
2. 从用户任务提取通道、波形、频率（Hz）、幅值（Vpp）、偏置（V）、实际负载（`50` / `INF`）、是否开启输出。常用通道为 CH2；用户指定其他通道时遵从。幅值单位不明确或必需参数缺失时询问，不自行选取电压、负载或实验频率。
3. 对扫频任务，另需起止频率、扫动时间（秒）、`LIN`/`LOG`；目前支持仪器内部连续重复正弦扫频。逐频点停留、响应测量或单次扫频不是当前接口能力，不将其冒充为已完成。
4. 提交配置任务，等待 `succeeded`，核对回读。配置会关闭所选通道输出；如果用户仅要求配置，不额外开启。用户明确要求输出且接线、实际负载、信号参数已明确时，随后提交独立的开启输出任务，无需对相同明确授权重复询问。
5. 关闭请求直接提交所选通道 `output/off`。不要关闭未指定通道，除非用户要求全部停止。
6. 最终反馈任务成功/失败、通道及回读参数、输出状态。回读是设定值，不是实测波形。状态过期或断开时不得声称仪器已关闭；执行失败可能已有部分配置生效，应查询现状。

## 命令与协议

在 PowerShell 中使用项目 Python：

```powershell
& '<项目目录>\.venv\Scripts\python.exe' '<项目目录>\generator_client.py' status
& '<项目目录>\.venv\Scripts\python.exe' '<项目目录>\generator_client.py' refresh
```

控制请求写入项目内的 UTF-8 JSON 文件，再用客户端 `send --file <绝对路径>`，避免 shell 引号破坏 JSON。请求只有 `action`、`parameters`，不得附加原始 SCPI 或 Python 代码。

| action | parameters 必需字段 |
|---|---|
| connect / refresh | `{}` |
| configure | channel: 1/2；waveform: SIN/SQU/RAMP/PULS；frequency、amplitude、offset: 数值；load: 字符串 50/INF |
| sweep | channel: 1/2；start、stop、seconds、amplitude、offset: 数值；spacing: LIN/LOG；load: 字符串 50/INF |
| output | channel: 1/2；state: on/off |

关闭 CH2 请求：`{"action":"output","parameters":{"channel":2,"state":"off"}}`。

客户端提交后自动轮询至结束，默认 60 秒。`queued`/`running` 不是执行成功；超时保留原任务 ID，使用 `task <id>` 查询，勿重复提交。`failed` 和 `cancelled` 均不是成功。`status` 返回上位机缓存，`updated_at` 为 UTC；用 `refresh` 请求实时回读。

接口只监听 127.0.0.1，客户端从项目 `.runtime/endpoint.json` 读取地址和令牌，不向用户输出令牌。界面与客户端共用工作线程，旧版直连脚本和 IOLS 调试窗口不应同时操作设备。

## 连接故障

先检查电源和 USB，再检查 Connection Expert 能否识别设备。项目需要 PyVISA、IOLS 和 PySide6；Windows 本机驱动不由 pip 代替。库加载失败时报告准确错误，不能自行修改系统 DLL、禁用安全设置或升级仪器固件。

