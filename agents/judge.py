"""
JudgeAgent - 裁判
负责评审文案和分镜方案，把关质量和风格一致性。
方案通过后，负责生成最终的 enriched prompts（正向 + 反向）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
- 状态：[PASS] 通过 / [FAIL] 需要修改

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
        return "[PASS] 通过" in response_content or "[PASS]通过" in response_content

    # ── 最终 Enriched Prompt 生成 ─────────────────────────────────

    @staticmethod
    def _coerce_prompt_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if isinstance(payload, dict):
            for key in ("segments", "prompts", "data", "items", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]

        return []

    @staticmethod
    def _is_json_after_comma(text: str, comma_pos: int, n: int) -> bool:
        """判断逗号之后是否是 JSON 结构（而非自然语言散文）。

        例如:
          OK  ", \n    "camera_type": ..."   → ",后面是 "key": 模式，真正的 JSON 逗号
          OK  "}, {"                         → 下一个对象
          NO  ", an orange kit ..."          → 英文散文，逗号只是句子的一部分
        """
        k = comma_pos + 1
        while k < n and text[k] in ' \t\r\n':
            k += 1
        if k >= n:
            return True
        ch = text[k]
        # { [ ] } → JSON 结构
        if ch in ('{', '[', ']', '}'):
            return True
        # 数字
        if ch.isdigit() or ch == '-':
            return True
        # boolean / null
        tail = text[k:]
        if tail.startswith(('true', 'null', 'false')):
            return True
        # "key": 模式 → 下一个键值对
        if ch == '"':
            close_q = text.find('"', k + 1)
            if close_q != -1:
                p = close_q + 1
                while p < n and text[p] in ' \t\r\n':
                    p += 1
                if p < n and text[p] == ':':
                    return True
        return False

    @staticmethod
    def _fix_unescaped_quotes(text: str) -> str:
        """修复 JSON 字符串值内部未转义的 ASCII 双引号。

        LLM 经常在中文场景描述或英文 prompt 中插入裸引号，如：
          "scene_description": "...写着"进门请消毒"。灯光..."
          "positive_prompt": "...label \"MINOR INJURIES\", an orange kit..."
        这里的内嵌 " 会破坏 JSON 解析。

        策略：逐字符扫描，追踪是否在字符串值内部。
        遇到 " 时根据后续上下文判断：
          - 后跟 : ] } 或 EOF → 字符串结束
          - 后跟 , → 进一步检查逗号后面是否有 JSON 结构模式（"key": / { / 数字等）
          - 其他 → 内嵌裸引号，转义为 \\"
        """
        result: list[str] = []
        i = 0
        n = len(text)
        in_string = False

        while i < n:
            ch = text[i]

            if ch == '\\' and in_string:
                # 转义序列，原样保留两个字符
                result.append(text[i:i + 2])
                i += 2
                continue

            if ch == '"':
                if not in_string:
                    # 字符串开始
                    in_string = True
                    result.append(ch)
                else:
                    # 判断这个 " 是字符串结束，还是内嵌裸引号
                    j = i + 1
                    while j < n and text[j] in ' \t\r\n':
                        j += 1
                    next_ch = text[j] if j < n else ''

                    if next_ch in (':', ']', '}', ''):
                        # 明确的字符串结束
                        in_string = False
                        result.append(ch)
                    elif next_ch == ',':
                        # 逗号有歧义：可能是 JSON 分隔符，也可能是英文散文中的逗号
                        # 进一步检查逗号之后是否跟着 JSON 结构
                        if JudgeAgent._is_json_after_comma(text, j, n):
                            in_string = False
                            result.append(ch)
                        else:
                            result.append('\\"')
                    else:
                        # 内嵌裸引号 → 转义
                        result.append('\\"')
            else:
                result.append(ch)

            i += 1

        return ''.join(result)

    def _parse_enriched_payload(self, raw: str) -> list[dict[str, Any]]:
        text = (raw or "").strip()
        if not text:
            return []

        decoder = json.JSONDecoder()

        candidates: list[str] = [text]

        fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        candidates.extend(block for block in fenced_blocks if block.strip())

        for start in ("[", "{"):
            idx = text.find(start)
            if idx != -1:
                candidates.append(text[idx:])

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue

            # 先尝试原样解析
            for attempt_text in (candidate, self._fix_unescaped_quotes(candidate)):
                try:
                    payload = json.loads(attempt_text)
                    items = self._coerce_prompt_items(payload)
                    if items:
                        return items
                except json.JSONDecodeError:
                    pass

            # raw_decode 兜底（同样先原样，再修复）
            for attempt_text in (candidate, self._fix_unescaped_quotes(candidate)):
                for match in re.finditer(r"\[|\{", attempt_text):
                    start = match.start()
                    try:
                        payload, _ = decoder.raw_decode(attempt_text[start:])
                        items = self._coerce_prompt_items(payload)
                        if items:
                            return items
                    except json.JSONDecodeError:
                        continue

        # 截断恢复：如果 JSON 数组被截断，尝试找到最后一个完整的 } 并闭合数组
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            for attempt_text in (candidate, self._fix_unescaped_quotes(candidate)):
                arr_start = attempt_text.find('[')
                if arr_start == -1:
                    continue
                fragment = attempt_text[arr_start:]
                # 从末尾向前找最后一个完整对象的 }
                last_brace = fragment.rfind('}')
                if last_brace == -1:
                    continue
                truncated = fragment[:last_brace + 1].rstrip().rstrip(',') + ']'
                try:
                    payload = json.loads(truncated)
                    items = self._coerce_prompt_items(payload)
                    if items:
                        print(f"   [INFO] 截断恢复成功，从不完整 JSON 中提取到 {len(items)} 个片段")
                        return items
                except json.JSONDecodeError:
                    continue

        return []

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
        # enriched prompt 通常很长（每片段 ~800 token），给足输出空间
        enrich_max_tokens = max(self.llm_config.max_tokens, 32768)

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

        # 诊断日志：截断检测 + 原始内容预览
        if finish_reason == "length":
            print(f"[WARN] LLM 输出因 max_tokens({enrich_max_tokens}) 被截断，JSON 可能不完整。")
        if not raw.strip():
            print("[WARN] LLM 返回了空内容。")

        data = self._parse_enriched_payload(raw)
        if not data:
            # 保存原始返回用于调试（使用绝对路径，确保不受 cwd 影响）
            try:
                from datetime import datetime as _dt
                output_dir = Path(__file__).resolve().parent.parent / "output"
                output_dir.mkdir(parents=True, exist_ok=True)
                debug_file = output_dir / f"_debug_enriched_{_dt.now().strftime('%H%M%S')}.txt"
                debug_file.write_text(raw, encoding="utf-8")
                print(f"[WARN] 裁判生成的 enriched prompt 解析失败。原始返回已保存: {debug_file}")
            except Exception as e:
                print(f"[WARN] 裁判生成的 enriched prompt 解析失败（debug 保存也失败: {e}）")
            print(f"   finish_reason={finish_reason}, raw_length={len(raw)}, raw_preview={raw[:300]!r}...")
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
