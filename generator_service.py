"""Single-owner instrument worker and loopback HTTP interface."""
import copy
import json
import logging
import math
import queue
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from edu33212a import Generator

ROOT = Path(__file__).resolve().parent


def validate_command(command):
    if not isinstance(command, dict) or set(command) != {"action", "parameters"}:
        raise ValueError("需要 action 和 parameters 两个字段")
    action, parameters = command["action"], command["parameters"]
    fields = {"connect": set(), "refresh": set(), "configure": {"channel", "waveform", "frequency", "amplitude", "offset", "load"}, "sweep": {"channel", "start", "stop", "seconds", "spacing", "amplitude", "offset", "load"}, "output": {"channel", "state"}}
    if not isinstance(action, str) or action not in fields or not isinstance(parameters, dict) or set(parameters) != fields[action]:
        raise ValueError("操作或参数不完整，或包含不支持的字段")
    if action in ("connect", "refresh"):
        return
    if type(parameters["channel"]) is not int or parameters["channel"] not in (1, 2):
        raise ValueError("通道必须是 1 或 2")
    if action == "output":
        if parameters["state"] not in ("on", "off"):
            raise ValueError("state 必须是 on/off")
        return
    if parameters["load"] not in ("50", "INF"):
        raise ValueError("负载必须明确选择 50 或 INF")
    numeric = ("frequency", "amplitude", "offset") if action == "configure" else ("start", "stop", "seconds", "amplitude", "offset")
    for name in numeric:
        value = parameters[name]
        if type(value) not in (int, float) or not math.isfinite(value) or (name != "offset" and value <= 0):
            raise ValueError(f"{name} 必须是有限数值，除偏置外必须大于零")
    if action == "configure" and parameters["waveform"] not in ("SIN", "SQU", "RAMP", "PULS"):
        raise ValueError("不支持此波形")
    if action == "sweep" and (parameters["spacing"] not in ("LIN", "LOG") or parameters["start"] == parameters["stop"]):
        raise ValueError("扫频方式必须是 LIN/LOG，起止频率不能相同")


class Controller:
    def __init__(self, factory=Generator, log_directory=None):
        self.factory = factory
        self.generator = None
        self.lock = threading.RLock()
        self.tasks = {}
        self.events = []
        self.state = {"connected": False, "updated_at": None, "error": "尚未连接", "device": None}
        self.commands = queue.PriorityQueue(maxsize=64)
        self.sequence = 0
        self.stopping = threading.Event()
        directory = log_directory or ROOT / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"generator.{uuid.uuid4().hex}")
        self.logger.setLevel(logging.INFO)
        self.handler = logging.FileHandler(directory / "operations.jsonl", encoding="utf-8")
        self.logger.addHandler(self.handler)
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({**self.state, "tasks": list(self.tasks.values())[-20:], "events": self.events[-30:]})

    def task(self, task_id):
        with self.lock:
            return copy.deepcopy(self.tasks.get(task_id))

    def submit(self, command):
        validate_command(command)
        with self.lock:
            if self.stopping.is_set():
                raise ValueError("程序正在退出")
            if self.commands.full():
                raise ValueError("任务队列已满")
            task_id = uuid.uuid4().hex
            self.sequence += 1
            task = {"id": task_id, "state": "queued", "action": command["action"], "parameters": copy.deepcopy(command["parameters"]), "result": None, "error": None}
            if command["action"] == "output" and command["parameters"]["state"] == "off":
                for pending in self.tasks.values():
                    if pending["state"] == "queued" and pending["parameters"].get("channel") == command["parameters"]["channel"]:
                        pending.update(state="cancelled", error="已被后续关闭输出请求取消")
            self.tasks[task_id] = task
            priority = 0 if command["action"] == "output" and command["parameters"]["state"] == "off" else 10
            self.commands.put_nowait((priority, self.sequence, task_id))
            for old_id in list(self.tasks)[:-256]:
                if self.tasks[old_id]["state"] in ("succeeded", "failed"):
                    del self.tasks[old_id]
            return copy.deepcopy(task)

    def record(self, message):
        event = {"time": datetime.now(timezone.utc).isoformat(), "message": message}
        with self.lock:
            self.events.append(event)
            self.events = self.events[-100:]
        self.logger.info(json.dumps(event, ensure_ascii=False))

    def refresh(self):
        device = self.generator.status()
        with self.lock:
            self.state = {"connected": True, "updated_at": datetime.now(timezone.utc).isoformat(), "error": None, "device": device}
        return device

    def disconnect(self, error):
        with self.lock:
            self.state.update(connected=False, error=str(error))
        if self.generator:
            try:
                self.generator.close()
            except Exception:
                pass
            self.generator = None

    def execute(self, action, parameters):
        if action == "connect":
            if self.generator is None:
                self.generator = self.factory()
            return self.refresh()
        if self.generator is None:
            raise RuntimeError("仪器未连接，请先连接")
        if action == "configure":
            self.generator.configure(**parameters)
        elif action == "sweep":
            self.generator.configure_sweep(**parameters)
        elif action == "output":
            channel = parameters["channel"]
            try:
                self.generator.write(f"OUTP{channel} {parameters['state'].upper()}")
                actual = self.generator.channel_status(channel)
                if actual["output"] != ("1" if parameters["state"] == "on" else "0"):
                    raise RuntimeError("输出开关回读不一致")
            except Exception:
                if parameters["state"] == "on":
                    try:
                        self.generator.write(f"OUTP{channel} OFF")
                    except Exception:
                        pass
                raise
        return self.refresh()

    def run(self):
        next_refresh = time.monotonic() + 2
        while not self.stopping.is_set():
            try:
                _, _, task_id = self.commands.get(timeout=0.2)
            except queue.Empty:
                if self.generator and time.monotonic() >= next_refresh:
                    try:
                        self.refresh()
                    except Exception as error:
                        self.disconnect(error)
                        self.record(f"连接中断：{error}")
                    next_refresh = time.monotonic() + 2
                continue
            with self.lock:
                task = self.tasks[task_id]
                if task["state"] == "cancelled":
                    continue
                task["state"] = "running"
            try:
                result = self.execute(task["action"], task["parameters"])
                with self.lock:
                    task.update(state="succeeded", result=result)
                self.record(f"{task['action']} 成功：{json.dumps(task['parameters'], ensure_ascii=False)}")
            except Exception as error:
                with self.lock:
                    task.update(state="failed", error=str(error))
                self.record(f"{task['action']} 失败：{error}")
                try:
                    if self.generator:
                        self.refresh()
                    else:
                        with self.lock:
                            self.state.update(connected=False, error=str(error))
                except Exception as refresh_error:
                    self.disconnect(refresh_error)
            next_refresh = time.monotonic() + 2
        self.disconnect("上位机已退出")

    def stop(self):
        self.stopping.set()
        self.worker.join(timeout=8)
        self.handler.close()


def create_server(controller, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, code, value):
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if self.headers.get("Origin") or not secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.respond(403, {"error": "禁止访问"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path == "/status":
                self.respond(200, controller.snapshot())
            elif self.path.startswith("/tasks/"):
                task = controller.task(self.path.split("/")[-1])
                self.respond(200 if task else 404, task or {"error": "任务不存在"})
            else:
                self.respond(404, {"error": "接口不存在"})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != "/commands":
                self.respond(404, {"error": "接口不存在"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("请求大小不合法")
                self.connection.settimeout(5)
                command = json.loads(self.rfile.read(length))
                self.respond(202, controller.submit(command))
            except (ValueError, TypeError, TimeoutError) as error:
                self.respond(400, {"error": str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, {"url": f"http://127.0.0.1:{server.server_port}", "token": token}

