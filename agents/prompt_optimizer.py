"""
PromptOptimizerAgent - 独立 Prompt 优化器
根据 Wan2.2 最佳实践，将一段原始描述文字优化为高质量的视频生成 Prompt。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agents.prompt_bestpractice import get_bestpractice_for_enrichment, load_bestpractice
from config import LLMConfig, MIN_LLM_MAX_TOKENS


@dataclass
class OptimizedPrompt:
    """优化后的 Prompt 结果"""
    original_text: str          # 原始输入文字
    positive_prompt: str        # 优化后的英文正向 Prompt
    negative_prompt: str        # 生成的英文反向 Prompt
    analysis: str               # 中文分析说明（解释优化思路）


class PromptOptimizerAgent:
    """
    独立的 Prompt 优化器。
    输入：一段中文/英文描述文字
    输出：按照 Wan2.2 最佳实践优化后的 positive prompt + negative prompt
    """

    def __init__(self, llm_config: LLMConfig) -> None:
        self.llm_config = llm_config
        self._client = OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            timeout=120.0,
        )

    def optimize(self, text: str, mode: str = "t2v") -> OptimizedPrompt:
        """
        将原始描述文字优化为 Wan2.2 最佳实践 Prompt。

        Args:
            text: 原始描述文字（中文或英文）
            mode: 生成模式
                  - "t2v": 文生视频（Text-to-Video），生成完整的正向 prompt
                  - "i2v": 图生视频（Image-to-Video / Wan2.2），只生成运动和运镜 prompt
                  - "ltx-i2v": 图生视频（Image-to-Video / LTX-2.0），英文流畅段落叙事

        Returns:
            OptimizedPrompt 包含优化后的 positive/negative prompt 和分析说明
        """
        bestpractice = get_bestpractice_for_enrichment()

        if mode == "ltx-i2v":
            system_prompt = f"""You are an expert LTX-2.0 Image-to-Video (I2V) prompt engineer.

LTX-2.0 I2V Prompt Best Practices:
- The reference image already defines the character appearance, scene, and style
- Do NOT describe the character's appearance (hair, clothing, features) — the image handles that
- Write the prompt as a SINGLE FLOWING PARAGRAPH in English
- Use PRESENT TENSE verbs for all actions and movements
- Focus on: action/motion sequence, camera movement, atmosphere changes, audio description
- Describe camera movement relative to the subject (e.g., "the camera slowly pushes in")
- Express emotion through physical cues, not abstract labels (not "sad", but show the gesture)
- Place spoken dialogue in quotation marks
- Aim for 4-8 descriptive sentences
- For static camera, explicitly write "static frame" or "the camera holds steady"

I2V Formula: Motion + Camera Movement (+ optional: atmosphere/audio)

Output ONLY valid JSON:
```json
{{{{
  "positive_prompt": "English LTX I2V prompt as a single flowing paragraph...",
  "negative_prompt": "blurry, low quality, still frame, frames, watermark, overlay, titles, has blurbox, has subtitles",
  "analysis": "Chinese analysis explaining optimization decisions..."
}}}}
```"""
        elif mode == "i2v":
            system_prompt = f"""You are an expert Wan2.2 Image-to-Video (I2V) prompt engineer.

{bestpractice}

The user will provide a description of a scene or action. Since this is I2V mode, the reference image already defines the scene, subject, and style. Your job is to generate a prompt that ONLY describes:
1. Motion and action (what moves, how fast, what changes)
2. Camera movement (push in, pull out, pan, tilt, orbit, tracking, etc.)

Follow the I2V formula: Motion + Camera Movement
- Specify motion intensity: gently, slowly, rapidly, violently
- Specify camera movement type and direction
- Do NOT describe the static scene — only what CHANGES over 5 seconds

Output ONLY valid JSON:
```json
{{
  "positive_prompt": "English I2V motion prompt following best practices...",
  "negative_prompt": "English negative prompt...",
  "analysis": "Chinese analysis explaining optimization decisions..."
}}
```"""
        else:
            system_prompt = f"""You are an expert Wan2.2 Text-to-Video (T2V) prompt engineer.

{bestpractice}

The user will provide a raw description (Chinese or English) of a video they want to generate. Your job is to transform it into a professional, production-ready Wan2.2 prompt following the best practices.

You MUST follow the advanced formula:
**[Aesthetic controls] + [Shot type] + [Subject with detailed description] + [Motion with intensity/speed] + [Scene description] + [Style keywords]**

Aesthetic controls MUST include:
- Lighting source (e.g., sunlight, artificial light, moonlight, mixed light)
- Light quality (e.g., soft light, hard light, rim light, side light)
- Shot scale (e.g., close-up, medium close-up, medium shot, full shot)
- Composition (e.g., center composition, balanced composition, left/right weighted)
- Color tone (e.g., warm tone, cold tone, low saturation, high saturation)
- Time of day (if relevant: daytime, sunset, dawn, night)

Additional requirements:
- The positive_prompt must be in English
- Subject description must be concrete and visual (appearance, clothing, expression, posture)
- Motion description must specify intensity (gently, slowly, rapidly)
- Include camera movement if appropriate (push in, tracking shot, orbit, etc.)
- Include quality tags and style keywords for consistency
- The prompt should be self-contained and production-ready

Output ONLY valid JSON:
```json
{{
  "positive_prompt": "English positive prompt following best practices...",
  "negative_prompt": "English negative prompt tailored to the content...",
  "analysis": "Chinese analysis explaining the optimization: what aesthetic controls were added, what details were enriched, what motion/camera choices were made, and why..."
}}
```"""

        user_prompt = f"""请将以下描述优化为 Wan2.2 最佳实践 Prompt：

【原始描述】
{text}

【生成模式】{"LTX-2.0 图生视频 — 英文单段落叙事，聚焦动作/镜头/音频" if mode == "ltx-i2v" else "Wan2.2 图生视频 (I2V) — 只生成运动和运镜描述" if mode == "i2v" else "文生视频 (T2V) — 生成完整的视频描述"}

请严格按照最佳实践公式输出优化后的 prompt，并在 analysis 中用中文解释你的优化思路。"""

        response = self._client.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=max(self.llm_config.max_tokens, MIN_LLM_MAX_TOKENS),
        )

        raw = response.choices[0].message.content or ""
        result = self._parse_result(raw)

        return OptimizedPrompt(
            original_text=text,
            positive_prompt=result.get("positive_prompt", ""),
            negative_prompt=result.get("negative_prompt", ""),
            analysis=result.get("analysis", ""),
        )

    def _parse_result(self, raw: str) -> dict[str, Any]:
        """解析 LLM 返回的 JSON 结果"""
        import re
        text = raw.strip()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 fenced code block 中提取
        fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        for block in fenced:
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                continue

        # 尝试找到 JSON 对象
        for match in re.finditer(r"\{", text):
            try:
                decoder = json.JSONDecoder()
                payload, _ = decoder.raw_decode(text[match.start():])
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                continue

        # 兜底：返回原始文本作为 positive_prompt
        print(f"[WARN] PromptOptimizer 解析失败，raw_preview: {raw[:200]!r}")
        return {
            "positive_prompt": raw,
            "negative_prompt": "",
            "analysis": "解析失败，返回原始 LLM 输出",
        }
