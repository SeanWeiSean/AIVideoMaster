"""
LTX I2V Generator — ComfyUI 图生视频客户端 (LTX-2.0)

通过 ComfyUI API 提交 LTX-2.0 I2V（图生视频）工作流：
  1. 上传参考图到 ComfyUI input 目录
  2. 注入参数（prompt、seed、帧数等）
  3. 提交工作流 → 轮询任务状态 → 下载视频

工作流特征（双阶段采样 + Spatial Upscaler）：
  - Pass1: euler 采样器，20 步，CFG=4（标准模型）
  - Pass2: gradient_estimation 采样器，蒸馏 LoRA，CFG=1（精修）
  - LTXVLatentUpsampler: spatial 2x 放大
  - 音频支持：LTXVAudioVAE 生成伴随音频
  - 图片预处理：LTXVPreprocess + ResizeByLongerEdge

关键节点映射：
  "98"       — LoadImage（参考图文件名）
  "102"      — ResizeImageMaskNode（缩放到 width x height）
  "92:3"     — 正向 prompt (CLIPTextEncode)
  "92:4"     — 反向 prompt (CLIPTextEncode)
  "92:62"    — PrimitiveInt（帧数 Length）
  "92:11"    — RandomNoise Pass1（noise_seed）
  "92:67"    — RandomNoise Pass2（noise_seed）
  "92:9"     — LTXVScheduler（steps, max_shift, base_shift）
  "92:47"    — CFGGuider Pass1（cfg）
  "92:82"    — CFGGuider Pass2（cfg）
  "75"       — SaveVideo（output prefix）
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

# ── LTX-2.0 I2V 节点 ID 映射 ────────────────────────────────

_LTX_I2V_PROFILE = {
    "file": "ltx2/ltx2_i2v.json",
    # 参考图
    "load_image_node": "98",
    # 图片缩放
    "resize_node": "102",
    # prompt
    "positive_prompt_node": "92:3",
    "negative_prompt_node": "92:4",
    # 帧数
    "length_node": "92:62",
    # 种子
    "seed_pass1_node": "92:11",
    "seed_pass2_node": "92:67",
    # 采样参数
    "scheduler_node": "92:9",
    "cfg_pass1_node": "92:47",
    "cfg_pass2_node": "92:82",
    # 输出
    "output_node": "75",
}

# LTX-2.0 默认反向提示词
_LTX_DEFAULT_NEGATIVE = (
    "blurry, low quality, still frame, frames, watermark, "
    "overlay, titles, has blurbox, has subtitles"
)


@dataclass
class LtxI2VJob:
    """LTX I2V 视频生成任务结果"""
    job_id: str
    prompt: str
    status: str         # "pending" | "running" | "success" | "failed"
    file_path: str = ""
    error: str = ""


class LtxI2VGenerator:
    """通过 ComfyUI + LTX-2.0 I2V 工作流生成图生视频

    注意：LTX 是 image-to-video，角色外观由参考图决定，
    prompt 应聚焦于动作、镜头运动和音频，不要描述角色外貌。
    """

    def __init__(self, comfyui_url: str, output_dir: str = "./output") -> None:
        self.client = ComfyUIClient(comfyui_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._base_workflow = self._load_workflow()

    def _load_workflow(self) -> dict:
        wf_path = _WORKFLOWS_DIR / _LTX_I2V_PROFILE["file"]
        if not wf_path.is_file():
            raise FileNotFoundError(f"LTX I2V 工作流文件不存在: {wf_path}")
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
        width: int = 1280,
        height: int = 720,
        length: int = 241,
        seed: int | None = None,
        steps: int = 20,
        cfg_pass1: float = 4.0,
        cfg_pass2: float = 1.0,
        output_name: str = "",
    ) -> LtxI2VJob:
        """
        LTX-2.0 图生视频：上传参考图 → 构建工作流 → 提交 → 等待 → 下载。

        Args:
            positive_prompt: 正向提示词（聚焦动作和镜头，不描述角色外观）
            input_image_b64: 参考图 base64 编码（不含 data: 前缀）
            negative_prompt: 反向提示词，留空使用默认
            width: 视频宽度 (默认 1280)
            height: 视频高度 (默认 720)
            length: 帧数 (默认 241 = ~9.6秒@25fps)
            seed: 随机种子，None 自动生成
            steps: Pass1 采样步数 (默认 20)
            cfg_pass1: Pass1 CFG 引导强度 (默认 4.0)
            cfg_pass2: Pass2 CFG 引导强度 (默认 1.0)
            output_name: 输出文件名（不含路径），留空自动生成
        """
        job_id = uuid.uuid4().hex[:12]
        if not output_name:
            output_name = f"ltx_i2v_{job_id}.mp4"

        job = LtxI2VJob(
            job_id=job_id,
            prompt=positive_prompt,
            status="running",
        )

        try:
            # Step 1: 上传参考图
            print(f"[LTX-I2V] 上传参考图...")
            image_filename = self._upload_image(input_image_b64, f"ltx_ref_{job_id}.png")
            print(f"[LTX-I2V] 参考图已上传: {image_filename}")

            # Step 2: 构建工作流
            actual_seed = seed if seed is not None else int(time.time() * 1000) % (2**53)
            actual_neg = negative_prompt or _LTX_DEFAULT_NEGATIVE

            workflow = self._build_workflow(
                image_filename=image_filename,
                positive_prompt=positive_prompt,
                negative_prompt=actual_neg,
                width=width,
                height=height,
                length=length,
                seed=actual_seed,
                steps=steps,
                cfg_pass1=cfg_pass1,
                cfg_pass2=cfg_pass2,
                output_prefix=f"video/ltx_i2v_{job_id}",
            )

            print(f"[LTX-I2V] 尺寸: {width}x{height} | 帧数: {length} | "
                  f"步数: {steps} | CFG: {cfg_pass1}/{cfg_pass2} | 种子: {actual_seed}")

            # Step 3: 提交
            prompt_id = self.client.submit_workflow(workflow)
            print(f"[LTX-I2V] 已提交 prompt_id={prompt_id}")

            # Step 4: 轮询等待
            task_data = self._wait_for_completion(prompt_id)

            # Step 5: 下载视频
            output_path = str(self.output_dir / output_name)
            self._download_output(task_data, output_path)

            job.status = "success"
            job.file_path = output_path
            print(f"[LTX-I2V] ✅ 视频已保存: {output_path}")

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            print(f"[LTX-I2V] ❌ 生成失败: {e}")

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
        steps: int,
        cfg_pass1: float,
        cfg_pass2: float,
        output_prefix: str,
    ) -> dict:
        """深拷贝工作流模板并注入所有参数"""
        wf = json.loads(json.dumps(self._base_workflow))
        p = _LTX_I2V_PROFILE

        # 参考图
        wf[p["load_image_node"]]["inputs"]["image"] = image_filename

        # 图片缩放尺寸
        resize_inputs = wf[p["resize_node"]]["inputs"]
        resize_inputs["resize_type.width"] = width
        resize_inputs["resize_type.height"] = height

        # Prompt
        wf[p["positive_prompt_node"]]["inputs"]["text"] = positive_prompt
        wf[p["negative_prompt_node"]]["inputs"]["text"] = negative_prompt

        # 帧数
        wf[p["length_node"]]["inputs"]["value"] = length

        # 种子（两个采样阶段分别注入）
        wf[p["seed_pass1_node"]]["inputs"]["noise_seed"] = seed
        wf[p["seed_pass2_node"]]["inputs"]["noise_seed"] = seed

        # 采样步数（Pass1 scheduler）
        wf[p["scheduler_node"]]["inputs"]["steps"] = steps

        # CFG 引导强度
        wf[p["cfg_pass1_node"]]["inputs"]["cfg"] = cfg_pass1
        wf[p["cfg_pass2_node"]]["inputs"]["cfg"] = cfg_pass2

        # 输出文件名前缀
        wf[p["output_node"]]["inputs"]["filename_prefix"] = output_prefix

        return wf

    def _wait_for_completion(self, prompt_id: str, timeout: int = 1200, interval: int = 5) -> dict:
        """轮询 ComfyUI 直到任务完成（LTX 双阶段+放大较慢，默认超时 20 分钟）"""
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
                        raise RuntimeError(f"ComfyUI LTX I2V 工作流出错: {msgs}")
                    print(f"   [OK] 任务完成（耗时 {elapsed}s）")
                    return task_data

            except Exception as e:
                if "工作流出错" in str(e):
                    raise
                print(f"   [WARN] [{elapsed}s] 查询异常: {e}，继续等待...")

            if timeout > 0 and (time.time() - start) >= timeout:
                raise TimeoutError(f"LTX I2V 视频生成超时（{timeout}s），prompt_id={prompt_id}")

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
                f"ComfyUI LTX I2V 输出中未找到视频文件。输出: "
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
