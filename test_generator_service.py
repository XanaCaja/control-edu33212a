import json
import uuid
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from generator_client import request
from generator_service import Controller, create_server, validate_command


class FakeGenerator:
    def __init__(self):
        self.outputs = {1: "0", 2: "0"}
        self.owners = set()
        self.fail = False

    def status(self):
        self.owners.add(threading.get_ident())
        if self.fail:
            raise RuntimeError("USB disconnected")
        return {"identity": "Keysight,EDU33212A,YOUR_DEVICE_SERIAL", "channels": {str(channel): self.channel_status(channel) for channel in (1, 2)}}

    def channel_status(self, channel):
        return {"output": self.outputs[channel]}

    def write(self, command):
        self.owners.add(threading.get_ident())
        if self.fail:
            raise RuntimeError("USB disconnected")
        self.outputs[int(command[4])] = "1" if command.endswith("ON") else "0"

    def close(self):
        pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeGenerator()
        directory = Path(__file__).resolve().parent / ".cache" / "tests" / uuid.uuid4().hex
        self.controller = Controller(lambda: self.device, directory)

    def tearDown(self):
        self.controller.stop()

    def wait(self, task):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            value = self.controller.task(task["id"])
            if value["state"] not in ("queued", "running"):
                return value
            time.sleep(0.01)
        self.fail("Worker timeout")

    def submit(self, action, parameters):
        return self.wait(self.controller.submit({"action": action, "parameters": parameters}))

    def test_shared_worker_and_readback(self):
        self.assertEqual(self.submit("connect", {})["state"], "succeeded")
        self.assertEqual(self.device.outputs[2], "0")
        result = self.submit("output", {"channel": 2, "state": "on"})
        self.assertEqual(result["result"]["channels"]["2"]["output"], "1")
        self.submit("output", {"channel": 2, "state": "off"})
        self.assertEqual(self.device.outputs, {1: "0", 2: "0"})
        self.assertEqual(len(self.device.owners), 1)

    def test_disconnected_output_fails(self):
        result = self.submit("output", {"channel": 2, "state": "on"})
        self.assertEqual(result["state"], "failed")
        self.submit("connect", {})
        self.device.fail = True
        self.assertEqual(self.submit("refresh", {})["state"], "failed")
        self.assertFalse(self.controller.snapshot()["connected"])

    def test_bad_parameters_rejected_before_queue(self):
        for command in ({"action": "raw", "parameters": {}}, {"action": "output", "parameters": {"channel": 3, "state": "on"}}, {"action": "configure", "parameters": {"channel": 2, "waveform": "SIN", "frequency": float("nan"), "amplitude": 1, "offset": 0, "load": "INF"}}):
            with self.assertRaises(ValueError):
                validate_command(command)

    def test_off_cancels_pending_channel_commands(self):
        with self.controller.lock:
            pending = self.controller.submit({"action": "output", "parameters": {"channel": 2, "state": "on"}})
            off = self.controller.submit({"action": "output", "parameters": {"channel": 2, "state": "off"}})
            self.assertEqual(self.controller.task(pending["id"])["state"], "cancelled")
        self.wait(off)
        self.assertEqual(self.device.outputs[2], "0")

    def test_http_auth_and_task_lifecycle(self):
        server, endpoint = create_server(self.controller, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as denied:
                urlopen(endpoint["url"] + "/status")
            self.assertEqual(denied.exception.code, 403)
            task = request(endpoint, "/commands", {"action": "connect", "parameters": {}})
            self.wait(task)
            self.assertEqual(request(endpoint, f"/tasks/{task['id']}")["state"], "succeeded")
            self.assertTrue(request(endpoint, "/status")["connected"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

