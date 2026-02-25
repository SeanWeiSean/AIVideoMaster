"""
BaseAgent - 所有 Sub Agent 的基类
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from config import LLMConfig, MIN_LLM_MAX_TOKENS


@dataclass
class Message:
    """讨论中的一条消息"""
    role: str          # "copywriter" | "cinematographer" | "judge" | "system"
    content: str
    round_num: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Sub Agent 基类，封装与 LLM 的交互"""

    def __init__(self, name: str, llm_config: LLMConfig) -> None:
        self.name = name
        self.llm_config = llm_config
        self._client = OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            timeout=300.0,  # 5 分钟超时，长回复场景
        )

    # ---- 子类必须实现 ----
    @abstractmethod
    def system_prompt(self) -> str:
        """返回该角色的系统提示词"""

    @abstractmethod
    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        """根据主题、历史消息和当前轮次，构建发给 LLM 的 user prompt"""

    # ---- 公共方法 ----
    def respond(self, topic: str, history: list[Message], round_num: int) -> Message:
        """调用 LLM 生成本角色的回复"""
        user_prompt = self.build_user_prompt(topic, history, round_num)
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        response = self._client.chat.completions.create(
            model=self.llm_config.model,
            messages=messages,
            temperature=self.llm_config.temperature,
            max_tokens=max(self.llm_config.max_tokens, MIN_LLM_MAX_TOKENS),
        )
        content = response.choices[0].message.content or ""
        return Message(role=self.name, content=content, round_num=round_num)

    # ---- 工具方法 ----
    @staticmethod
    def format_history(history: list[Message]) -> str:
        """将历史消息格式化为可读文本"""
        if not history:
            return "（暂无讨论记录）"
        lines: list[str] = []
        for msg in history:
            role_label = {
                "copywriter": "📝 文案师",
                "cinematographer": "🎬 镜头师",
                "judge": "⚖️ 裁判",
                "scene_analyzer": "📖 场景分析师",
                "system": "🔧 系统",
            }.get(msg.role, msg.role)
            lines.append(f"[第{msg.round_num}轮] {role_label}:\n{msg.content}\n")
        return "\n".join(lines)
