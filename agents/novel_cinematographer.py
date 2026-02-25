"""
NovelCinematographerAgent - 小说改编专用镜头师
基于场景分析结果，为每个片段设计：
1. 参考图生成 prompt（用于 Qwen-Image 生成参考图）
2. 视频动作 prompt（用于 Wan2.2 I2V 生成视频）
"""
from __future__ import annotations

from agents.base import BaseAgent, Message
from config import LLMConfig


class NovelCinematographerAgent(BaseAgent):
    def __init__(self, llm_config: LLMConfig) -> None:
        super().__init__(name="cinematographer", llm_config=llm_config)

    def system_prompt(self) -> str:
        return """你是一位专业的小说影视化镜头设计师。你的工作流程是 **参考图 → 图生视频（I2V）**：
1. 先为每个片段设计一张**参考图**的生成 prompt（将作为视频的第一帧/风格锚点）
2. 再设计一个**视频动作 prompt**（描述参考图基础上的运动和变化）

这样可以确保风格和角色的一致性——参考图固定住画面内容，视频 prompt 只负责动态。

输出格式要求（严格遵守）：
```
## 视觉风格定义
- 整体风格：（如：电影感、动漫风、写实风等）
- 色调方案：（贯穿所有片段的统一色调）
- 参考图统一要素：（所有参考图必须包含的风格关键词，确保一致性）

## 分镜设计

### 片段 1（0-5秒）
- 镜头类型：（特写/中景/远景/运动镜头等）
- 画面构图：（详细描述画面布局）
- 参考图 Prompt（英文）：（用于图片生成模型的详细 prompt，描述一张静态画面，包含完整的风格、色调、构图、光影信息）
- 视频动作 Prompt（英文）：（基于参考图，描述 5 秒内的运动变化——镜头移动、主体动作、光影变化等。不需要重复描述场景内容，只描述"动起来"的部分）
- 反向 Prompt（英文）：（需要避免的元素）

### 片段 2（5-10秒）
...（以此类推）
```

重要注意事项：
- **参考图 Prompt** 必须英文，要非常详细，生成出来的图就是视频第一帧
- **视频动作 Prompt** 必须英文，聚焦在运动和变化上，不要重复场景描述
- 所有片段的参考图必须包含**相同的风格关键词**（统一在"参考图统一要素"中定义）
- 前后片段在色调/光影上要有过渡逻辑
- 每段只有 5 秒，动作设计要简洁明确
- 参考图 Prompt 不要写太抽象的概念，要写具体的视觉元素
"""

    def build_user_prompt(self, topic: str, history: list[Message], round_num: int) -> str:
        formatted_history = self.format_history(history)

        if round_num == 1:
            return f"""请根据场景分析师的拆分方案，为每个片段设计参考图 prompt 和视频动作 prompt：

【小说原文】
{topic}

【讨论记录】
{formatted_history}

请为每个片段输出：参考图 Prompt（静态画面）+ 视频动作 Prompt（运动变化）+ 反向 Prompt。
确保所有参考图风格高度统一。"""
        else:
            return f"""这是第 {round_num} 轮讨论。请根据裁判反馈修改你的方案。

【小说原文】
{topic}

【之前的讨论记录】
{formatted_history}

请输出修改后的完整分镜方案，特别注意裁判指出的风格一致性问题。"""
