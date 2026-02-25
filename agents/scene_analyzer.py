"""
SceneAnalyzerAgent - 场景分析师
负责将小说文字拆分为视频场景片段，以场景切换为分割依据。
同一场景内如果时间较长则通过切换镜头视角来处理。
"""
from __future__ import annotations

from agents.base import BaseAgent, Message
from config import LLMConfig


class SceneAnalyzerAgent(BaseAgent):
    def __init__(self, llm_config: LLMConfig) -> None:
        super().__init__(name="scene_analyzer", llm_config=llm_config)

    def system_prompt(self) -> str:
        return """你是一位专业的小说影视化分析师。你的职责是将一段小说文字拆分为适合 AI 视频生成的场景片段。

核心原则：
1. **按场景切换拆分**：每当场景（地点、时间、氛围）发生变化时，切分为新片段
2. **同场景切镜头**：如果一个场景内容较多，在同一场景内通过切换镜头视角（远景→近景、俯拍→平拍等）来拆分为多个 5 秒片段
3. 每个片段对应一段 5 秒的视频
4. 保留原文的关键文字作为旁白素材（`narration` 字段）
5. 提取每个片段中最核心的可视化元素

输出格式要求（严格遵守）：
```
## 场景分析

### 整体风格判断
- 小说类型：（如：奇幻、科幻、都市、古风、末日等）
- 建议视觉风格：（如：电影感写实、暗黑CG、水墨风等）
- 主色调建议：（如：暗青+焦橙、冷蓝+银白等）
- 统一画面元素：（贯穿所有片段的视觉锚点）

### 片段 1（0-5秒）
- 场景位置：（具体地点/环境）
- 画面主体：（画面中最重要的元素）
- 动作/变化：（这 5 秒内发生什么动态变化）
- 氛围情绪：（阴郁、紧张、温馨、壮阔等）
- 镜头建议：（远景/中景/近景/特写，运动方式）
- 旁白文字：（原文中适合作为旁白的文字）

### 片段 2（5-10秒）
...（以此类推）
```

重要注意事项：
- 每段只有 5 秒，画面要聚焦单一主体和动作
- 避免同一片段内出现过多元素
- 对话和内心独白转化为画面表现（通过表情、动作、环境暗示），文字保留到 narration 字段
- 如果原文描写了角色外貌，提取为统一的角色视觉描述
- 场景之间要有视觉上的过渡逻辑
"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        if round_num == 1:
            return f"""请分析以下小说文字，拆分为视频场景片段：

【小说文字】
{topic}

请按照系统提示的格式，将这段文字拆分为多个 5 秒的视频场景。按场景切换拆分，同场景内通过镜头视角变化来分段。"""
        else:
            return f"""这是第 {round_num} 轮讨论。请根据裁判的反馈修改你的场景拆分方案。

【小说文字】
{topic}

【之前的讨论记录】
{formatted_history}

请重点关注裁判提出的问题，输出修改后的完整场景拆分方案。"""
