"""
Wan2.2 Prompt 最佳实践知识库
从 promptbase/wan22_bestpractice.md 加载最佳实践，供各 Agent 引用。
"""
from __future__ import annotations

from pathlib import Path

_BESTPRACTICE_PATH = Path(__file__).resolve().parent.parent / "promptbase" / "wan22_bestpractice.md"

_cached_content: str | None = None


def load_bestpractice() -> str:
    """加载并缓存最佳实践 Markdown 全文"""
    global _cached_content
    if _cached_content is None:
        if _BESTPRACTICE_PATH.is_file():
            _cached_content = _BESTPRACTICE_PATH.read_text(encoding="utf-8")
        else:
            _cached_content = ""
            print(f"[WARN] 最佳实践文件不存在: {_BESTPRACTICE_PATH}")
    return _cached_content


def get_bestpractice_summary() -> str:
    """返回精炼的最佳实践摘要（用于 system prompt 注入，控制 token 开销）"""
    return """## Wan2.2 文生视频 Prompt 最佳实践摘要

### 一、提示词公式
**基础公式**: 主体 + 场景 + 运动
**进阶公式**: 主体（主体描述）+ 场景（场景描述）+ 运动（运动描述）+ 美学控制 + 风格化
**图生视频公式**: 运动 + 运镜（因图像已确定主体/场景/风格）

### 二、关键维度
1. **光源类型**: 日光、人工光、月光、实用光、火光、荧光、阴天光、混合光、晴天光
2. **光线类型**: 柔光、硬光、高对比度、侧光、底光、低对比度、边缘光、剪影
3. **时间段**: 白天、夜晚、日出、日落、黎明
4. **景别**: 特写、近景、广角、中近景、全景
5. **构图**: 中心构图、平衡构图、左/右侧构图、对称构图、短边构图
6. **镜头焦段**: 中焦距、广角、长焦、超广角-鱼眼
7. **镜头类型**: 干净的单人镜头、群像镜头、三人镜头、双人镜头、过肩镜头
8. **人物情绪**: 愤怒、恐惧、高兴等
9. **运动**: 街舞、跑步、橄榄球等动态场景
10. **基础运镜**: 镜头推进、镜头拉远、镜头上摇
11. **高级运镜**: 手持镜头、复合运镜、跟随镜头、环绕运镜
12. **风格化**: 像素风格、3D游戏、木偶动画、二次元
13. **特效镜头**: 移轴摄影、延时拍摄

### 三、Prompt 撰写要点
- 描述越完整、精确和丰富，生成视频品质越高
- 主体描述要具体：外观特征细节、服饰、表情等
- 场景描述要丰富：环境特征、背景、前景
- 运动描述要明确：幅度（猛烈/缓慢）、速率、作用效果
- 美学控制要精准：光源+光线+景别+视角+镜头+运镜
- 风格化要统一：同一项目所有片段保持一致的风格关键词
- 正向 prompt 中主动列出光源、光线、色调、构图等美学控制词
- 每个 prompt 应该是自包含的完整描述"""


def get_bestpractice_for_enrichment() -> str:
    """返回用于最终 enriched prompt 生成的详细最佳实践指导"""
    return """## Wan2.2 Prompt Engineering Best Practices (MUST FOLLOW)

When crafting the final positive prompt for Wan2.2 video generation, you MUST follow this formula:

**Advanced Formula**: Subject (detailed description) + Scene (detailed description) + Motion (detailed description) + Aesthetic Control + Stylization

### Required Dimensions to Include:

1. **Lighting Source** (pick one or combine): sunlight(日光), artificial light(人工光), moonlight(月光), practical light(实用光), firelight(火光), fluorescent(荧光), overcast light(阴天光), mixed light(混合光)

2. **Light Quality** (pick relevant): soft light(柔光), hard light(硬光), high contrast(高对比度), side light(侧光), bottom light(底光), low contrast(低对比度), rim light(边缘光), silhouette(剪影)

3. **Time of Day**: daytime(白天), night(夜晚), sunrise(日出), sunset(日落), dawn(黎明)

4. **Shot Scale**: close-up(特写), medium close-up(中近景), medium shot(中景), full shot(全景), extreme wide shot(极端全景)

5. **Composition**: center composition(中心构图), balanced composition(平衡构图), left/right weighted(左/右侧重构图), symmetrical composition(对称构图), short side composition(短边构图)

6. **Lens/Focal Length**: medium focal length(中焦距), wide angle(广角), telephoto(长焦), ultra wide/fisheye(超广角-鱼眼)

7. **Camera Movement**: push in(镜头推进), pull out(镜头拉远), tilt up(镜头上摇), handheld(手持镜头), tracking shot(跟随镜头), orbit(环绕运镜), composite camera movement(复合运镜)

8. **Color Tone**: warm tone(暖色调), cold tone(冷色调), mixed tone(混合色调), low saturation(低饱和度), high saturation(高饱和度)

9. **Shot Type**: clean single shot(干净的单人镜头), group shot(群像镜头), two-shot(双人镜头), three-shot(三人镜头), over-the-shoulder shot(过肩镜头)

### Prompt Structure Example:
`[aesthetic controls: rim light, soft light, medium close-up, center composition, warm tone, low saturation, sunset, side light], [shot type], [subject with detailed description: appearance, clothing, expression, posture], [action/motion with intensity and speed], [scene description: background, foreground, atmosphere], [style keywords]`

### Critical Rules:
- Every prompt MUST include at least: lighting, shot scale, composition, color tone
- Motion descriptions must specify intensity: "gently/slowly/rapidly/violently"
- All segments in a project must share the same style anchor keywords
- For I2V (image-to-video) prompts: focus ONLY on motion + camera movement, not scene description
- Subject descriptions must be concrete and visual, not abstract concepts
- Include quality tags where appropriate"""
