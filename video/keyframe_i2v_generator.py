"""
KeyframeI2VGenerator — ComfyUI 6关键帧视频生成客户端

通过 ComfyUI API 提交 Wan2.2 6关键帧 I2V 工作流：
  1. 上传 6 张关键帧图片到 ComfyUI input 目录
  2. 注入每段的 prompt、种子、尺寸参数
  3. 提交工作流 → 轮询任务状态 → 下载合成视频

工作流特征：
  - 5 段独立 WanFirstLastFrameToVideo 分段生成（帧1→2, 2→3, 3→4, 4→5, 5→6）
  - 每段 4步 LightX2V LoRA 加速采样（高噪声+低噪声双阶段）
  - 所有段的输出帧通过 ImageBatch 链式拼接
  - 最终 CreateVideo (24fps) + SaveVideo 输出完整视频

关键节点映射：
  "62"         — LoadImage  帧1（首帧）
  "122"        — LoadImage  帧2
  "124"        — LoadImage  帧3
  "126"        — LoadImage  帧4
  "128"        — LoadImage  帧5
  "130"        — LoadImage  帧6（尾帧）

  每段前缀 p ∈ {140, 141, 142, 143, 144}：
  "{p}:6"      — CLIPTextEncode 正向 prompt
  "{p}:7"      — CLIPTextEncode 反向 prompt（已内置默认）
  "{p}:57"     — KSamplerAdvanced Pass1（noise_seed）
  "{p}:67"     — WanFirstLastFrameToVideo（width, height, length）

  "145"        — CreateVideo（fps）
  "146"        — SaveVideo（filename_prefix）
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from video.generator import ComfyUIClient


_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

# ── 工作流文件路径 ────────────────────────────────────────────

_WORKFLOW_FILE = "wan2.2/wan22_6keyframe_i2v.json"

# ── 6帧配置映射 ───────────────────────────────────────────────

# 6 个 LoadImage 节点 ID（顺序对应帧1~帧6）
_LOAD_IMAGE_NODES = ["62", "122", "124", "126", "128", "130"]

# 5 个分段前缀（每段负责相邻两帧之间的视频生成）
# seg_i: frames[i] → frames[i+1]
_SEGMENT_PREFIXES = ["140", "141", "142", "143", "144"]

# 输出节点
_OUTPUT_NODE = "146"   # SaveVideo
_FPS_NODE    = "145"   # CreateVideo


DEFAULT_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
    "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
    "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
    "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)


@dataclass
class KeyframeI2VJob:
    """6关键帧视频生成任务结果"""
    job_id: str
    status: str         # "pending" | "running" | "success" | "failed"
    file_path: str = ""
    error: str = ""


class KeyframeI2VGenerator:
    """通过 ComfyUI + Wan2.2 6关键帧 I2V 工作流生成分段视频

    输入 6 张关键帧图片和每段的提示词，输出一段拼接后的完整视频。
    每段对应相邻两帧之间的过渡动画。
    """

    def __init__(self, comfyui_url: str, output_dir: str = "./output") -> None:
        self.client = ComfyUIClient(comfyui_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._base_workflow = self._load_workflow()

    def _load_workflow(self) -> dict:
        wf_path = _WORKFLOWS_DIR / _WORKFLOW_FILE
        if not wf_path.is_file():
            raise FileNotFoundError(f"6关键帧工作流文件不存在: {wf_path}")
        with open(wf_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_connection(self) -> bool:
        return self.client.is_alive()

    # ── 主入口 ────────────────────────────────────────────────

    def generate(
        self,
        images_b64: list[str],
        prompts: list[str],
        *,
        negative_prompt: str = "",
        width: int = 720,
        height: int = 720,
        length: int = 25,
        seed: int | None = None,
        fps: int = 24,
        output_name: str = "",
    ) -> KeyframeI2VJob:
        """
        6关键帧视频生成：上传6张图 → 注入5段提示词 → 提交 → 等待 → 下载。

        Args:
            images_b64:       6 张关键帧图片的 base64 编码列表（不含 data: 前缀）
            prompts:          5 段提示词列表（每段对应相邻两帧之间的运动描述）
                              长度不足5时用空字符串补齐，超出5时截断
            negative_prompt:  反向提示词，留空使用内置默认
            width:            视频宽度（默认 720）
            height:           视频高度（默认 720）
            length:           每段帧数（默认 25 = ~1.5秒 @16fps）
            seed:             随机种子，None 自动生成；每段种子递增
            fps:              最终合成视频帧率（默认 24）
            output_name:      输出文件名（不含路径），留空自动生成
        """
        if len(images_b64) != 6:
            raise ValueError(f"images_b64 必须包含 6 张图片，实际收到 {len(images_b64)} 张")

        job_id = uuid.uuid4().hex[:12]
        if not output_name:
            output_name = f"kf6_i2v_{job_id}.mp4"

        job = KeyframeI2VJob(job_id=job_id, status="running")

        try:
            # Step 1: 上传 6 张关键帧图片
            print(f"[KF6-I2V] 上传 6 张关键帧图片...")
            uploaded_names: list[str] = []
            for i, img_b64 in enumerate(images_b64):
                fname = f"kf6_{job_id}_frame{i+1}.png"
                server_name = self._upload_image(img_b64, fname)
                uploaded_names.append(server_name)
                print(f"[KF6-I2V]   帧{i+1} → {server_name}")

            # Step 2: 标准化 prompts（确保长度为5）
            seg_prompts = list(prompts[:5]) + [""] * max(0, 5 - len(prompts))

            # Step 3: 生成种子
            base_seed = seed if seed is not None else int(time.time() * 1000) % (2 ** 53)
            actual_neg = negative_prompt or DEFAULT_NEGATIVE

            # Step 4: 构建工作流
            workflow = self._build_workflow(
                image_filenames=uploaded_names,
                seg_prompts=seg_prompts,
                negative_prompt=actual_neg,
                width=width,
                height=height,
                length=length,
                base_seed=base_seed,
                fps=fps,
                output_prefix=f"video/kf6_{job_id}",
            )

            print(f"[KF6-I2V] 参数: {width}x{height}, 每段{length}帧, fps={fps}, 基础种子={base_seed}")
            print(f"[KF6-I2V] 段落提示词:")
            for i, p in enumerate(seg_prompts):
                print(f"[KF6-I2V]   段{i+1}: {p[:80] or '(empty)'}")

            # Step 5: 提交工作流
            prompt_id = self.client.submit_workflow(workflow)
            print(f"[KF6-I2V] 已提交 prompt_id={prompt_id}")

            # Step 6: 轮询等待
            task_data = self._wait_for_completion(prompt_id)

            # Step 7: 下载视频
            output_path = str(self.output_dir / output_name)
            self._download_output(task_data, output_path)

            job.status = "success"
            job.file_path = output_path
            print(f"[KF6-I2V] ✅ 视频已保存: {output_path}")

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            print(f"[KF6-I2V] ❌ 生成失败: {e}")

        return job

    # ── 内部方法 ──────────────────────────────────────────────

    def _upload_image(self, image_b64: str, filename: str) -> str:
        """base64 → bytes → 上传到 ComfyUI，返回服务器端文件名"""
        image_data = base64.b64decode(image_b64)
        return self.client.upload_image(image_data, filename)

    def _build_workflow(
        self,
        image_filenames: list[str],
        seg_prompts: list[str],
        negative_prompt: str,
        width: int,
        height: int,
        length: int,
        base_seed: int,
        fps: int,
        output_prefix: str,
    ) -> dict:
        """深拷贝工作流模板并注入所有参数"""
        wf = json.loads(json.dumps(self._base_workflow))

        # 注入 6 张图片文件名到 LoadImage 节点
        for node_id, filename in zip(_LOAD_IMAGE_NODES, image_filenames):
            wf[node_id]["inputs"]["image"] = filename

        # 注入 5 段参数
        for i, prefix in enumerate(_SEGMENT_PREFIXES):
            # 正向提示词
            wf[f"{prefix}:6"]["inputs"]["text"] = seg_prompts[i]

            # 反向提示词（覆盖默认）
            wf[f"{prefix}:7"]["inputs"]["text"] = negative_prompt

            # 视频尺寸 & 帧数（WanFirstLastFrameToVideo）
            i2v_node = wf[f"{prefix}:67"]["inputs"]
            i2v_node["width"] = width
            i2v_node["height"] = height
            i2v_node["length"] = length

            # 种子（KSamplerAdvanced Pass1）
            wf[f"{prefix}:57"]["inputs"]["noise_seed"] = base_seed + i

        # FPS
        wf[_FPS_NODE]["inputs"]["fps"] = fps

        # 输出文件名前缀
        wf[_OUTPUT_NODE]["inputs"]["filename_prefix"] = output_prefix

        return wf

    def _wait_for_completion(self, prompt_id: str, timeout: int = 1800, interval: int = 5) -> dict:
        """轮询 ComfyUI 直到任务完成（6段生成耗时较长，默认超时30分钟）"""
        start = time.time()
        while True:
            elapsed = int(time.time() - start)
            try:
                queue = self.client.get_queue()
                history = self.client.get_history(prompt_id)

                running = queue.get("queue_running", [])
                pending = queue.get("queue_pending", [])
                in_running = any(len(item) > 1 and item[1] == prompt_id for item in running)
                in_pending = any(len(item) > 1 and item[1] == prompt_id for item in pending)
                state = "running" if in_running else ("pending" if in_pending else "—")

                print(f"   [{elapsed}s] 状态={state}  运行中={len(running)}  排队={len(pending)}")

                if prompt_id in history:
                    task_data = history[prompt_id]
                    status_info = task_data.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        raise RuntimeError(f"ComfyUI 6关键帧工作流出错: {msgs}")
                    print(f"   [OK] 任务完成（耗时 {elapsed}s）")
                    return task_data

            except Exception as e:
                if "工作流出错" in str(e):
                    raise
                print(f"   [WARN] [{elapsed}s] 查询异常: {e}，继续等待...")

            if timeout > 0 and (time.time() - start) >= timeout:
                raise TimeoutError(f"6关键帧视频生成超时（{timeout}s），prompt_id={prompt_id}")

            time.sleep(interval)

    def _download_output(self, task_data: dict, output_path: str) -> None:
        """从 ComfyUI history 提取最终合成视频并下载到本地"""
        outputs = task_data.get("outputs", {})

        video_files: list[dict] = []
        for node_id, node_output in outputs.items():
            for key in ("videos", "gifs", "images"):
                for item in node_output.get(key, []):
                    fname = item.get("filename", "")
                    if fname.endswith((".mp4", ".webm", ".gif")):
                        video_files.append(item)

        if not video_files:
            raise RuntimeError(
                f"ComfyUI 6关键帧输出中未找到视频文件。输出: "
                f"{json.dumps(outputs, ensure_ascii=False)[:500]}"
            )

        # 优先选择来自 SaveVideo 节点（146）的输出
        primary = video_files[0]
        for vf in video_files:
            if vf.get("filename", "").startswith("video/"):
                primary = vf
                break

        filename = primary["filename"]
        subfolder = primary.get("subfolder", "")
        file_type = primary.get("type", "output")

        print(f"   [INFO] 下载: {filename}")
        data = self.client.download_output(filename, subfolder, file_type)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)
        size_mb = len(data) / (1024 * 1024)
        print(f"   [OK] 已保存: {output_path} ({size_mb:.1f} MB)")
