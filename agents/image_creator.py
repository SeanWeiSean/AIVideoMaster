"""
图片创作双智能体

- ImageArchitect  (建筑师): 将用户粗略想法扩充成完整的图像蓝图
- ImageDescriptor (描述师): 将建筑师蓝图转化为 QwenImage 中文 Prompt

设计原则
--------
建筑师: 像设计一栋大豪宅的每个房间一样，把握每一处细节，
        只讲事实，不讲感觉，尽量把画面铺满。
描述师: QwenImage 使用专家，输出的 Prompt 只含可见视觉元素，
        用中文，不写情绪/感觉/模糊比喻。
"""
from __future__ import annotations

from openai import OpenAI

from config import LLMConfig, MIN_LLM_MAX_TOKENS


# ── 建筑师 ───────────────────────────────────────────────────

class ImageArchitect:
    """建筑师：像建造一栋大房子一样，把用户的简单意图扩充成完整图像蓝图"""

    SYSTEM_PROMPT = """\
你是一位顶级视觉概念设计师，代号「建筑师」。
你的任务：把用户的简单创意意图，像建筑师设计蓝图那样，扩充成一个完整、\
具体、面面俱到的图像概念方案——就像设计一栋大豪宅，要把每一个房间、\
每一处走廊、每一扇窗户都规划清楚。

设计规则：
1. 覆盖所有视觉维度：主体、前景、中景、背景、光线来源、颜色搭配、\
   材质质感、构图方式、景深关系、细节装饰
2. 每个元素要具体到可以直接被画出来的程度
3. 只讲视觉事实，不讲感觉和情绪（不写"美丽"、"震撼"、"温馨"）
4. 不使用模糊比喻（不写"如诗如画"、"让人心旷神怡"）
5. 用中文回答
6. 输出时逐项列明，使用以下固定结构：

【主体】（画面中心人物/物体/生物，外形、颜色、状态、动作）
【前景】（近处可见的物体、地面、植物等）
【中景】（主体所在的直接环境）
【背景】（远景、天空、建筑群、自然地貌）
【光线】（光源位置、光的类型、投影、反光）
【色彩】（主色调、辅助色、色温、对比关系）
【构图】（视角高低、镜头焦距感、画面比例、留白）
【材质/质感】（皮肤、布料、金属、石材、植物等的质感描述）
【数量/位置关系】（画面中各元素的空间排列）
【细节补充】（任何增强真实感和丰富度的额外细节）\
"""

    def __init__(self, llm_config: LLMConfig) -> None:
        self._client = OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            timeout=300.0,
        )
        self._model = llm_config.model
        self._temperature = llm_config.temperature
        self._max_tokens = max(llm_config.max_tokens, MIN_LLM_MAX_TOKENS)

    def expand(self, user_intent: str) -> str:
        """将用户意图扩充为完整图像蓝图"""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"请为以下创意意图设计完整图像蓝图——"
                    f"像建造一栋大豪宅一样，把每个细节都规划清楚：\n\n{user_intent}"
                ),
            },
        ]
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""


# ── 描述师 ───────────────────────────────────────────────────

class ImageDescriptor:
    """描述师：QwenImage Prompt 专家，将建筑师蓝图提炼为精准中文 Prompt"""

    SYSTEM_PROMPT = """\
你是 QwenImage 模型的资深使用专家，代号「描述师」。
你的任务：将详细的图像概念蓝图，转化为 QwenImage 能高效理解并精准生成的中文 Prompt。

转化规则：
1. 必须用中文
2. 只描述可见的视觉事实：物体形状、颜色数值（如"深蓝色"、"金棕色"）、材质、\
   光源方向（如"左上方来的强侧光"）、位置关系、数量
3. 绝对不描述感觉和情绪（不写"磅礴"、"温馨"、"壮观"、"梦幻"、"唯美"）
4. 绝对不用模糊比喻（不写"像……一样"、"如诗如画"）
5. 关键视觉元素排前面，细节补充排后面，用逗号分隔
6. 结尾加上质量词：高分辨率，细节丰富，写实渲染
7. 只输出最终 Prompt，不要任何解释说明、不要列标题、不要分段

输出示例风格（仅作格式参考，不代表实际内容）：
正面侧身站立的年轻男性，身穿深红色皮质夹克，米白色紧身裤，黑色皮靴，\
右手拿着一杯咖啡，左手插裤袋，背景是玻璃幕墙写字楼，地面为抛光大理石，\
左上方来的自然漫射光，浅棕色皮肤，短发，中等焦距镜头感，平视角，高分辨率，细节丰富，写实渲染\
"""

    def __init__(self, llm_config: LLMConfig) -> None:
        self._client = OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            timeout=300.0,
        )
        self._model = llm_config.model
        self._temperature = 0.3   # 描述师要确定性强
        self._max_tokens = max(llm_config.max_tokens, MIN_LLM_MAX_TOKENS)

    def generate_prompt(self, blueprint: str) -> str:
        """将建筑师蓝图转化为 QwenImage Prompt"""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请将以下图像蓝图转化为 QwenImage 中文 Prompt，"
                    "只输出 Prompt 本身，不要任何额外说明：\n\n"
                    f"{blueprint}"
                ),
            },
        ]
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""
