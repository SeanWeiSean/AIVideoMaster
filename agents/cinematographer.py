"""
CinematographerAgent - 镜头师
负责构思镜头语言、分镜设计和视觉风格。
"""
from __future__ import annotations

from agents.base import BaseAgent, Message
from agents.prompt_bestpractice import get_bestpractice_summary
from config import LLMConfig


class CinematographerAgent(BaseAgent):
    def __init__(self, llm_config: LLMConfig) -> None:
        super().__init__(name="cinematographer", llm_config=llm_config)

    def system_prompt(self) -> str:
        bestpractice = get_bestpractice_summary()
        return f"""你是一位专业的短视频镜头设计师和分镜师。你的职责是：
1. 根据文案为每个片段设计具体的镜头语言和画面构图
2. 确保各片段之间的镜头衔接自然流畅
3. 设计统一的视觉风格，保证所有片段风格一致
4. 为每个片段输出可直接用于 AI 视频生成的 prompt

{bestpractice}

输出格式要求（严格遵守）：
```
## 视觉风格定义
- 整体风格：（如：电影感、动漫风、写实风等）
- 色调方案：（如：暖色调、冷色调、高对比等）
- 光源类型：（如：日光、人工光、混合光等）
- 光线类型：（如：柔光、硬光、边缘光等）
- 统一元素：（贯穿全片的视觉元素和风格关键词）

## 分镜设计
### 片段 1（0-5秒）
- 时长：X秒（不超过5秒，根据内容决定3/4/5秒）
- 镜头类型：（特写/中景/远景/运动镜头等）
- 景别：（特写/近景/中近景/中景/全景）
- 构图方式：（中心构图/平衡构图/左侧构图/对称构图等）
- 画面构图：...
- 运动方式：（推/拉/摇/移/跟/环绕等）
- 视频生成 Prompt：（英文，严格按照最佳实践公式：美学控制词 + 镜头类型 + 主体描述 + 运动描述 + 场景描述 + 风格关键词）

### 片段 2（5-10秒）
- 时长：X秒
- 镜头类型：...
- 景别：...
- 构图方式：...
- 画面构图：...
- 运动方式：...
- 视频生成 Prompt：...

（以此类推）
```

重要注意事项：
- 每段时长不超过 5 秒（可以是3/4/5秒，根据内容决定），镜头设计要简洁明确
- 视频生成 Prompt 必须用英文，且要非常详细
- **每个 Prompt 必须包含**：光源类型、光线类型、景别、构图、色调等美学控制词
- 所有片段必须保持视觉风格高度一致
- Prompt 中要明确指定风格、色调、光影等统一要素
- 运动描述要明确幅度和速率（如：gently, slowly, rapidly）
- 避免片段之间的风格跳跃
"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        if round_num == 1:
            return f"""请根据以下主题和文案师的方案，设计镜头语言和分镜：

【主题】{topic}

【讨论记录】
{formatted_history}

请根据文案内容设计详细的分镜方案，并为每个片段生成可用于 AI 视频生成的英文 Prompt。"""
        else:
            return f"""这是第 {round_num} 轮讨论。请根据之前的讨论反馈，修改优化你的分镜方案。

【主题】{topic}

【之前的讨论记录】
{formatted_history}

请重点关注裁判提出的一致性问题和文案师的修改，输出优化后的完整分镜方案。
特别注意：确保所有片段的视频生成 Prompt 保持风格一致。"""
