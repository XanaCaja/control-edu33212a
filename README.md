# EDU33212A 波形发生器控制

Windows 桌面上位机与 Codex Skill，通过 USB / Keysight VISA 控制 EDU33212A。

**首次在另一台电脑复现，请按 [新电脑部署指南](skills/control-edu33212a/references/setup.md) 操作。** 指南覆盖 IOLS 官网下载安装、USB 识别、Python 环境、实际序列号配置、双击启动、Skill 安装及只读验收；不要求沿用原电脑目录。仓库不包含 IOLS 安装包。

## 安装与启动

安装 Python 3.13（64 位）和 Keysight IO Libraries Suite，确认 Connection Expert 可以识别仪器。在仓库目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
$env:EDU33212A_SERIAL = '<实际仪器序列号>'
.\.venv\Scripts\python.exe .\generator_app.py
```

序列号必须从实际设备或 Connection Expert 获取。公开源码不包含设备序列号和个人项目路径。使用 BAT 启动时，同样需要启动进程能够读取 EDU33212A_SERIAL 环境变量。

## 功能

双通道状态回读、基本波形参数设置、CH2 连续正弦扫频、通道输出开关、操作记录，以及本机 HTTP 任务接口。配置后输出保持关闭；开启需单独操作。界面与 Skill 共用执行端，不模拟鼠标。

## Skill

将整个 skills/control-edu33212a 文件夹（包括 references）复制到个人 Codex skills 目录。使用前设置 EDU33212A_HOME，或向助手提供实际项目位置；不要复制原电脑的目录或序列号。客户端也支持 --home 参数。具体安装命令见新电脑部署指南。

Skill 通过 generator_client.py 调用正在运行的上位机。运行接口令牌、日志、状态快照和虚拟环境不包含在仓库中。

## 使用与测试

参见 [上位机说明](上位机使用说明.md) 和 [Skill](skills/control-edu33212a/SKILL.md)。文档中的 <项目目录>、YOUR_DEVICE_SERIAL 均为需要自行填写的占位符。基础 Skill 只负责连接、查询、单次设置及输出开关，默认 CH2/高阻，完整配置经人工确认后执行；复杂实验由上层编排。

```powershell
.\.venv\Scripts\python.exe -m unittest test_generator_service -v
```

单元测试使用模拟设备。真实仪器已验证连接、CH2 配置与扫频回读、关闭输出；没有开启输出进行实测波形验证。

关闭窗口不会关闭仪器输出。负载设置须与真实接线相符；界面显示设定值，不是实测波形。USB 断开时软件不能保证关闭输出。

旧版直连工具保留，但上位机运行时不要同时通过其他程序操作仪器。

