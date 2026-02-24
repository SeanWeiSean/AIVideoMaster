"""
VideoComposer - 视频合成器
将多段视频片段合成为完整视频。
"""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from video.generator import GeneratedClip


class VideoComposer:
    """使用 ffmpeg 将选定的视频片段合成为最终视频"""

    def __init__(self, output_dir: str = "./output") -> None:
        self.output_dir = Path(output_dir)
        self._check_ffmpeg()

    def _check_ffmpeg(self) -> None:
        """检查 ffmpeg 是否可用"""
        if not shutil.which("ffmpeg"):
            print("⚠️ 未检测到 ffmpeg，视频合成功能将不可用。")
            print("  请安装 ffmpeg: https://ffmpeg.org/download.html")

    def compose(
        self,
        clips: list[GeneratedClip],
        output_name: str = "final_output.mp4",
    ) -> str:
        """将选定的视频片段按顺序合成"""
        # 过滤出成功的片段
        valid_clips = [c for c in clips if c.status == "success"]
        if not valid_clips:
            raise ValueError("没有可用的视频片段进行合成")

        # 按 index 排序
        valid_clips.sort(key=lambda c: c.index)

        output_path = self.output_dir / output_name

        # 创建 ffmpeg 合并列表文件
        concat_list_path = self.output_dir / "concat_list.txt"
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for clip in valid_clips:
                # ffmpeg 要求用正斜杠或转义
                escaped_path = clip.file_path.replace("\\", "/")
                f.write(f"file '{escaped_path}'\n")

        # 使用 ffmpeg concat 合并
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(output_path),
        ]

        try:
            print(f"\n🎞️ 正在合成视频...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print(f"⚠️ ffmpeg 输出: {result.stderr}")
                # 尝试重编码方式合并
                return self._compose_with_reencode(valid_clips, output_path)

            print(f"✅ 视频合成完成: {output_path}")
            return str(output_path)

        except FileNotFoundError:
            print("❌ ffmpeg 未找到，无法合成视频。")
            raise
        except subprocess.TimeoutExpired:
            print("❌ 视频合成超时。")
            raise
        finally:
            # 清理临时文件
            concat_list_path.unlink(missing_ok=True)

    def _compose_with_reencode(
        self,
        clips: list[GeneratedClip],
        output_path: Path,
    ) -> str:
        """使用重编码方式合并视频（兼容性更好但更慢）"""
        # 构建 filter_complex 用于多输入合并
        inputs: list[str] = []
        filter_parts: list[str] = []
        for i, clip in enumerate(clips):
            inputs.extend(["-i", clip.file_path])
            filter_parts.append(f"[{i}:v:0][{i}:a:0]")

        # 如果没有音轨，使用纯视频合并
        filter_str = "".join(f"[{i}:v:0]" for i in range(len(clips)))
        filter_str += f"concat=n={len(clips)}:v=1:a=0[outv]"

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[outv]",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"视频合成失败: {result.stderr}")

        print(f"✅ 视频合成完成（重编码模式）: {output_path}")
        return str(output_path)

    @staticmethod
    def interactive_select(clips: list[GeneratedClip]) -> list[GeneratedClip]:
        """交互式让用户选择要使用的片段"""
        print("\n" + "=" * 60)
        print("  📋 请审核生成的视频片段")
        print("=" * 60)

        selected: list[GeneratedClip] = []

        for clip in clips:
            if clip.status != "success":
                print(f"\n片段 {clip.index}: ❌ 生成失败 - {clip.error}")
                continue

            print(f"\n片段 {clip.index}: {clip.file_path}")
            print(f"  Prompt: {clip.prompt[:100]}...")

            while True:
                choice = input("  是否使用该片段？(y=使用 / n=跳过 / r=重新生成): ").strip().lower()
                if choice in ("y", "n", "r"):
                    break
                print("  请输入 y, n 或 r")

            if choice == "y":
                selected.append(clip)
            elif choice == "r":
                # 标记需要重新生成
                clip.status = "pending"
                selected.append(clip)

        return selected
