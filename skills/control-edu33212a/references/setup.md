# 在另一台 Windows 电脑上复现

本指南适用于实验室同学在新电脑上部署 EDU33212A 上位机和基础控制 Skill。无需使用原电脑的盘符、用户名或 Python 环境。仪器驱动由每台电脑单独安装，仓库不分发 IOLS 安装包。

## 1. 准备条件

| 项目 | 要求 |
|---|---|
| 电脑 | 本项目已在 Windows 11 x64、Python 3.13 64 位验证 |
| 仪器 | Keysight EDU33212A；其他型号不属于本 Skill 的支持范围 |
| 接线 | 支持数据通信的 USB 线，连接电脑与仪器 USB-B 控制接口 |
| Python | 安装标准 64 位版本，并启用 pip、venv、添加到 PATH |
| IOLS | 从 Keysight 官网安装适配系统的 Windows x64 IO Libraries Suite |
| Codex | 使用 Skill 时需要；只使用上位机不需要 Codex |

Python 下载：https://www.python.org/downloads/windows/

IOLS 下载：https://www.keysight.com/us/en/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637.html

按官网安装说明完成 IOLS 必要组件及重启。当前 USB-B 控制不需要 SIC Expert，也不需要为本项目额外安装 NI-VISA。已有其他 VISA 环境时，先检查兼容性，不直接卸载或覆盖。

PyVISA 是 Python 调用层，不是驱动；`pip install` 不会自动安装 IOLS。IOLS 正常安装后由程序调用，日常不需要打开其安装程序或 Connection Expert。不要禁用它的配套后台服务。

## 2. 下载项目并创建环境

从 https://github.com/XanaCaja/control-edu33212a 下载 ZIP 并解压，或使用 Git 克隆。目录可自行选择，以下示例使用 `D:\Lab\control-edu33212a`；若实际目录不同，请替换第一行。

```powershell
$project = 'D:\Lab\control-edu33212a'
Set-Location -LiteralPath $project
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
```

不要复制原电脑的 `.venv`，应在新电脑重新创建。上述命令直接使用虚拟环境中的 Python，无需执行激活脚本，也无需修改 PowerShell 执行策略。锁定依赖版本记录的是原环境，若安装失败，保留具体报错排查，不将安装失败当成仪器故障。

## 3. 检查 USB 连接并取得序列号

1. 开启仪器，用 USB 连接电脑。
2. 在开始菜单打开 **Keysight Connection Expert**，确认找到 EDU33212A，读取其真实序列号。
3. 必要时在交互通信工具发送 `*IDN?`，核对返回的厂家、型号和序列号。该查询不会开启信号输出。
4. 结束交互通信，再启动本项目。上位机运行期间，不要同时通过 Interactive IO 或旧版直连程序控制设备。

不能复用其他仪器的序列号，也不能猜测 VISA 地址；程序按指定序列号枚举实际 USB 设备并核对型号。

## 4. 设置本机参数并启动

在刚才的 PowerShell 中执行，将序列号占位文本替换为第 3 步读取的真实值：

```powershell
$env:EDU33212A_SERIAL = '<填写真实仪器序列号>'
$env:EDU33212A_HOME = $project
.\.venv\Scripts\python.exe .\generator_app.py
```

`EDU33212A_SERIAL` 是公开版驱动模块选择目标设备的必要条件；`EDU33212A_HOME` 用于标识项目位置。不能将尖括号占位文本原样使用。主窗口显示“已连接”和正确的设备身份后，连接部署才算完成；窗口启动不等于设备已连接。

启动只连接并查询，不开启输出。关闭窗口也不会自动关闭已开启的输出。配置或产生信号前应核实外部接线及负载。

### 后续双击 BAT 启动

上面的环境变量只对当前 PowerShell 及其子进程有效。若希望以后从资源管理器双击 BAT，关闭上位机后，可在同一 PowerShell 中保存当前用户的配置：

```powershell
[Environment]::SetEnvironmentVariable('EDU33212A_SERIAL', $env:EDU33212A_SERIAL, 'User')
[Environment]::SetEnvironmentVariable('EDU33212A_HOME', $project, 'User')
```

保存前确保两项值已正确填写。重新登录 Windows 以确保资源管理器继承新变量，然后双击项目中的 `启动上位机.bat`。更换仪器时重新核对并更新序列号，重启上位机。不需要每次重新安装 IOLS。

## 5. 安装并使用 Skill

上位机正常后，将整个 `skills\control-edu33212a` 目录安装到个人技能目录，必须包含 `references` 文件夹。本机若已有同名 Skill，先检查版本，不直接覆盖。新安装可执行：

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
$skillTarget = Join-Path $skillRoot 'control-edu33212a'
if (Test-Path -LiteralPath $skillTarget) { throw '同名 Skill 已存在，请先检查已有版本' }
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $project 'skills\control-edu33212a') -Destination $skillTarget -Recurse
```

重新打开 Codex 后，告诉助手实际项目目录，先请求“使用 control-edu33212a 查询仪器状态”。如果进程没有继承 `EDU33212A_HOME`，可在请求中明确项目路径，不需要修改成原作者的路径。

Skill 默认 CH2、高阻；其他必要参数缺失时询问。任何配置或开关输出操作，先展示完整配置和最终状态，等待人的确认后执行。扫频、逐频点、计时和循环由上层 Skill/Agent 负责；上位机保留的扫频按钮不代表基础 Skill 会编排实验。

## 6. 验收与故障排查

上位机运行后，在另一个 PowerShell 中进入项目目录，执行只读验证：

```powershell
.\.venv\Scripts\python.exe .\generator_client.py refresh
```

成功标准：任务为 `succeeded`，回读型号/序列号匹配真实设备，上位机能持续更新状态。本步骤不应改变输出开关；不要为验证部署而默认开启信号。配置/输出功能应在参数和接线明确、人工确认后另行验证。

不接设备也可运行模拟测试：

```powershell
.\.venv\Scripts\python.exe -m unittest test_generator_service -v
```

| 情况 | 检查方法 |
|---|---|
| 找不到 Python / `.venv` | 检查 Python 安装和当前目录，重新创建项目环境 |
| 未设置序列号 / 找不到目标设备 | 检查启动进程的 `EDU33212A_SERIAL`、电源、USB 和真实序列号 |
| `VI_ERROR_LIBRARY_NFOUND` | 检查 IOLS 是否完整、是否按提示重启，再检查 Python/VISA 位数与库选择 |
| Connection Expert 正常但 Python 失败 | 退出仪器控制程序后运行 `.\.venv\Scripts\pyvisa-info.exe`，保留诊断信息；不要替换系统 DLL |
| 本地端口被占用 | 检查是否已有上位机实例，不重复启动 |
| 客户端无法连接 | 检查上位机是否运行、项目目录是否一致；不要复制别人的 `.runtime` 目录 |

日志位于项目 `logs`。`.runtime` 含当前进程的接口令牌；这些内容、缓存、状态快照及 `.venv` 均不需要拷贝给其他同学或提交到 GitHub。IOLS 由使用者从官网自行安装，仓库只包含源码、依赖清单和说明。
