"""
CopywriterAgent - 文案师
负责根据主题撰写视频文案，拆分为多段（每段对应一个 5 秒视频片段）。
"""
from __future__ import annotations

from agents.base import BaseAgent, Message
from config import LLMConfig


class CopywriterAgent(BaseAgent):
    def __init__(self, llm_config: LLMConfig) -> None:
        super().__init__(name="copywriter", llm_config=llm_config)

    def system_prompt(self) -> str:
        return """你是一位资深的短视频文案创作者。你的职责是：
1. 根据给定主题撰写引人入胜的视频文案
2. 将文案合理拆分为多个片段，每个片段对应一段 5 秒的视频
3. 每段文案要简洁有力，适合短视频的节奏
4. 为每段文案提供清晰的描述，方便后续生成视频 prompt

输出格式要求（严格遵守）：
```
## 总体构思
（你对整体视频的文案构思说明）

## 分段文案
### 片段 1（0-5秒）
- 文案内容：...
- 画面描述：...

### 片段 2（5-10秒）
- 文案内容：...
- 画面描述：...

（以此类推）
```

重要注意事项：
- 每段视频只有 5 秒，文案要精炼
- 保持整体风格统一连贯
- 关注观众注意力，开头要有吸引力
- 结尾要有记忆点或 call-to-action
"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        if round_num == 1:
            return f"""请根据以下主题创作短视频文案：

【主题】{topic}

请按照系统提示的格式输出你的文案方案。"""
        else:
            return f"""这是第 {round_num} 轮讨论。请根据之前的讨论反馈，修改优化你的文案方案。

【主题】{topic}

【之前的讨论记录】
{formatted_history}

请重点关注裁判和镜头师提出的修改建议，输出优化后的完整文案方案。"""
