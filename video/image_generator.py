"""
ImageGenerator - 参考图生成客户端
通过外部 API（如 Qwen-Image）生成视频参考图。

用户需要提供 API 地址和接口格式，本模块提供统一的抽象接口。
"""
from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib import request, error, parse


@dataclass
class GeneratedImage:
    """生成的参考图"""
    index: int
    prompt: str
    file_path: str
    status: str  # "success" | "failed"
    error: str = ""


class BaseImageGenerator(ABC):
    """参考图生成器抽象基类 —— 实现此接口以接入不同的图片生成 API"""

    @abstractmethod
    def generate(self, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024) -> bytes:
        """
        生成一张图片，返回图片二进制数据（PNG/JPG）。

        Args:
            prompt: 英文正向 prompt
            negative_prompt: 英文反向 prompt
            width: 图片宽度
            height: 图片高度

        Returns:
            图片的二进制数据
        """

    def generate_to_file(self, prompt: str, output_path: str,
                         negative_prompt: str = "",
                         width: int = 1024, height: int = 1024) -> GeneratedImage:
        """生成图片并保存到文件"""
        try:
            data = self.generate(prompt, negative_prompt, width, height)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(data)
            return GeneratedImage(
                index=0, prompt=prompt,
                file_path=output_path, status="success",
            )
        except Exception as e:
            return GeneratedImage(
                index=0, prompt=prompt,
                file_path=output_path, status="failed", error=str(e),
            )


class QwenImageGenerator(BaseImageGenerator):
    """
    Qwen-Image API 客户端（占位实现）

    接口格式说明（等用户提供后替换）：
    ──────────────────────────────────
    预期的 API 格式：

    POST {base_url}/generate
    Content-Type: application/json

    请求体:
    {
        "prompt": "English image description",
        "negative_prompt": "things to avoid",
        "width": 1024,
        "height": 1024,
        "style": "optional style preset"
    }

    响应:
    - 直接返回图片二进制 (Content-Type: image/png)
    - 或返回 JSON: {"image_url": "https://...", "image_base64": "..."}
    ──────────────────────────────────

    用户提供实际 API 格式后，修改 generate() 方法即可。
    """

    def __init__(self, base_url: str, api_key: str = "",
                 timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024) -> bytes:
        """
        调用 Qwen-Image API 生成图片。

        TODO: 用户提供实际 API 格式后替换此实现。
        当前为占位实现，展示接口调用流程。
        """
        url = f"{self.base_url}/generate"
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method="POST")

        with request.urlopen(req, timeout=self.timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")

            # 情况1：直接返回图片二进制
            if "image/" in content_type:
                return resp.read()

            # 情况2：返回 JSON
            result = json.loads(resp.read().decode("utf-8"))

            # 2a: base64 编码的图片
            if "image_base64" in result:
                import base64
                return base64.b64decode(result["image_base64"])

            # 2b: 图片 URL，需要二次下载
            if "image_url" in result:
                img_req = request.Request(result["image_url"])
                with request.urlopen(img_req, timeout=self.timeout) as img_resp:
                    return img_resp.read()

            raise RuntimeError(f"无法解析 API 响应: {json.dumps(result)[:500]}")


class ComfyUIImageGenerator(BaseImageGenerator):
    """
    通过 ComfyUI 工作流生成参考图（备选方案）

    如果用户本地有 Flux/SDXL 等图片生成模型，
    可以复用 ComfyUI 工作流来生成参考图。
    """

    def __init__(self, comfyui_url: str, workflow_path: str = "") -> None:
        self.comfyui_url = comfyui_url
        self.workflow_path = workflow_path
        # 复用已有的 ComfyUI client
        from video.generator import ComfyUIClient
        self.client = ComfyUIClient(comfyui_url)

    def generate(self, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024) -> bytes:
        """通过 ComfyUI 工作流生成图片（需要用户提供图片生成工作流）"""
        raise NotImplementedError(
            "ComfyUI 图片生成需要用户提供对应的工作流 JSON 和节点映射。"
            "请实现此方法或使用 QwenImageGenerator。"
        )


class ImageGeneratorPipeline:
    """参考图批量生成管线"""

    def __init__(self, generator: BaseImageGenerator, output_dir: str) -> None:
        self.generator = generator
        self.output_dir = Path(output_dir)

    def generate_all(
        self,
        prompts: list[dict],
        session_name: str = "default",
        width: int = 1024,
        height: int = 1024,
    ) -> list[GeneratedImage]:
        """
        为所有片段生成参考图。

        Args:
            prompts: 列表，每项包含 {index, image_prompt, negative_prompt}
            session_name: 会话名称（子目录）
            width, height: 图片尺寸

        Returns:
            GeneratedImage 列表
        """
        session_dir = self.output_dir / session_name / "ref_images"
        session_dir.mkdir(parents=True, exist_ok=True)

        results: list[GeneratedImage] = []
        total = len(prompts)

        for i, p in enumerate(prompts, 1):
            idx = p.get("index", i)
            img_prompt = p.get("image_prompt", "")
            neg_prompt = p.get("negative_prompt", "")

            print(f"\n{'─'*50}")
            print(f"🖼️ 生成参考图 {i}/{total}：片段 {idx}")
            print(f"   Prompt: {img_prompt[:100]}...")
            print(f"{'─'*50}")

            output_path = str(session_dir / f"ref_{idx:03d}.png")
            result = self.generator.generate_to_file(
                prompt=img_prompt,
                output_path=output_path,
                negative_prompt=neg_prompt,
                width=width,
                height=height,
            )
            result.index = idx

            if result.status == "success":
                print(f"   ✅ 参考图已生成: {result.file_path}")
            else:
                print(f"   ❌ 生成失败: {result.error}")

            results.append(result)

        return results
