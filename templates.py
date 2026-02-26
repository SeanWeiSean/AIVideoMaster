"""
TemplateStore - 优秀 Prompt 模板存储
保存效果好的 prompt 作为模板，后续生成时可作为风格参考。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


_DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "templates.json"


@dataclass
class PromptTemplate:
    """一条优秀 prompt 模板"""
    name: str                  # 模板名称（用户自定义）
    positive_prompt: str       # 正向 prompt
    negative_prompt: str       # 反向 prompt
    tags: list[str]            # 标签，如 ["末日", "庇护所", "暗黑"]
    description: str = ""      # 描述说明
    source_topic: str = ""     # 来源主题
    source_segment: int = 0    # 来源片段序号
    created_at: str = ""       # 创建时间
    quality_score: float = 0.0 # 质量评分（0-10）


class TemplateStore:
    """模板存储管理器"""

    def __init__(self, store_path: str | Path | None = None) -> None:
        self.store_path = Path(store_path) if store_path else _DEFAULT_STORE_PATH
        self._templates: dict[str, PromptTemplate] = {}
        self._load()

    # ── 持久化 ────────────────────────────────────────────────

    def _load(self) -> None:
        """从 JSON 文件加载模板"""
        if not self.store_path.is_file():
            self._templates = {}
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._templates = {
                name: PromptTemplate(**item)
                for name, item in data.items()
            }
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[WARN] 模板文件加载失败: {e}")
            self._templates = {}

    def _save(self) -> None:
        """保存模板到 JSON 文件"""
        data = {name: asdict(t) for name, t in self._templates.items()}
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── CRUD ──────────────────────────────────────────────────

    def save_template(self, template: PromptTemplate) -> None:
        """保存一个模板（按 name 去重，同名覆盖）"""
        if not template.created_at:
            template.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._templates[template.name] = template
        self._save()
        print(f"[OK] 模板已保存: 「{template.name}」")

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """按名称获取模板"""
        return self._templates.get(name)

    def list_templates(self) -> list[PromptTemplate]:
        """列出所有模板"""
        return list(self._templates.values())

    def search_by_tag(self, tag: str) -> list[PromptTemplate]:
        """按标签搜索模板"""
        tag_lower = tag.lower()
        return [t for t in self._templates.values()
                if any(tag_lower in tg.lower() for tg in t.tags)]

    def delete_template(self, name: str) -> bool:
        """删除模板"""
        if name in self._templates:
            del self._templates[name]
            self._save()
            print(f"[OK] 模板已删除: 「{name}」")
            return True
        print(f"[WARN] 未找到模板: 「{name}」")
        return False

    def show_all(self) -> None:
        """打印所有模板摘要"""
        templates = self.list_templates()
        if not templates:
            print("暂无保存的模板")
            return
        print(f"\n已保存 {len(templates)} 个优秀模板:\n")
        for i, t in enumerate(templates, 1):
            tags_str = ", ".join(t.tags) if t.tags else "无标签"
            prompt_preview = t.positive_prompt[:80] + "..." if len(t.positive_prompt) > 80 else t.positive_prompt
            print(f"  {i}. 「{t.name}」 [{tags_str}]")
            if t.description:
                print(f"     {t.description}")
            print(f"     + {prompt_preview}")
            if t.quality_score > 0:
                print(f"     评分: {t.quality_score}/10")
            print()

    # ── 便捷方法 ──────────────────────────────────────────────

    def save_from_segment(
        self,
        name: str,
        positive_prompt: str,
        negative_prompt: str,
        tags: list[str] | None = None,
        description: str = "",
        source_topic: str = "",
        source_segment: int = 0,
        quality_score: float = 0.0,
    ) -> PromptTemplate:
        """从一个生成片段快速保存模板"""
        template = PromptTemplate(
            name=name,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            tags=tags or [],
            description=description,
            source_topic=source_topic,
            source_segment=source_segment,
            quality_score=quality_score,
        )
        self.save_template(template)
        return template

    def get_style_reference(self, name: str) -> str:
        """获取模板的风格参考文本，供 LLM 参考生成同风格 prompt"""
        t = self.get_template(name)
        if not t:
            return ""
        return (
            f"=== 风格参考模板: 「{t.name}」 ===\n"
            f"描述: {t.description}\n"
            f"Positive Prompt:\n{t.positive_prompt}\n\n"
            f"Negative Prompt:\n{t.negative_prompt}\n"
            f"=== 参考结束 ==="
        )
