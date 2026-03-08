"""
分镜自动生成脚本 — 远洋游轮豪华套房
1. 设计 6 张分镜静帧 Prompt
2. 逐帧调用 /api/image/create (v2 纯文生图) 生成图片
3. 读取图片文件转为 base64
4. 调用 /api/video/keyframe-i2v 生成最终视频

Usage:
    python samplefolder/storyboard_generate.py
"""

import base64
import json
import sys
import time
from pathlib import Path

import requests

# ── 配置 ──────────────────────────────────────────────────────

BASE_URL = "http://127.0.0.1:5678"
POLL_INTERVAL = 5       # 秒
IMAGE_TIMEOUT = 300     # 单张图片最长等待秒数
VIDEO_TIMEOUT = 1800    # 视频生成最长等待秒数

# ── 6 张分镜静帧 Prompt ───────────────────────────────────────
#
# 场景: 远洋游轮豪华套房 (1930s Art Deco Ocean Liner Luxury Suite)
# 叙事: 男士开门 → 镜头独自进入房间

FRAME_PROMPTS = [
    # Frame 1 — 首帧：男士站在舱门外，手握门把
    (
        "A man in a dark navy double-breasted wool suit stands on the exterior teak deck of a 1930s Art Deco ocean liner, "
        "hand resting on an ornate circular brass porthole door with polished rivets, "
        "overcast Atlantic grey daylight, slight ocean mist, teakwood deck planks, "
        "brass handrail visible at left, shot from slightly low angle at eye level, "
        "cinematic 4K, shallow depth of field, 35mm prime lens, muted cool exterior palette"
    ),

    # Frame 2 — 门半开，男士侧身退开，暖光溢出
    (
        "A man in a dark navy double-breasted suit stepping sideways away from a circular brass porthole door, "
        "door swinging open 40 degrees, warm amber golden interior light spilling through the gap onto grey teak deck planks, "
        "strong contrast between cool overcast exterior daylight and warm 3200K interior glow, "
        "Art Deco brass riveted door edge filling left quarter of frame, "
        "cinematic 4K, 35mm lens, color temperature split: 5600K exterior / 3200K interior, dramatic chiaroscuro"
    ),

    # Frame 3 — 门全开，男士退出画面，镜头在门槛处
    (
        "Interior threshold view of a 1930s Art Deco ocean liner luxury suite: circular brass porthole door frame "
        "filling the screen edges, door held fully open, warm amber glow beyond threshold, "
        "Art Deco geometric wool carpet pattern visible on the cabin floor just inside, "
        "man's sleeve barely visible at right frame edge as he steps aside, "
        "camera positioned exactly at doorway threshold looking inward, "
        "cinematic 4K, 24mm wide lens, deep foreground brass door frame, warm interior bokeh"
    ),

    # Frame 4 — 镜头越过门槛，进入舱室，门框在边缘
    (
        "Inside a 1930s Art Deco ocean liner luxury suite looking toward the cabin interior: "
        "circular brass riveted porthole door frame at all four screen edges, camera just crossed the threshold, "
        "Art Deco geometric wool Persian carpet in navy and gold filling the floor, "
        "polished mahogany wall paneling with brass accent strips, small brass wall sconces glowing 3200K, "
        "deep blue velvet sofa partially visible mid-distance, "
        "cinematic 4K, ultra-wide 18mm lens, warm amber interior light, vignette at frame edges"
    ),

    # Frame 5 — 镜头推至房间中部，沙发与圆舷窗清晰可见
    (
        "Mid-cabin interior of a 1930s Art Deco ocean liner luxury suite: "
        "camera at waist height gliding forward, deep blue velvet Chesterfield sofa with brass stud trim centered, "
        "low polished brass and mahogany cocktail table with crystal ashtray and silver cigarette case, "
        "circular steel porthole window at far wall showing steel-grey Atlantic ocean, "
        "hand-painted tropical flamingo mural on mahogany panels, brass ceiling light fixture, "
        "Art Deco geometric carpet below, wool Persian area rug under sofa, "
        "cinematic 4K, 35mm lens, warm golden 3200K lamplight, slight motion blur from camera dolly"
    ),

    # Frame 6 — 尾帧：完整内景 master shot
    (
        "Art Deco 1930s ocean liner luxury cabin suite, full interior master shot: "
        "deep navy blue velvet Chesterfield sofa with polished brass nail-head trim, "
        "low oval mahogany cocktail table with silver ice bucket and crystal glasses, "
        "hand-painted tropical bird mural on lacquered mahogany panels, "
        "circular bronze porthole window with steel-grey Atlantic ocean view, "
        "Persian wool carpet in navy gold cream geometric pattern, "
        "brass floor-level accent trim, silk lampshade side lamp on mahogany end table, "
        "small brass telescope on a tripod beside the porthole, "
        "leather-bound travel books stacked beside the lamp, a single white orchid in a crystal vase, "
        "warm golden interior 3200K lamplight, no people, cinematic 4K Panavision, "
        "ultra-detailed ultra-realistic photography"
    ),
]

# ── 5 段 I2V 运动 Prompt（帧间过渡）────────────────────────────
# 每段描述相邻两帧之间的镜头运动

SEGMENT_PROMPTS = [
    # Seg 1: Frame1 → Frame2
    (
        "Man's gloved hand grips ornate circular brass door handle, slowly pulling the heavy porthole door open, "
        "golden interior light begins to spill across grey teak deck planks, "
        "man starts stepping backward and sideways, door swings smoothly outward, "
        "warm amber glow grows as door opening widens, gentle ocean mist, cinematic slow motion"
    ),

    # Seg 2: Frame2 → Frame3
    (
        "Man steps fully aside and exits frame right, circular brass porthole door swings to fully open position, "
        "camera begins slow forward dolly push toward the open doorway, "
        "warm amber interior light floods the threshold, "
        "Art Deco carpet pattern inside comes into view, brass riveted door frame fills screen edges, "
        "smooth cinematic forward movement, 24fps"
    ),

    # Seg 3: Frame3 → Frame4
    (
        "Camera glides forward through the circular brass porthole doorway threshold, "
        "brass riveted door frame sweeps past the edges of frame, "
        "Art Deco geometric wool carpet rises from below as camera crosses into the cabin, "
        "color temperature shifts from cool 5600K exterior daylight to warm 3200K interior amber glow, "
        "smooth seamless dolly push, no cuts, cinematic"
    ),

    # Seg 4: Frame4 → Frame5
    (
        "Camera continues smooth dolly push deeper into the Art Deco ocean liner cabin, "
        "porthole door frame slides off the edges of frame behind, "
        "deep blue velvet Chesterfield sofa comes into focus ahead, "
        "polished brass cocktail table gleams under warm lamplight, "
        "circular steel porthole window with Atlantic ocean view draws the eye, "
        "slow majestic forward movement, warm lamplight, 24fps"
    ),

    # Seg 5: Frame5 → Frame6
    (
        "Camera slows its forward dolly, gently settling into master shot framing of the full cabin interior, "
        "deep blue velvet sofa centered, brass fixtures gleaming, circular ocean porthole at far wall, "
        "Persian carpet and mahogany paneling fill the frame, "
        "camera comes to a smooth complete stop revealing the entire Art Deco luxury suite, "
        "warm golden 3200K lamplight, cinematic final reveal shot"
    ),
]

# ── 公共负向提示 ─────────────────────────────────────────────

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, ugly, duplicate, "
    "text, watermark, signature, modern furniture, cartoon, anime, "
    "overexposed, underexposed, noise"
)

# 1×1 白色 PNG (如服务器 v2 模式仍要求 input_image 则用此占位)
_BLANK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIA"
    "BQAABjE+ibYAAAAASUVORK5CYII="
)


# ── 工具函数 ─────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def poll_job(job_id: str, timeout: int = IMAGE_TIMEOUT) -> dict:
    """轮询 /api/jobs/{job_id} 直到状态为 done 或 error，返回 job 元数据"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)
        r.raise_for_status()
        meta = r.json()
        status = meta.get("status", "")
        if status == "done":
            return meta
        if status == "error":
            raise RuntimeError(f"Job {job_id} failed: {meta.get('error', meta.get('result', ''))}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def image_to_b64(file_path: str) -> str:
    """读取图片文件并返回 base64 字符串"""
    data = Path(file_path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def create_image(prompt: str, frame_index: int) -> str:
    """调用 /api/image/create，返回生成图片的 base64"""
    log(f"  → 提交 Frame {frame_index + 1} 生成请求...")
    payload = {
        "positive_prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "workflow_version": "v2",   # 纯文生图
        "input_image": _BLANK_PNG_B64,  # 占位：部分服务端版本要求传此字段
        "seed": None,
    }
    r = requests.post(f"{BASE_URL}/api/image/create", json=payload, timeout=15)
    r.raise_for_status()
    job_id = r.json()["job_id"]
    log(f"  → Frame {frame_index + 1} job_id={job_id}，等待完成...")

    meta = poll_job(job_id, timeout=IMAGE_TIMEOUT)
    result = meta.get("result") or {}

    file_path = result.get("file_path", "")
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"Frame {frame_index + 1}: file_path 无效 ({file_path!r})\nmeta={json.dumps(meta, ensure_ascii=False, indent=2)}")

    log(f"  ✓ Frame {frame_index + 1} 完成: {file_path}")
    return image_to_b64(file_path)


# ── 主流程 ───────────────────────────────────────────────────

def main() -> None:
    log("=" * 60)
    log("分镜自动生成 — 远洋游轮豪华套房")
    log("=" * 60)

    # 1. 检查服务器连通性
    try:
        r = requests.get(f"{BASE_URL}/api/jobs", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 无法连接服务器 {BASE_URL}: {e}", file=sys.stderr)
        sys.exit(1)
    log("服务器连接正常 ✓")

    # 2. 逐帧生成图片
    log(f"\n─── 阶段 1: 生成 {len(FRAME_PROMPTS)} 张分镜静帧 ───")
    images_b64: list[str] = []
    for i, prompt in enumerate(FRAME_PROMPTS):
        log(f"\nFrame {i + 1}/{len(FRAME_PROMPTS)}")
        log(f"  Prompt: {prompt[:80]}...")
        b64 = create_image(prompt, i)
        images_b64.append(b64)
        log(f"  图片大小: {len(b64) // 1024} KB (base64)")

    log(f"\n✓ 全部 {len(images_b64)} 张图片生成完毕")

    # 3. 调用 6 帧关键帧 I2V 接口
    log("\n─── 阶段 2: 提交 6-keyframe I2V 视频生成 ───")
    log(f"分辨率: 720×720, 帧数: 25, FPS: 24")

    video_payload = {
        "images": images_b64,        # 6 张图片 base64
        "prompts": SEGMENT_PROMPTS,  # 5 段运动描述
        "negative_prompt": NEGATIVE_PROMPT,
        "width": 720,
        "height": 720,
        "length": 25,
        "fps": 24,
        "seed": None,
    }

    r = requests.post(f"{BASE_URL}/api/video/keyframe-i2v", json=video_payload, timeout=30)
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
