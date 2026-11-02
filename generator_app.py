"""Desktop front end sharing the HTTP service's instrument worker."""
import argparse
import json
import os
import sys
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from generator_service import Controller, ROOT, create_server


def create_application():
    app = QtWidgets.QApplication(sys.argv[:1])
    for name in ("msyh.ttc", "segoeui.ttf"):
        font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name
        if font.exists():
            QtGui.QFontDatabase.addApplicationFont(str(font))
    app.setFont(QtGui.QFont("Microsoft YaHei", 10))
    app.setStyle("Fusion")
    app.setStyleSheet("QWidget{font-family:'Microsoft YaHei';font-size:13px} QPushButton{padding:8px} QLineEdit,QComboBox{padding:5px} QGroupBox{margin-top:12px;padding-top:12px}")
    return app


def display_number(value):
    try:
        number = float(value)
        return "高阻" if abs(number) >= 1e30 else f"{number:.8g}"
    except (ValueError, TypeError):
        return str(value)


class Window(QtWidgets.QMainWindow):
    def __init__(self, controller, endpoint):
        super().__init__()
        self.controller = controller
        self.last_task = None
        self.setWindowTitle("EDU33212A · 波形发生器控制")
        self.resize(1050, 820)
        body = QtWidgets.QWidget()
        self.setCentralWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        heading = QtWidgets.QLabel("波形发生器控制台")
        heading.setStyleSheet("font-size:24px;font-weight:600")
        layout.addWidget(heading)
        self.connection = QtWidgets.QLabel("尚未连接")
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        toolbar = QtWidgets.QHBoxLayout()
        for label, action in (("连接 / 重连", "connect"), ("立即刷新", "refresh")):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda checked=False, value=action: self.submit(value, {}))
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.table = QtWidgets.QTableWidget(2, 8)
        self.table.setHorizontalHeaderLabels(["通道", "输出", "波形", "频率 / Hz", "幅值", "偏置 / V", "负载 / Ω", "模式"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(115)
        layout.addWidget(self.table)
        self.sweep_status = QtWidgets.QLabel("扫频设置：等待仪器回读")
        self.sweep_status.setWordWrap(True)
        layout.addWidget(self.sweep_status)
        group = QtWidgets.QGroupBox("参数编辑 · 应用后输出保持关闭")
        form = QtWidgets.QGridLayout(group)
        self.channel = QtWidgets.QComboBox()
        self.channel.addItems(["CH1", "CH2"])
        self.channel.setCurrentIndex(1)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["定频波形", "连续正弦扫频"])
        self.waveform = QtWidgets.QComboBox()
        for text, value in (("正弦波", "SIN"), ("方波", "SQU"), ("斜坡", "RAMP"), ("脉冲", "PULS")):
            self.waveform.addItem(text, value)
        self.load = QtWidgets.QComboBox()
        for text, value in (("请选择实际负载", None), ("高阻", "INF"), ("50 Ω", "50")):
            self.load.addItem(text, value)
        self.spacing = QtWidgets.QComboBox()
        self.spacing.addItem("线性", "LIN")
        self.spacing.addItem("对数", "LOG")
        self.inputs = {}
        widgets = [("操作通道", self.channel), ("工作方式", self.mode), ("波形", self.waveform), ("实际负载", self.load)]
        for label, key in (("定频频率 / Hz", "frequency"), ("幅值 / Vpp", "amplitude"), ("直流偏置 / V", "offset"), ("扫频起点 / Hz", "start"), ("扫频终点 / Hz", "stop"), ("扫频时间 / s", "seconds")):
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText("明确输入参数")
            self.inputs[key] = field
            widgets.append((label, field))
        widgets.append(("扫频间隔", self.spacing))
        for index, (label, widget) in enumerate(widgets):
            row, column = divmod(index, 2)
            form.addWidget(QtWidgets.QLabel(label), row, column * 2)
            form.addWidget(widget, row, column * 2 + 1)
        buttons = QtWidgets.QHBoxLayout()
        apply = QtWidgets.QPushButton("应用参数（输出关闭）")
        apply.clicked.connect(self.configure)
        enable = QtWidgets.QPushButton("开启所选通道输出…")
        enable.clicked.connect(self.enable_output)
        disable = QtWidgets.QPushButton("关闭所选通道输出")
        disable.setStyleSheet("background:#b83535;color:white;font-weight:600")
        disable.clicked.connect(lambda: self.submit("output", {"channel": self.channel.currentIndex() + 1, "state": "off"}))
        for button in (apply, enable, disable):
            buttons.addWidget(button)
        form.addLayout(buttons, 6, 0, 1, 4)
        layout.addWidget(group)
        self.result = QtWidgets.QLabel("就绪。参数编辑区与仪器回读区分开显示。")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        footer = QtWidgets.QLabel(f"本地接口：{endpoint['url']}  |  状态约每 2 秒更新；显示设定值，不是实测波形。\n关闭窗口不会关闭仪器输出；需要停止信号时先点击关闭输出。")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.update_fields()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(300)

    def update_fields(self):
        sweep = self.mode.currentIndex() == 1
        self.waveform.setEnabled(not sweep)
        self.inputs["frequency"].setEnabled(not sweep)
        for name in ("start", "stop", "seconds"):
            self.inputs[name].setEnabled(sweep)
        self.spacing.setEnabled(sweep)

    def submit(self, action, parameters):
        try:
            task = self.controller.submit({"action": action, "parameters": parameters})
            self.last_task = task["id"]
            self.result.setText(f"任务已接收：{action}；等待执行。")
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "操作未提交", str(error))

    def configure(self):
        try:
            if self.load.currentData() is None:
                raise ValueError("请选择实际连接的负载")
            sweep = self.mode.currentIndex() == 1
            names = ("start", "stop", "seconds", "amplitude", "offset") if sweep else ("frequency", "amplitude", "offset")
            parameters = {name: float(self.inputs[name].text()) for name in names}
            parameters.update(channel=self.channel.currentIndex() + 1, load=self.load.currentData())
            parameters.update({"spacing": self.spacing.currentData()} if sweep else {"waveform": self.waveform.currentData()})
            self.submit("sweep" if sweep else "configure", parameters)
        except ValueError as error:
            QtWidgets.QMessageBox.warning(self, "参数不完整", f"请填写所有必需数值。\n{error}")

    def enable_output(self):
        state = self.controller.snapshot()
        if not state["connected"]:
            QtWidgets.QMessageBox.warning(self, "未连接", "请先连接仪器并检查回读设置")
            return
        channel = self.channel.currentIndex() + 1
        actual = state["device"]["channels"][str(channel)]
        description = json.dumps(actual, ensure_ascii=False, indent=2)
        reply = QtWidgets.QMessageBox.question(self, f"开启 CH{channel}", f"将按仪器当前设置开启输出，编辑框未应用的内容不会生效。\n请核对接线和实际负载。\n{description}")
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.submit("output", {"channel": channel, "state": "on"})

    def update_status(self):
        state = self.controller.snapshot()
        if state["connected"]:
            self.connection.setText(f"已连接 · {state['device']['identity']}\n回读时间（UTC）：{state['updated_at']}")
            self.connection.setStyleSheet("color:#16834b")
        else:
            self.connection.setText(f"已断开 / 状态可能过期 · {state['error']}")
            self.connection.setStyleSheet("color:#ba3333")
        if state["device"]:
            channels = state["device"]["channels"]
            for row, channel in enumerate(("1", "2")):
                values = channels[channel]
                cells = [f"CH{channel}", "开启" if values["output"] == "1" else "关闭", values["waveform"], display_number(values["frequency_hz"]), f"{display_number(values['amplitude'])} {values['amplitude_unit']}", display_number(values["offset_v"]), display_number(values["load_ohms"]), values["frequency_mode"]]
                for column, text in enumerate(cells):
                    self.table.setItem(row, column, QtWidgets.QTableWidgetItem(text))
            value = channels[str(self.channel.currentIndex() + 1)]
            self.sweep_status.setText(f"所选通道扫频回读：{display_number(value['sweep_start_hz'])} → {display_number(value['sweep_stop_hz'])} Hz；{display_number(value['sweep_time_s'])} s；{value['sweep_spacing']}；触发 {value['trigger_source']}")
        if self.last_task:
            task = self.controller.task(self.last_task)
            if task:
                labels = {"queued": "排队中", "running": "执行中", "succeeded": "执行成功，已回读", "failed": "执行失败", "cancelled": "已取消"}
                self.result.setText(f"{task['action']}：{labels.get(task['state'], task['state'])} {task['error'] or ''}")
        text = "\n".join(f"{event['time']} {event['message']}" for event in state["events"])
        if text != self.log.toPlainText():
            self.log.setPlainText(text)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run the same service without a desktop window")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    controller = Controller()
    try:
        server, endpoint = create_server(controller, args.port)
    except OSError:
        controller.stop()
        raise SystemExit("本地接口端口被占用；请检查上位机是否已启动。")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    endpoint_path = runtime / "endpoint.json"
    endpoint_path.write_text(json.dumps(endpoint), encoding="utf-8")
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    controller.submit({"action": "connect", "parameters": {}})
    try:
        if args.headless:
            server_thread.join()
        else:
            app = create_application()
            window = Window(controller, endpoint)
            window.show()
            app.exec()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        controller.stop()
        if endpoint_path.exists():
            endpoint_path.unlink()


if __name__ == "__main__":
    main()

