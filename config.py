"""
Video Pipeline 配置文件
"""
import os
from dataclasses import dataclass, field


MIN_LLM_MAX_TOKENS = int(os.getenv("LLM_MIN_MAX_TOKENS", "16384"))


@dataclass
class LLMConfig:
    """LLM 连接配置"""
    api_key: str = os.getenv("LLM_API_KEY", "no-key")
    base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:23333/api/openai/v1")
    model: str = os.getenv("LLM_MODEL", "claude-opus-4.6")
    temperature: float = 0.7
    max_tokens: int = MIN_LLM_MAX_TOKENS


@dataclass
class VideoConfig:
    """视频生成配置 (ComfyUI + Wan2.2)"""
    comfyui_url: str = os.getenv("COMFYUI_URL", "http://localhost:8188")
    workflow_path: str = os.getenv("COMFYUI_WORKFLOW", "")  # 留空则使用内置默认
    quality_mode: str = os.getenv("VIDEO_QUALITY", "fast")  # "fast"(Lora4步~60s) / "quality"(标准20步~10min) / "cocktail_lora"(鸡尾酒LoRA 10步)
    # Wan2.2 默认参数
    width: int = 640
    height: int = 640
    length: int = 81         # 帧数，81帧 ≈ 5秒 @16fps
    fps: int = 16
    negative_prompt: str = "低质量, 模糊, 变形, 水印, 文字, low quality, blurry, deformed, watermark, text"
    # 运行参数
    poll_interval: int = 15   # 轮询间隔（秒）
    generation_timeout: int = 1800  # 单个片段超时（秒），30分钟
    output_dir: str = os.getenv("VIDEO_OUTPUT_DIR", "./output")


@dataclass
class ImageGenConfig:
    """参考图生成配置（Qwen-Image 等）"""
    api_url: str = os.getenv("IMAGE_GEN_URL", "")          # 图片生成 API 地址
    api_key: str = os.getenv("IMAGE_GEN_KEY", "")          # API Key
    width: int = 1024
    height: int = 1024
    timeout: int = 120  # 单张图片超时（秒）


@dataclass
class PipelineConfig:
    """Pipeline 总配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    image_gen: ImageGenConfig = field(default_factory=ImageGenConfig)
    max_discussion_rounds: int = 3  # 最多讨论轮数
    language: str = "zh"  # 默认使用中文


# 全局默认配置
DEFAULT_CONFIG = PipelineConfig()
