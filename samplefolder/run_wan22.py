#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import uuid
from urllib import request, error


def http_json(url, method="GET", payload=None, timeout=30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_workflow(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_overrides(workflow, positive=None, negative=None, width=None, height=None, length=None, fps=None, seed=None):
    if positive is not None and "99" in workflow:
        workflow["99"]["inputs"]["text"] = positive
    if negative is not None and "91" in workflow:
        workflow["91"]["inputs"]["text"] = negative
    if width is not None and "104" in workflow:
        workflow["104"]["inputs"]["width"] = int(width)
    if height is not None and "104" in workflow:
        workflow["104"]["inputs"]["height"] = int(height)
    if length is not None and "104" in workflow:
        workflow["104"]["inputs"]["length"] = int(length)
    if fps is not None and "100" in workflow:
        workflow["100"]["inputs"]["fps"] = int(fps)

    if seed is not None:
        if "96" in workflow:
            workflow["96"]["inputs"]["noise_seed"] = int(seed)
        if "95" in workflow:
            workflow["95"]["inputs"]["noise_seed"] = 0


def submit(base_url, workflow):
    payload = {
        "prompt": workflow,
        "client_id": str(uuid.uuid4()),
    }
    return http_json(f"{base_url.rstrip('/')}/prompt", method="POST", payload=payload)


def wait_done(base_url, prompt_id, poll_interval, timeout_sec):
    start = time.time()
    base_url = base_url.rstrip("/")
    while True:
        queue = http_json(f"{base_url}/queue")
        history = http_json(f"{base_url}/history/{prompt_id}")

        in_running = any((len(item) > 1 and item[1] == prompt_id) for item in queue.get("queue_running", []))
        in_pending = any((len(item) > 1 and item[1] == prompt_id) for item in queue.get("queue_pending", []))
        elapsed = int(time.time() - start)

        state = "running" if in_running else ("pending" if in_pending else "unknown")
        print(f"[{elapsed}s] state={state} running={len(queue.get('queue_running', []))} pending={len(queue.get('queue_pending', []))}")

        if prompt_id in history:
            print("done")
            print(json.dumps(history[prompt_id], ensure_ascii=False, indent=2))
            return 0

        if timeout_sec > 0 and (time.time() - start) >= timeout_sec:
            print("timeout", file=sys.stderr)
            return 2

        time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="Run Wan2.2 non-LoRA workflow on remote ComfyUI")
    parser.add_argument("--base-url", default="http://43.136.21.177:8555", help="Remote ComfyUI base URL")
    parser.add_argument("--workflow", default="/home/ubuntu/video_pipeline_e2e/workflows/wan22_t2v_non_lora_api.json", help="Workflow API JSON path")
    parser.add_argument("--positive", default=None, help="Override positive prompt")
    parser.add_argument("--negative", default=None, help="Override negative prompt")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--length", type=int, default=None, help="Video frame count")
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--wait", action="store_true", help="Wait until finished")
    parser.add_argument("--poll-interval", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=0, help="Seconds, 0 means no timeout")

    args = parser.parse_args()

    if not os.path.exists(args.workflow):
        print(f"Workflow not found: {args.workflow}", file=sys.stderr)
        return 1

    try:
        workflow = load_workflow(args.workflow)
        apply_overrides(
            workflow,
            positive=args.positive,
            negative=args.negative,
            width=args.width,
            height=args.height,
            length=args.length,
            fps=args.fps,
            seed=args.seed,
        )

        result = submit(args.base_url, workflow)
        prompt_id = result.get("prompt_id")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if not prompt_id:
            print("No prompt_id in response", file=sys.stderr)
            return 1

        if args.wait:
            return wait_done(args.base_url, prompt_id, args.poll_interval, args.timeout)

        print(f"submitted prompt_id={prompt_id}")
        print(f"check: {args.base_url.rstrip('/')}/history/{prompt_id}")
        return 0

    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTPError {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
