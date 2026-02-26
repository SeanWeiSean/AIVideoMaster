"""
DiscussionOrchestrator - 多轮讨论协调器
管理文案师、镜头师、裁判之间的多轮讨论流程。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agents.base import BaseAgent, Message
from agents.copywriter import CopywriterAgent
from agents.cinematographer import CinematographerAgent
from agents.judge import JudgeAgent
from config import PipelineConfig


@dataclass
class VideoSegmentPrompt:
    """最终输出的单个视频片段 Prompt"""
    index: int
    time_range: str        # e.g. "0-5秒"
    copywriting: str       # 文案内容
    scene_description: str # 画面描述
    camera_type: str       # 镜头类型
    video_prompt: str      # 用于 AI 生成的英文正向 Prompt
    negative_prompt: str = ""  # 英文反向 Prompt（裁判生成）


@dataclass
class DiscussionResult:
    """讨论的最终结果"""
    topic: str
    rounds_used: int
    approved: bool
    history: list[Message]
    final_prompts: list[VideoSegmentPrompt]
    visual_style: str = ""


class DiscussionOrchestrator:
    """协调三个 Agent 进行多轮讨论"""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.copywriter = CopywriterAgent(config.llm)
        self.cinematographer = CinematographerAgent(config.llm)
        self.judge = JudgeAgent(config.llm)
        self.history: list[Message] = []

    def run(self, topic: str) -> DiscussionResult:
        """运行完整的多轮讨论流程"""
        self.history = []
        approved = False

        for round_num in range(1, self.config.max_discussion_rounds + 1):
            print(f"\n{'='*60}")
            print(f"  第 {round_num} 轮讨论")
            print(f"{'='*60}\n")

            # Step 1: 文案师发言
            print("[copywriter] 文案师正在撰写文案...")
            copywriter_msg = self.copywriter.respond(topic, self.history, round_num)
            self.history.append(copywriter_msg)
            print(f"\n{copywriter_msg.content}\n")

            # Step 2: 镜头师发言（基于文案师的方案）
            print("[cinematographer] 镜头师正在设计分镜...")
            cinematographer_msg = self.cinematographer.respond(topic, self.history, round_num)
            self.history.append(cinematographer_msg)
            print(f"\n{cinematographer_msg.content}\n")

            # Step 3: 裁判评审
            print("[judge] 裁判正在评审方案...")
            judge_msg = self.judge.respond(topic, self.history, round_num)
            self.history.append(judge_msg)
            print(f"\n{judge_msg.content}\n")

            # 检查是否通过
            if self.judge.is_approved(judge_msg.content):
                approved = True
                print(f"\n[PASS] 方案在第 {round_num} 轮通过评审！\n")
                break
            else:
                if round_num < self.config.max_discussion_rounds:
                    print(f"\n[FAIL] 方案未通过，进入第 {round_num + 1} 轮讨论...\n")
                else:
                    print(f"\n[WARN] 已达到最大讨论轮数（{self.config.max_discussion_rounds}轮），"
                          f"使用最终方案。\n")
                    approved = True  # 到达最大轮数，强制采用

        # 由裁判生成最终 enriched prompts（正向 + 反向）
        print("\n[judge] 裁判正在生成最终 Enriched Prompts（正向 + 反向）...")
        final_prompts = self.judge.enrich_prompts(topic, self.history)

        return DiscussionResult(
            topic=topic,
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
                # 提取"视觉风格定义"段落
                style_match = re.search(
                    r'## 视觉风格定义\s*\n(.*?)(?=\n## |\Z)',
                    msg.content,
                    re.DOTALL,
                )
                if style_match:
                    return style_match.group(1).strip()
                return ""
        return ""
