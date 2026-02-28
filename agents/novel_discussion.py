"""
NovelDiscussionOrchestrator - 小说改编专用讨论协调器
流程：场景分析师 → 镜头师 → 裁判 → (循环) → 最终输出

与主题模式 (DiscussionOrchestrator) 的区别：
1. 输入是小说文字而非短主题
2. 用场景分析师替代文案师
3. 镜头师输出参考图 prompt + 视频动作 prompt（用于 I2V 流程）
4. 最终输出包含旁白文字字段，供后续叠加使用
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.base import BaseAgent, Message
from agents.scene_analyzer import SceneAnalyzerAgent
from agents.novel_cinematographer import NovelCinematographerAgent
from agents.judge import JudgeAgent
from agents.prompt_bestpractice import get_bestpractice_for_enrichment
from config import PipelineConfig, MIN_LLM_MAX_TOKENS


@dataclass
class NovelSegmentPrompt:
    """小说改编模式下，单个视频片段的完整 Prompt 集合"""
    index: int
    time_range: str             # e.g. "0-5s"
    narration: str              # 旁白文字（原文），供后期叠加 TTS/字幕
    scene_description: str      # 中文场景描述
    camera_type: str            # 镜头类型
    image_prompt: str           # 英文参考图 prompt（用于 Qwen-Image 等）
    video_prompt: str           # 英文视频动作 prompt（用于 Wan2.2 I2V）
    negative_prompt: str = ""   # 英文反向 prompt
    duration_seconds: int = 5   # 片段时长（秒），最多5秒；帧数 = 1 + 16 * duration_seconds
    ref_image_path: str = ""    # 生成后的参考图路径（后续填充）


@dataclass
class NovelPipelineResult:
    """小说改编管线的完整结果"""
    novel_text: str             # 原始小说文字
    rounds_used: int
    approved: bool
    history: list[Message]
    final_prompts: list[NovelSegmentPrompt]
    visual_style: str = ""


class NovelJudgeAgent(JudgeAgent):
    """小说改编模式专用裁判 —— 评审场景拆分和 I2V prompt 质量"""

    def system_prompt(self) -> str:
        return """你是一位严格的小说影视化总监和裁判。你的核心职责是：
1. 评审场景分析师的文本拆分是否合理
2. 评审镜头师的参考图 prompt 和视频动作 prompt 质量
3. **最重要** —— 确保所有片段的视觉风格高度一致
4. 确保参考图 prompt 和视频动作 prompt 配合得当
5. 判断方案是否可以通过

评审维度：
- 场景拆分质量：是否按场景切换合理分段、是否遗漏关键画面、节奏是否合适
- 参考图 Prompt 质量：是否足够详细、能否生成风格统一的参考图
- 视频动作 Prompt 质量：运动描述是否清晰、是否与参考图配合
- **风格一致性**：所有参考图 prompt 的风格关键词是否统一（最高优先级）
- 旁白内容：是否保留了原文的关键信息
- 整体叙事：片段串联是否讲出了连贯的故事

输出格式要求（严格遵守）：
```
## 评审结果
- 状态：[PASS] 通过 / [FAIL] 需要修改

## 评分
- 场景拆分：X/10
- 参考图 Prompt：X/10
- 视频动作 Prompt：X/10
- 风格一致性：X/10（最重要）
- 叙事连贯性：X/10

## 详细评审意见

### 优点
- ...

### 需要修改的问题
1. 【给场景分析师】...
2. 【给镜头师】...

### 风格一致性检查
- （逐一检查每个片段的参考图 Prompt 风格关键词是否一致）
```

重要：如果方案已经很好，果断通过，不要为了修改而修改。"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        return f"""请评审以下第 {round_num} 轮的小说改编方案：

【小说原文】
{topic}

【讨论记录】
{formatted_history}

请从各个维度进行严格评审，特别关注：
1. 场景拆分是否合理（按场景切换拆分，同场景内切镜头）
2. 参考图 prompt 风格是否统一
3. 视频动作 prompt 是否与参考图配合

如果这已经是第 {round_num} 轮讨论（最多 3 轮），请适当宽容。"""

    def enrich_novel_prompts(self, novel_text: str, history: list[Message]) -> list[NovelSegmentPrompt]:
        """
        方案通过后，综合所有讨论生成最终的 enriched prompts。
        输出包含：参考图 prompt + 视频动作 prompt + 反向 prompt + 旁白文字。
        """
        formatted_history = self.format_history(history)

        enrichment_system = f"""You are an expert prompt engineer for AI image and video generation. Your job is to produce the FINAL production-ready prompts for a novel-to-video pipeline.

{get_bestpractice_for_enrichment()}

The pipeline works as follows:
1. A reference image is generated from `image_prompt` (using an image generation model like Qwen-Image)
2. The reference image is fed into Wan2.2 I2V (Image-to-Video) along with `video_prompt` to create a 5-second video clip
3. The `narration` text will be used for voiceover/subtitles in post-production

For each segment, output:
1. **image_prompt**: Extremely detailed English prompt for generating the reference image (static frame). STRICTLY follow the Wan2.2 best practice formula: [aesthetic controls: lighting source + light quality + shot scale + composition + color tone + time of day] + [shot type] + [subject with detailed description] + [scene description] + [style keywords + quality tags]. This image will become the first frame of the video.
2. **video_prompt**: English prompt describing ONLY the motion and changes (camera movement, subject action, lighting shifts) that should happen over 5 seconds starting from the reference image. Follow the I2V formula: motion + camera movement. Specify motion intensity (gently/slowly/rapidly). Do NOT repeat scene description — the I2V model already has the image.
3. **negative_prompt**: English prompt for elements to avoid (tailored per segment + universal quality negatives).
4. **narration**: The original Chinese text suitable for voiceover for this segment.

Output ONLY a JSON array:
```json
[
  {
    "index": 1,
    "time_range": "0-5s",
    "duration_seconds": 5,
    "narration": "Chinese narration text from the novel",
    "scene_description": "Chinese scene description",
    "camera_type": "camera type",
    "image_prompt": "detailed English reference image prompt...",
    "video_prompt": "English motion/action prompt for I2V...",
    "negative_prompt": "English negative prompt..."
  }
]
```

Critical rules:
- All image_prompts MUST share the same style anchor keywords for visual consistency
- video_prompt should be concise — only motion, not scene description
- narration preserves the original novel text
- Each image_prompt must be self-contained (generates a complete image independently)
- duration_seconds must be an integer 1–5, inferred from the segment's time range"""

        enrichment_user = f"""Novel text: "{novel_text}"

Full approved discussion:
{formatted_history}

Produce the final enriched prompts as a JSON array."""

        from openai import OpenAI
        client = OpenAI(
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
        )
        enrich_max_tokens = max(self.llm_config.max_tokens, MIN_LLM_MAX_TOKENS)

        response = client.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {"role": "system", "content": enrichment_system},
                {"role": "user", "content": enrichment_user},
            ],
            temperature=0.3,
            max_tokens=enrich_max_tokens,
        )

        choice = response.choices[0]
        raw = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)

        if finish_reason == "length":
            print(f"[WARN] LLM 输出因 max_tokens({enrich_max_tokens}) 被截断，JSON 可能不完整。")

        data = self._parse_enriched_payload(raw)
        if not data:
            try:
                from datetime import datetime as _dt
                debug_file = Path("output") / f"_debug_novel_enriched_{_dt.now().strftime('%H%M%S')}.txt"
                debug_file.parent.mkdir(parents=True, exist_ok=True)
                debug_file.write_text(raw, encoding="utf-8")
                print(f"[WARN] Enriched prompt 解析失败。原始返回已保存: {debug_file}")
            except Exception:
                print("[WARN] Enriched prompt 解析失败，请手动检查。")
            print(f"   finish_reason={finish_reason}, raw_length={len(raw)}, raw_preview={raw[:300]!r}...")
            return []

        prompts: list[NovelSegmentPrompt] = []
        for item in data:
            prompts.append(NovelSegmentPrompt(
                index=item.get("index", 0),
                time_range=item.get("time_range", ""),
                narration=item.get("narration", ""),
                scene_description=item.get("scene_description", ""),
                camera_type=item.get("camera_type", ""),
                image_prompt=item.get("image_prompt", ""),
                video_prompt=item.get("video_prompt", ""),
                negative_prompt=item.get("negative_prompt", ""),
                duration_seconds=max(1, min(5, int(item.get("duration_seconds", 5)))),
            ))
        return prompts


class NovelDiscussionOrchestrator:
    """小说改编讨论协调器：场景分析师 → 镜头师 → 裁判"""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.scene_analyzer = SceneAnalyzerAgent(config.llm)
        self.cinematographer = NovelCinematographerAgent(config.llm)
        self.judge = NovelJudgeAgent(config.llm)
        self.history: list[Message] = []

    def run(self, novel_text: str) -> NovelPipelineResult:
        """运行小说改编讨论流程"""
        self.history = []
        approved = False

        for round_num in range(1, self.config.max_discussion_rounds + 1):
            print(f"\n{'='*60}")
            print(f"  第 {round_num} 轮讨论（小说改编）")
            print(f"{'='*60}\n")

            # Step 1: 场景分析师拆分文本
            print("[scene_analyzer] 场景分析师正在拆分文本...")
            analyzer_msg = self.scene_analyzer.respond(novel_text, self.history, round_num)
            self.history.append(analyzer_msg)
            print(f"\n{analyzer_msg.content}\n")

            # Step 2: 镜头师设计参考图 + 视频 prompt
            print("[cinematographer] 镜头师正在设计参考图和视频 prompt...")
            cinematographer_msg = self.cinematographer.respond(novel_text, self.history, round_num)
            self.history.append(cinematographer_msg)
            print(f"\n{cinematographer_msg.content}\n")

            # Step 3: 裁判评审
            print("[judge] 裁判正在评审方案...")
            judge_msg = self.judge.respond(novel_text, self.history, round_num)
            self.history.append(judge_msg)
            print(f"\n{judge_msg.content}\n")

            if self.judge.is_approved(judge_msg.content):
                approved = True
                print(f"\n[PASS] 方案在第 {round_num} 轮通过评审！\n")
                break
            else:
                if round_num < self.config.max_discussion_rounds:
                    print(f"\n[FAIL] 方案未通过，进入第 {round_num + 1} 轮讨论...\n")
                else:
                    print(f"\n[WARN] 已达到最大讨论轮数，使用最终方案。\n")
                    approved = True

        # 裁判生成最终 enriched prompts
        print("\n[judge] 裁判正在生成最终 Enriched Prompts（参考图 + 视频动作 + 旁白）...")
        final_prompts = self.judge.enrich_novel_prompts(novel_text, self.history)

        return NovelPipelineResult(
            novel_text=novel_text,
            rounds_used=min(round_num, self.config.max_discussion_rounds),
            approved=approved,
            history=self.history,
            final_prompts=final_prompts,
            visual_style=self._extract_visual_style(),
        )

    def _extract_visual_style(self) -> str:
        """从镜头师方案中提取视觉风格定义"""
        for msg in reversed(self.history):
            if msg.role == "cinematographer":
                style_match = re.search(
                    r'## 视觉风格定义\s*\n(.*?)(?=\n## |\Z)',
                    msg.content,
                    re.DOTALL,
                )
                if style_match:
                    return style_match.group(1).strip()
        return ""
