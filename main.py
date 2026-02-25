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

from config import PipelineConfig, LLMConfig, VideoConfig, ImageGenConfig
from agents.discussion import DiscussionOrchestrator, DiscussionResult
from agents.novel_discussion import NovelDiscussionOrchestrator, NovelPipelineResult, NovelSegmentPrompt
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
    """运行完整的视频生成管线（主题模式 T2V）"""

    print("\n" + "=" * 60)
    print("  🎬 Video Pipeline - 主题模式 (T2V)")
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


def save_novel_result(result: NovelPipelineResult, output_dir: str) -> str:
    """保存小说改编讨论结果"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = out_path / f"novel_discussion_{timestamp}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("# 小说改编讨论记录\n\n")
        f.write(f"- **讨论轮数**: {result.rounds_used}\n")
        f.write(f"- **是否通过**: {'✅ 是' if result.approved else '❌ 否'}\n")
        f.write(f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 原始小说文字\n\n")
        f.write(f"{result.novel_text}\n\n---\n\n")

        f.write("## 讨论过程\n\n")
        for msg in result.history:
            role_label = {
                "scene_analyzer": "📖 场景分析师",
                "cinematographer": "🎬 镜头师",
                "judge": "⚖️ 裁判",
            }.get(msg.role, msg.role)
            f.write(f"### [第{msg.round_num}轮] {role_label}\n\n")
            f.write(f"{msg.content}\n\n---\n\n")

        if result.visual_style:
            f.write("## 视觉风格\n\n")
            f.write(f"{result.visual_style}\n\n")

        if result.final_prompts:
            f.write("## 最终 Prompts\n\n")
            for p in result.final_prompts:
                f.write(f"### 片段 {p.index}（{p.time_range}）\n\n")
                f.write(f"- **旁白**: {p.narration}\n")
                f.write(f"- **场景描述**: {p.scene_description}\n")
                f.write(f"- **镜头类型**: {p.camera_type}\n")
                f.write(f"- **参考图 Prompt**: {p.image_prompt}\n")
                f.write(f"- **视频动作 Prompt**: {p.video_prompt}\n")
                f.write(f"- **Negative Prompt**: {p.negative_prompt}\n\n")

    print(f"📄 讨论记录已保存: {filename}")
    return str(filename)


def save_novel_prompts_json(result: NovelPipelineResult, output_dir: str) -> str:
    """将小说改编 Prompt 保存为 JSON"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = out_path / f"novel_prompts_{timestamp}.json"

    data = {
        "mode": "novel",
        "novel_text": result.novel_text,
        "visual_style": result.visual_style,
        "segments": [
            {
                "index": p.index,
                "time_range": p.time_range,
                "narration": p.narration,
                "scene_description": p.scene_description,
                "camera_type": p.camera_type,
                "image_prompt": p.image_prompt,
                "video_prompt": p.video_prompt,
                "negative_prompt": p.negative_prompt,
                "ref_image_path": p.ref_image_path,
            }
            for p in result.final_prompts
        ],
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"📋 Prompt JSON 已保存: {filename}")
    return str(filename)


def run_novel_pipeline(novel_text: str, config: PipelineConfig, discuss_only: bool = False) -> None:
    """运行小说改编视频生成管线（I2V 模式）"""

    print("\n" + "=" * 60)
    print("  📖 Video Pipeline - 小说改编模式 (I2V)")
    print("=" * 60)
    print(f"\n📌 小说文字（{len(novel_text)} 字）:\n")
    preview = novel_text[:200] + "..." if len(novel_text) > 200 else novel_text
    print(f"   {preview}\n")

    # Phase 1: 多 Agent 讨论（场景分析师 → 镜头师 → 裁判）
    print("=" * 60)
    print("  Phase 1: 场景分析与分镜设计")
    print("=" * 60)

    orchestrator = NovelDiscussionOrchestrator(config)
    result = orchestrator.run(novel_text)

    # 保存讨论结果
    save_novel_result(result, config.video.output_dir)
    save_novel_prompts_json(result, config.video.output_dir)

    if not result.final_prompts:
        print("\n⚠️ 未能生成 Prompt，请检查讨论记录。")
        return

    print(f"\n📊 生成了 {len(result.final_prompts)} 个视频片段")
    for p in result.final_prompts:
        print(f"   片段 {p.index}（{p.time_range}）")
        print(f"      🖼️ 参考图: {p.image_prompt[:80]}...")
        print(f"      🎬 视频动作: {p.video_prompt[:80]}...")
        print(f"      📝 旁白: {p.narration[:50]}...")

    if discuss_only:
        print("\n✅ 仅讨论模式，跳过视频生成。")
        return

    # Phase 2: 用户确认
    print("\n" + "=" * 60)
    print("  Phase 2: 确认方案")
    print("=" * 60)

    proceed = input("\n是否开始生成参考图和视频？(y/n): ").strip().lower()
    if proceed != "y":
        print("已取消。")
        return

    # Phase 3: 生成参考图
    print("\n" + "=" * 60)
    print("  Phase 3: 生成参考图")
    print("=" * 60)

    if not config.image_gen.api_url:
        print("\n⚠️ 未配置参考图生成 API (--image-api)，跳过参考图生成。")
        print("   请手动生成参考图后放入对应目录，或配置 IMAGE_GEN_URL 环境变量。")
        print("   Prompt JSON 已保存，可用于手动生成。")
    else:
        from video.image_generator import QwenImageGenerator, ImageGeneratorPipeline

        img_gen = QwenImageGenerator(
            base_url=config.image_gen.api_url,
            api_key=config.image_gen.api_key,
            timeout=config.image_gen.timeout,
        )
        img_pipeline = ImageGeneratorPipeline(img_gen, config.video.output_dir)

        session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_prompts = [
            {"index": p.index, "image_prompt": p.image_prompt, "negative_prompt": p.negative_prompt}
            for p in result.final_prompts
        ]
        images = img_pipeline.generate_all(
            img_prompts, session_name=session_name,
            width=config.image_gen.width, height=config.image_gen.height,
        )

        # 将参考图路径写回 result
        for img in images:
            for p in result.final_prompts:
                if p.index == img.index and img.status == "success":
                    p.ref_image_path = img.file_path

        # 更新保存的 JSON（包含参考图路径）
        save_novel_prompts_json(result, config.video.output_dir)

        success_count = sum(1 for img in images if img.status == "success")
        print(f"\n✅ 参考图生成完成: {success_count}/{len(images)} 张成功")

    # Phase 4: I2V 视频生成
    print("\n" + "=" * 60)
    print("  Phase 4: I2V 视频生成")
    print("=" * 60)

    # 检查是否有参考图
    has_images = any(p.ref_image_path for p in result.final_prompts)
    if not has_images:
        print("\n⚠️ 没有参考图，无法进行 I2V 视频生成。")
        print("   请先生成参考图（配置 --image-api），或手动指定图片路径后重新运行。")
        print("   Prompt JSON 已保存，可手动处理。")
        return

    # TODO: 用户提供 I2V 工作流 API 后，在此接入
    print("\n⚠️ I2V 视频生成等待接入（用户提供 ComfyUI I2V 工作流后启用）。")
    print("   当前已输出所有 Prompt + 参考图，可手动在 ComfyUI 中生成。")
    print("   后续提供 I2V API 格式后将自动化此步骤。")

    # Phase 5: 审核 + 合成（复用现有 composer）
    # 在 I2V 接入后启用
    print("\n" + "=" * 60)
    print("  Phase 5: 审核与合成（待 I2V 接入后启用）")
    print("=" * 60)
    print("   📋 所有 Prompt 和参考图已保存到 output/ 目录。")
    print("   📝 旁白文字已保存在 JSON 的 narration 字段中，供后期配音使用。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Video Pipeline - 多 Agent 视频生成管线")
    parser.add_argument("--mode", type=str, default="topic", choices=["topic", "novel"],
                        help="运行模式: topic=主题创作(T2V), novel=小说改编(I2V)")
    parser.add_argument("--topic", type=str, help="视频主题（topic 模式）")
    parser.add_argument("--novel", type=str, help="小说文字（novel 模式，直接传文本）")
    parser.add_argument("--novel-file", type=str, help="小说文件路径（novel 模式，从文件读取）")
    parser.add_argument("--discuss-only", action="store_true", help="只进行讨论，不生成视频/图片")
    parser.add_argument("--api-key", type=str, help="LLM API Key")
    parser.add_argument("--base-url", type=str, help="LLM API Base URL")
    parser.add_argument("--model", type=str, help="LLM Model 名称")
    parser.add_argument("--comfyui-url", type=str, help="ComfyUI API 地址")
    parser.add_argument("--workflow", type=str, default="", help="ComfyUI 工作流 JSON 路径（留空用内置默认）")
    parser.add_argument("--quality", type=str, default="fast", choices=["fast", "quality", "cocktail_lora"],
                        help="视频质量模式: fast=Lora4步快速(~60s), quality=标准20步高质量(~10min), cocktail_lora=鸡尾酒LoRA(10步)")
    parser.add_argument("--width", type=int, default=640, help="视频宽度")
    parser.add_argument("--height", type=int, default=640, help="视频高度")
    parser.add_argument("--length", type=int, default=81, help="视频帧数")
    parser.add_argument("--fps", type=int, default=16, help="视频帧率")
    parser.add_argument("--output-dir", type=str, default="./output", help="输出目录")
    parser.add_argument("--max-rounds", type=int, default=3, help="最大讨论轮数")
    parser.add_argument("--image-api", type=str, help="参考图生成 API 地址（novel 模式）")
    parser.add_argument("--image-key", type=str, help="参考图生成 API Key（novel 模式）")

    args = parser.parse_args()

    # 构建配置
    config = PipelineConfig(
        llm=LLMConfig(
            api_key=args.api_key or os.getenv("LLM_API_KEY", "no-key"),
            base_url=args.base_url or os.getenv("LLM_BASE_URL", "http://localhost:23333/api/openai/v1"),
            model=args.model or os.getenv("LLM_MODEL", "claude-opus-4.6"),
        ),
        video=VideoConfig(
            comfyui_url=args.comfyui_url or os.getenv("COMFYUI_URL", "http://localhost:8188"),
            workflow_path=args.workflow,
            quality_mode=args.quality,
            width=args.width,
            height=args.height,
            length=args.length,
            fps=args.fps,
            output_dir=args.output_dir,
        ),
        image_gen=ImageGenConfig(
            api_url=args.image_api or os.getenv("IMAGE_GEN_URL", ""),
            api_key=args.image_key or os.getenv("IMAGE_GEN_KEY", ""),
        ),
        max_discussion_rounds=args.max_rounds,
    )

    # 检查 API key
    if not config.llm.api_key or config.llm.api_key == "no-key":
        print("ℹ️ 未设置 LLM API Key，使用本地代理 (Agent Maestro)")

    # 根据模式运行
    if args.mode == "novel":
        # 小说改编模式
        novel_text = args.novel
        if args.novel_file:
            with open(args.novel_file, "r", encoding="utf-8") as f:
                novel_text = f.read().strip()
        if not novel_text:
            novel_text = input("请输入小说文字（输入 END 结束）:\n")
            if novel_text.strip().upper() == "END":
                print("❌ 输入为空")
                sys.exit(1)
            # 支持多行输入
            lines = [novel_text]
            while True:
                line = input()
                if line.strip().upper() == "END":
                    break
                lines.append(line)
            novel_text = "\n".join(lines)

        run_novel_pipeline(novel_text, config, discuss_only=args.discuss_only)
    else:
        # 主题创作模式
        topic = args.topic
        if not topic:
            topic = input("请输入视频主题: ").strip()
            if not topic:
                print("❌ 主题不能为空")
                sys.exit(1)

        run_pipeline(topic, config, discuss_only=args.discuss_only)


if __name__ == "__main__":
    main()
