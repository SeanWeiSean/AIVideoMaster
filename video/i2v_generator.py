"""
I2V Generator — ComfyUI 图生视频客户端

通过 ComfyUI API 提交 Wan2.2 I2V（图生视频）工作流：
  1. 上传参考图到 ComfyUI input 目录
  2. 注入参数（prompt、seed、尺寸、帧数等）
  3. 提交工作流 → 轮询任务状态 → 下载视频

工作流特征：
  - 双 UNet 分段采样（高噪声 + 低噪声）
  - 可切换 4步 LoRA 加速 / 20步标准模式
  - WanImageToVideo 节点接受 start_image

关键节点映射：
  "97"       — LoadImage（参考图文件名）
  "129:93"   — 正向 prompt (CLIPTextEncode)
  "129:89"   — 反向 prompt (CLIPTextEncode)
  "129:98"   — WanImageToVideo（width, height, length）
  "129:86"   — KSamplerAdvanced Pass1（noise_seed）
  "129:131"  — 4步 LoRA 开关（true/false）
  "129:118"  — Steps (4步模式)
  "129:128"  — Steps (标准模式)
  "108"      — SaveVideo（output prefix）
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

# ── 节点 ID 映射 ─────────────────────────────────────────────

_I2V_PROFILE = {
    "file": "wan2.2/wan22_14B_i2v.json",
    # 参考图
    "load_image_node": "97",
    # prompt
    "positive_prompt_node": "129:93",
    "negative_prompt_node": "129:89",
    # 视频参数 (width, height, length)
    "i2v_node": "129:98",
    # 采样种子（高噪声 Pass1）
    "seed_node": "129:86",
    # 4步 LoRA 开关
    "lora_switch_node": "129:131",
    # Steps
    "steps_fast_node": "129:118",    # 4步模式
    "steps_quality_node": "129:128", # 标准模式
    # 输出
    "output_node": "108",
    # FPS
    "fps_node": "129:94",
}


@dataclass
class I2VJob:
    """I2V 视频生成任务结果"""
    job_id: str
    prompt: str
    status: str         # "pending" | "running" | "success" | "failed"
    file_path: str = ""
    error: str = ""


class I2VGenerator:
    """通过 ComfyUI + Wan2.2 I2V 工作流生成图生视频"""

    DEFAULT_NEGATIVE = (
        "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
        "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
        "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
        "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
    )

    def __init__(self, comfyui_url: str, output_dir: str = "./output") -> None:
        self.client = ComfyUIClient(comfyui_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._base_workflow = self._load_workflow()

    def _load_workflow(self) -> dict:
        wf_path = _WORKFLOWS_DIR / _I2V_PROFILE["file"]
        if not wf_path.is_file():
            raise FileNotFoundError(f"I2V 工作流文件不存在: {wf_path}")
        with open(wf_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_connection(self) -> bool:
        return self.client.is_alive()

    # ── 主入口 ────────────────────────────────────────────────

    def generate(
        self,
        positive_prompt: str,
        input_image_b64: str,
        *,
        negative_prompt: str = "",
        width: int = 1088,
        height: int = 720,
        length: int = 81,
        seed: int | None = None,
        use_fast_lora: bool = True,
        output_name: str = "",
    ) -> I2VJob:
        """
        图生视频：上传参考图 → 构建工作流 → 提交 → 等待 → 下载。

        Args:
            positive_prompt: 正向提示词
            input_image_b64: 参考图 base64 编码（不含 data: 前缀）
            negative_prompt: 反向提示词，留空使用默认
            width: 视频宽度 (默认 1088)
            height: 视频高度 (默认 720)
            length: 帧数 (默认 81 = 5秒@16fps)
            seed: 随机种子，None 自动生成
            use_fast_lora: True = 4步 LoRA 快速模式，False = 20步标准模式
            output_name: 输出文件名（不含路径），留空自动生成
        """
        job_id = uuid.uuid4().hex[:12]
        if not output_name:
            output_name = f"i2v_{job_id}.mp4"

        job = I2VJob(
            job_id=job_id,
            prompt=positive_prompt,
            status="running",
        )

        try:
            # Step 1: 上传参考图
            print(f"[I2V] 上传参考图...")
            image_filename = self._upload_image(input_image_b64, f"i2v_ref_{job_id}.png")
            print(f"[I2V] 参考图已上传: {image_filename}")

            # Step 2: 构建工作流
            actual_seed = seed if seed is not None else int(time.time() * 1000) % (2**53)
            actual_neg = negative_prompt or self.DEFAULT_NEGATIVE

            workflow = self._build_workflow(
                image_filename=image_filename,
                positive_prompt=positive_prompt,
                negative_prompt=actual_neg,
                width=width,
                height=height,
                length=length,
                seed=actual_seed,
                use_fast_lora=use_fast_lora,
                output_prefix=f"video/i2v_{job_id}",
            )

            mode_label = "4步LoRA快速" if use_fast_lora else "20步标准"
            print(f"[I2V] 模式: {mode_label} | 尺寸: {width}x{height} | 帧数: {length} | 种子: {actual_seed}")

            # Step 3: 提交
            prompt_id = self.client.submit_workflow(workflow)
            print(f"[I2V] 已提交 prompt_id={prompt_id}")

            # Step 4: 轮询等待
            task_data = self._wait_for_completion(prompt_id)

            # Step 5: 下载视频
            output_path = str(self.output_dir / output_name)
            self._download_output(task_data, output_path)

            job.status = "success"
            job.file_path = output_path
            print(f"[I2V] ✅ 视频已保存: {output_path}")

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            print(f"[I2V] ❌ 生成失败: {e}")

        return job

    # ── 内部方法 ──────────────────────────────────────────────

    def _upload_image(self, image_b64: str, filename: str) -> str:
        """base64 → bytes → 上传到 ComfyUI，返回服务器端文件名"""
        image_data = base64.b64decode(image_b64)
        return self.client.upload_image(image_data, filename)

    def _build_workflow(
        self,
        image_filename: str,
        positive_prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        length: int,
        seed: int,
        use_fast_lora: bool,
        output_prefix: str,
    ) -> dict:
        """深拷贝工作流模板并注入所有参数"""
        wf = json.loads(json.dumps(self._base_workflow))
        p = _I2V_PROFILE

        # 参考图
        wf[p["load_image_node"]]["inputs"]["image"] = image_filename

        # Prompt
        wf[p["positive_prompt_node"]]["inputs"]["text"] = positive_prompt
        wf[p["negative_prompt_node"]]["inputs"]["text"] = negative_prompt

        # 视频尺寸 & 帧数
        i2v_inputs = wf[p["i2v_node"]]["inputs"]
        i2v_inputs["width"] = width
        i2v_inputs["height"] = height
        i2v_inputs["length"] = length

        # 种子（Pass1 高噪声采样器）
        wf[p["seed_node"]]["inputs"]["noise_seed"] = seed

        # 4步 LoRA 开关
        wf[p["lora_switch_node"]]["inputs"]["value"] = use_fast_lora

        # 输出文件名前缀
        wf[p["output_node"]]["inputs"]["filename_prefix"] = output_prefix

        return wf

    def _wait_for_completion(self, prompt_id: str, timeout: int = 600, interval: int = 3) -> dict:
        """轮询 ComfyUI 直到任务完成"""
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
                        raise RuntimeError(f"ComfyUI I2V 工作流出错: {msgs}")
                    print(f"   [OK] 任务完成（耗时 {elapsed}s）")
                    return task_data

            except Exception as e:
                if "工作流出错" in str(e):
                    raise
                print(f"   [WARN] [{elapsed}s] 查询异常: {e}，继续等待...")

            if timeout > 0 and (time.time() - start) >= timeout:
                raise TimeoutError(f"I2V 视频生成超时（{timeout}s），prompt_id={prompt_id}")

            time.sleep(interval)

    def _download_output(self, task_data: dict, output_path: str) -> None:
        """从 ComfyUI history 提取视频并下载到本地"""
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
                f"ComfyUI I2V 输出中未找到视频文件。输出: "
                f"{json.dumps(outputs, ensure_ascii=False)[:500]}"
            )

        primary = video_files[0]
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
