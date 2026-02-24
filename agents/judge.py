"""
JudgeAgent - 裁判
负责评审文案和分镜方案，把关质量和风格一致性。
方案通过后，负责生成最终的 enriched prompts（正向 + 反向）。
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from agents.base import BaseAgent, Message
from config import LLMConfig

if TYPE_CHECKING:
    from agents.discussion import VideoSegmentPrompt


class JudgeAgent(BaseAgent):
    def __init__(self, llm_config: LLMConfig) -> None:
        super().__init__(name="judge", llm_config=llm_config)

    def system_prompt(self) -> str:
        return """你是一位严格的短视频创作总监和裁判。你的核心职责是：
1. 评审文案师和镜头师的方案质量
2. **最重要** —— 确保所有视频片段的风格高度一致
3. 判断当前方案是否可以通过，或需要继续修改
4. 给出具体、可操作的修改建议

评审维度：
- 文案质量：是否引人入胜、节奏是否合适、逻辑是否连贯
- 镜头设计：构图是否专业、镜头衔接是否自然
- **风格一致性**：所有片段的视觉风格、色调、画面元素是否统一（最高优先级）
- Prompt 质量：AI 视频生成 prompt 是否足够详细、风格描述是否一致
- 整体协调：文案与镜头是否匹配

输出格式要求（严格遵守）：
```
## 评审结果
- 状态：✅ 通过 / ❌ 需要修改

## 评分
- 文案质量：X/10
- 镜头设计：X/10
- 风格一致性：X/10（最重要）
- Prompt 质量：X/10
- 整体协调：X/10

## 详细评审意见

### 优点
- ...

### 需要修改的问题
1. 【给文案师】...
2. 【给镜头师】...

### 风格一致性检查
- （逐一检查每个片段 Prompt 的风格描述是否一致）
```

重要注意事项：
- 风格一致性是你的最高优先级评审标准
- 如果风格不一致，必须标记为"需要修改"
- 对每个视频生成 Prompt 的风格关键词进行逐一比对
- 给出的修改建议要具体可执行
- 如果方案已经很好，不要为了修改而修改，果断通过
"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        return f"""请评审以下第 {round_num} 轮的讨论方案：

【主题】{topic}

【讨论记录】
{formatted_history}

请从各个维度进行严格评审，特别关注所有片段的风格一致性。
如果这已经是第 {round_num} 轮讨论（最多 3 轮），请在评审时考虑是否需要更加宽容。

请按照系统提示的格式输出你的评审结果。"""

    def is_approved(self, response_content: str) -> bool:
        """判断裁判是否通过了方案"""
        return "✅ 通过" in response_content or "✅通过" in response_content

    # ── 最终 Enriched Prompt 生成 ─────────────────────────────────

    def enrich_prompts(self, topic: str, history: list[Message]) -> list[VideoSegmentPrompt]:
        """
        方案通过后，由裁判综合文案师 + 镜头师的全部讨论，
        为每个片段生成最终的 enriched positive prompt + negative prompt（英文）。
        返回结构化的 VideoSegmentPrompt 列表。
        """
        from agents.discussion import VideoSegmentPrompt

        formatted_history = self.format_history(history)

        enrichment_system = """You are an expert AI video generation prompt engineer. Your job is to take the approved discussion between a copywriter (文案师) and a cinematographer (镜头师) and produce the FINAL enriched prompts for an AI video generation model (Wan2.2).

For each video segment you must output:
1. **positive_prompt**: A highly detailed, richly descriptive English prompt that combines the copywriter's intent with the cinematographer's visual design. Include: subject, action, composition, camera movement, lighting, color palette, atmosphere, style keywords, quality tags. Make it as detailed and specific as possible for best generation quality.
2. **negative_prompt**: An English prompt specifying what to AVOID in that specific segment. Tailor it to each segment's content — for example, a nature scene should exclude people/text/UI elements; a person scene should exclude deformities. Always include universal quality negatives (low quality, blurry, etc.) plus segment-specific exclusions.

Output ONLY a JSON array, no other text:
```json
[
  {
    "index": 1,
    "time_range": "0-5s",
    "copywriting": "original Chinese copywriting text",
    "scene_description": "Chinese scene description",
    "camera_type": "camera type",
    "positive_prompt": "detailed English positive prompt...",
    "negative_prompt": "detailed English negative prompt..."
  }
]
```

Important rules:
- positive_prompt must be in English, extremely detailed, production-ready
- negative_prompt must be in English, tailored per segment
- Maintain perfect style consistency across ALL segments' positive prompts (same style anchors, quality tags, aspect ratio, film grain, etc.)
- Keep the creative vision from the discussion intact — do not deviate from the approved plan
- Each positive_prompt should be self-contained (not reference other segments)"""

        enrichment_user = f"""Below is the full approved discussion for topic: "{topic}"

{formatted_history}

Now produce the final enriched prompts (positive + negative) for each video segment as a JSON array."""

        from openai import OpenAI
        client = OpenAI(
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
        )
        response = client.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {"role": "system", "content": enrichment_system},
                {"role": "user", "content": enrichment_user},
            ],
            temperature=0.3,
            max_tokens=self.llm_config.max_tokens,
        )

        raw = response.choices[0].message.content or "[]"

        # 提取 JSON
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            raw = json_match.group()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("⚠️ 裁判生成的 enriched prompt 解析失败，请手动检查。")
            return []

        prompts: list[VideoSegmentPrompt] = []
        for item in data:
            prompts.append(VideoSegmentPrompt(
                index=item.get("index", 0),
                time_range=item.get("time_range", ""),
                copywriting=item.get("copywriting", ""),
                scene_description=item.get("scene_description", ""),
                camera_type=item.get("camera_type", ""),
                video_prompt=item.get("positive_prompt", ""),
                negative_prompt=item.get("negative_prompt", ""),
            ))
        return prompts
