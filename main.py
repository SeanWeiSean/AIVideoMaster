"""
Video Pipeline - 主入口
多 Agent 协作视频生成管线

用法:
    python main.py                      # 交互模式
    python main.py --topic "你的主题"    # 直接指定主题
    python main.py --discuss-only       # 只进行讨论，不生成视频
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from config import PipelineConfig, LLMConfig, VideoConfig
from agents.discussion import DiscussionOrchestrator, DiscussionResult
from video.generator import VideoGenerator
from video.composer import VideoComposer


def save_discussion_result(result: DiscussionResult, output_dir: str) -> str:
    """保存讨论结果到文件"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = out_path / f"discussion_{timestamp}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 视频方案讨论记录\n\n")
        f.write(f"- **主题**: {result.topic}\n")
        f.write(f"- **讨论轮数**: {result.rounds_used}\n")
        f.write(f"- **是否通过**: {'✅ 是' if result.approved else '❌ 否'}\n")
        f.write(f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("---\n\n")
        f.write("## 讨论过程\n\n")
        for msg in result.history:
            role_label = {
                "copywriter": "📝 文案师",
                "cinematographer": "🎬 镜头师",
                "judge": "⚖️ 裁判",
            }.get(msg.role, msg.role)
            f.write(f"### [第{msg.round_num}轮] {role_label}\n\n")
            f.write(f"{msg.content}\n\n---\n\n")

        if result.visual_style:
            f.write("## 视觉风格\n\n")
            f.write(f"{result.visual_style}\n\n")

        if result.final_prompts:
            f.write("## 最终视频生成 Prompts（裁判 Enriched）\n\n")
            for p in result.final_prompts:
                f.write(f"### 片段 {p.index}（{p.time_range}）\n\n")
                f.write(f"- **文案**: {p.copywriting}\n")
                f.write(f"- **画面描述**: {p.scene_description}\n")
                f.write(f"- **镜头类型**: {p.camera_type}\n")
                f.write(f"- **Positive Prompt**: {p.video_prompt}\n")
                f.write(f"- **Negative Prompt**: {p.negative_prompt}\n\n")

    print(f"📄 讨论记录已保存: {filename}")
    return str(filename)


def save_prompts_json(result: DiscussionResult, output_dir: str) -> str:
    """将最终 Prompt 保存为 JSON 方便后续处理"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = out_path / f"prompts_{timestamp}.json"

    data = {
        "topic": result.topic,
        "visual_style": result.visual_style,
        "segments": [
            {
                "index": p.index,
                "time_range": p.time_range,
                "copywriting": p.copywriting,
                "scene_description": p.scene_description,
                "camera_type": p.camera_type,
                "positive_prompt": p.video_prompt,
                "negative_prompt": p.negative_prompt,
            }
            for p in result.final_prompts
        ],
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"📋 Prompt JSON 已保存: {filename}")
    return str(filename)


def run_pipeline(topic: str, config: PipelineConfig, discuss_only: bool = False) -> None:
    """运行完整的视频生成管线"""

    print("\n" + "=" * 60)
    print("  🎬 Video Pipeline - 多 Agent 视频生成管线")
    print("=" * 60)
    print(f"\n📌 主题: {topic}\n")

    # Phase 1: 多 Agent 讨论
    print("=" * 60)
    print("  Phase 1: 多 Agent 讨论")
    print("=" * 60)

    orchestrator = DiscussionOrchestrator(config)
    result = orchestrator.run(topic)

    # 保存讨论结果
    save_discussion_result(result, config.video.output_dir)
    save_prompts_json(result, config.video.output_dir)

    if not result.final_prompts:
        print("\n⚠️ 未能提取到视频生成 Prompt，请检查讨论记录。")
        return

    print(f"\n📊 生成了 {len(result.final_prompts)} 个视频片段的 Enriched Prompt")
    for p in result.final_prompts:
        print(f"   片段 {p.index}（{p.time_range}）")
        print(f"      ➕ {p.video_prompt[:80]}...")
        print(f"      ➖ {p.negative_prompt[:80]}{'...' if len(p.negative_prompt) > 80 else ''}")

    if discuss_only:
        print("\n✅ 仅讨论模式，跳过视频生成。")
        return

    # Phase 2: 用户确认
    print("\n" + "=" * 60)
    print("  Phase 2: 确认方案")
    print("=" * 60)

    proceed = input("\n是否开始生成视频？(y/n): ").strip().lower()
    if proceed != "y":
        print("已取消视频生成。")
        return

    # Phase 3: 视频生成
    print("\n" + "=" * 60)
    print("  Phase 3: 视频生成")
    print("=" * 60)

    session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    generator = VideoGenerator(config.video)
    clips = generator.generate_all(result.final_prompts, session_name)

    # Phase 4: 用户审核
    print("\n" + "=" * 60)
    print("  Phase 4: 审核视频片段")
    print("=" * 60)

    composer = VideoComposer(config.video.output_dir)
    selected = composer.interactive_select(clips)

    # 检查是否有需要重新生成的片段
    pending = [c for c in selected if c.status == "pending"]
    if pending:
        print(f"\n🔄 有 {len(pending)} 个片段需要重新生成...")
        # 找到对应的 prompt 重新生成
        for clip in pending:
            prompt = next(
                (p for p in result.final_prompts if p.index == clip.index), None
            )
            if prompt:
                new_clip = generator._generate_single(
                    prompt, Path(config.video.output_dir) / session_name
                )
                clip.file_path = new_clip.file_path
                clip.status = new_clip.status
                clip.error = new_clip.error

    # Phase 5: 视频合成
    valid_clips = [c for c in selected if c.status == "success"]
    if not valid_clips:
        print("\n❌ 没有可用的视频片段，无法合成。")
        return

    print("\n" + "=" * 60)
    print("  Phase 5: 视频合成")
    print("=" * 60)

    output_name = f"final_{session_name}.mp4"
    try:
        output_path = composer.compose(valid_clips, output_name)
        print(f"\n🎉 最终视频: {output_path}")
    except Exception as e:
        print(f"\n❌ 视频合成失败: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Video Pipeline - 多 Agent 视频生成管线")
    parser.add_argument("--topic", type=str, help="视频主题")
    parser.add_argument("--discuss-only", action="store_true", help="只进行讨论，不生成视频")
    parser.add_argument("--api-key", type=str, help="LLM API Key")
    parser.add_argument("--base-url", type=str, help="LLM API Base URL")
    parser.add_argument("--model", type=str, help="LLM Model 名称")
    parser.add_argument("--comfyui-url", type=str, help="ComfyUI API 地址")
    parser.add_argument("--workflow", type=str, default="", help="ComfyUI 工作流 JSON 路径（留空用内置默认）")
    parser.add_argument("--quality", type=str, default="fast", choices=["fast", "quality"],
                        help="视频质量模式: fast=Lora4步快速(~60s), quality=标准20步高质量(~10min)")
    parser.add_argument("--width", type=int, default=640, help="视频宽度")
    parser.add_argument("--height", type=int, default=640, help="视频高度")
    parser.add_argument("--length", type=int, default=81, help="视频帧数")
    parser.add_argument("--fps", type=int, default=16, help="视频帧率")
    parser.add_argument("--output-dir", type=str, default="./output", help="输出目录")
    parser.add_argument("--max-rounds", type=int, default=3, help="最大讨论轮数")

    args = parser.parse_args()

    # 构建配置
    config = PipelineConfig(
        llm=LLMConfig(
            api_key=args.api_key or os.getenv("LLM_API_KEY", "no-key"),
            base_url=args.base_url or os.getenv("LLM_BASE_URL", "http://localhost:23333/api/openai/v1"),
            model=args.model or os.getenv("LLM_MODEL", "claude-opus-4.6"),
        ),
        video=VideoConfig(
            comfyui_url=args.comfyui_url or os.getenv("COMFYUI_URL", "http://localhost:8189"),
            workflow_path=args.workflow,
            quality_mode=args.quality,
            width=args.width,
            height=args.height,
            length=args.length,
            fps=args.fps,
            output_dir=args.output_dir,
        ),
        max_discussion_rounds=args.max_rounds,
    )

    # 检查 API key
    if not config.llm.api_key or config.llm.api_key == "no-key":
        print("ℹ️ 未设置 LLM API Key，使用本地代理 (Agent Maestro)")

    # 获取主题
    topic = args.topic
    if not topic:
        topic = input("请输入视频主题: ").strip()
        if not topic:
            print("❌ 主题不能为空")
            sys.exit(1)

    run_pipeline(topic, config, discuss_only=args.discuss_only)


if __name__ == "__main__":
    main()
