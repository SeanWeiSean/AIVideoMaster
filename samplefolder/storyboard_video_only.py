"""
仅调用 /api/video/keyframe-i2v —— 使用已生成的 6 张分镜图片

运行前需先重启服务器 (server.py) 以加载新的 keyframe-i2v 路由。

Usage:
    python samplefolder/storyboard_video_only.py [image1.png image2.png ... image6.png]

  不传参数时自动使用最新生成的 6 张 output/images/create_*.png
"""

import base64
import glob
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:5678"
POLL_INTERVAL = 5
VIDEO_TIMEOUT = 1800

# ── 5 段 I2V 运动 Prompt（与 storyboard_generate.py 保持一致）──────────

SEGMENT_PROMPTS = [
    (
        "Man's gloved hand grips ornate circular brass door handle, slowly pulling the heavy porthole door open, "
        "golden interior light begins to spill across grey teak deck planks, "
        "man starts stepping backward and sideways, door swings smoothly outward, "
        "warm amber glow grows as door opening widens, gentle ocean mist, cinematic slow motion"
    ),
    (
        "Man steps fully aside and exits frame right, circular brass porthole door swings to fully open position, "
        "camera begins slow forward dolly push toward the open doorway, "
        "warm amber interior light floods the threshold, "
        "Art Deco carpet pattern inside comes into view, brass riveted door frame fills screen edges, "
        "smooth cinematic forward movement, 24fps"
    ),
    (
        "Camera glides forward through the circular brass porthole doorway threshold, "
        "brass riveted door frame sweeps past the edges of frame, "
        "Art Deco geometric wool carpet rises from below as camera crosses into the cabin, "
        "color temperature shifts from cool 5600K exterior daylight to warm 3200K interior amber glow, "
        "smooth seamless dolly push, no cuts, cinematic"
    ),
    (
        "Camera continues smooth dolly push deeper into the Art Deco ocean liner cabin, "
        "porthole door frame slides off the edges of frame behind, "
        "deep blue velvet Chesterfield sofa comes into focus ahead, "
        "polished brass cocktail table gleams under warm lamplight, "
        "circular steel porthole window with Atlantic ocean view draws the eye, "
        "slow majestic forward movement, warm lamplight, 24fps"
    ),
    (
        "Camera slows its forward dolly, gently settling into master shot framing of the full cabin interior, "
        "deep blue velvet sofa centered, brass fixtures gleaming, circular ocean porthole at far wall, "
        "Persian carpet and mahogany paneling fill the frame, "
        "camera comes to a smooth complete stop revealing the entire Art Deco luxury suite, "
        "warm golden 3200K lamplight, cinematic final reveal shot"
    ),
]

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, ugly, duplicate, "
    "text, watermark, signature, modern furniture, cartoon, anime, "
    "overexposed, underexposed, noise"
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def poll_job(job_id: str, timeout: int = VIDEO_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)
        r.raise_for_status()
        meta = r.json()
        status = meta.get("status", "")
        log(f"  状态: {status}")
        if status == "done":
            return meta
        if status == "error":
            raise RuntimeError(f"Job {job_id} failed: {meta.get('error', meta.get('result', ''))}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def image_to_b64(file_path: str | Path) -> str:
    data = Path(file_path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def find_latest_6_images() -> list[Path]:
    """找最近生成的 6 张 create_*.png"""
    pattern = str(Path("output/images/create_*.png"))
    files = sorted(glob.glob(pattern))
    if len(files) < 6:
        raise FileNotFoundError(
            f"output/images/ 中只找到 {len(files)} 张 create_*.png，需要至少 6 张"
        )
    # 取最新的 6 张（按文件名排序，最后 6 个）
    return [Path(f) for f in files[-6:]]


def main() -> None:
    log("=" * 60)
    log("6-Keyframe I2V 视频生成（使用已有图片）")
    log("=" * 60)

    # 1. 确定图片路径
    if len(sys.argv) >= 7:
        image_paths = [Path(p) for p in sys.argv[1:7]]
        log(f"使用命令行指定的 6 张图片")
    else:
        image_paths = find_latest_6_images()
        log(f"自动选取最新的 6 张图片:")

    for i, p in enumerate(image_paths, 1):
        if not p.exists():
            print(f"[ERROR] 图片不存在: {p}", file=sys.stderr)
            sys.exit(1)
        log(f"  Frame {i}: {p}")

    # 2. 读取为 base64
    log("\n加载图片为 base64...")
    images_b64 = [image_to_b64(p) for p in image_paths]
    total_kb = sum(len(b) for b in images_b64) // 1024
    log(f"共 {total_kb} KB base64 数据")

    # 3. 检查服务器
    try:
        r = requests.get(f"{BASE_URL}/api/jobs", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 无法连接服务器 {BASE_URL}: {e}", file=sys.stderr)
        sys.exit(1)
    log("服务器连接正常 ✓")

    # 4. 调用 keyframe-i2v
    log("\n─── 提交 6-keyframe I2V 视频生成 ───")
    log("分辨率: 720×720, 帧数: 25, FPS: 24")

    video_payload = {
        "images": images_b64,
        "prompts": SEGMENT_PROMPTS,
        "negative_prompt": NEGATIVE_PROMPT,
        "width": 720,
        "height": 720,
        "length": 25,
        "fps": 24,
        "seed": None,
    }

    log("发送请求（数据量较大，请稍候）...")
    r = requests.post(f"{BASE_URL}/api/video/keyframe-i2v", json=video_payload, timeout=60)
    r.raise_for_status()
    resp = r.json()
    video_job_id = resp.get("job_id", "")
    log(f"视频 job_id={video_job_id}，等待完成（最长 {VIDEO_TIMEOUT // 60} 分钟）...")

    meta = poll_job(video_job_id, timeout=VIDEO_TIMEOUT)
    result = meta.get("result") or {}
    video_path = result.get("file_path", "")

    log("\n" + "=" * 60)
    log("✓ 视频生成完成！")
    log(f"  输出路径: {video_path}")
    log("=" * 60)


if __name__ == "__main__":
    main()
