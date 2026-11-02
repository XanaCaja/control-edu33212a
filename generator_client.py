"""Skill/CLI client: talks only to the running host, never opens VISA."""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(endpoint, route, payload=None):
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
    req = urllib.request.Request(endpoint["url"] + route, data=data, headers={"Authorization": f"Bearer {endpoint['token']}", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode("utf-8", errors="replace")) from error


def main():
    parser = argparse.ArgumentParser(description="Control EDU33212A through its local desktop host")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("EDU33212A_HOME", str(Path(__file__).resolve().parent))))
    parser.add_argument("--timeout", type=float, default=60)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    actions.add_parser("connect")
    actions.add_parser("refresh")
    task = actions.add_parser("task")
    task.add_argument("id")
    send = actions.add_parser("send")
    content = send.add_mutually_exclusive_group(required=True)
    content.add_argument("--json")
    content.add_argument("--file", type=Path)
    args = parser.parse_args()
    try:
        endpoint = json.loads((args.home / ".runtime" / "endpoint.json").read_text(encoding="utf-8"))
        if args.action == "status":
            result = request(endpoint, "/status")
        elif args.action == "task":
            result = request(endpoint, f"/tasks/{args.id}")
        else:
            if args.action == "send":
                command = json.loads(args.file.read_text(encoding="utf-8-sig") if args.file else args.json)
            else:
                command = {"action": args.action, "parameters": {}}
            result = request(endpoint, "/commands", command)
            deadline = time.monotonic() + args.timeout
            while result["state"] in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(0.15)
                result = request(endpoint, f"/tasks/{result['id']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("state") not in ("failed", "cancelled", "queued", "running") else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error), "hint": "确认上位机已启动；任务超时不代表未执行，请查询原任务，不要盲目重试。"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

