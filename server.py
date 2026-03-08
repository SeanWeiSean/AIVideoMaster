"""
Video Pipeline API Server
为 Electron UI 提供 HTTP API，桥接现有的 Pipeline 功能。
支持 SSE 实时推送讨论进度。

存储设计：
  - Job ID = YYYYMMDD_HHMMSS 时间戳（人类可读，与输出文件夹一一对应）
  - 每个 Job 的数据存储在 output/{job_id}/ 目录下：
      job.json         — 元数据（状态、参数、结果）
      prompts.json     — 讨论生成的 prompt
      discussion.md    — 讨论过程记录
      clip_001.mp4 ... — 视频片段
      final.mp4        — 合成视频
  - 服务器启动时扫描 output/ 恢复所有历史 Job
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import struct
import sys
import threading
import time
import zlib
from base64 import b64encode as _b64encode
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PipelineConfig, LLMConfig, VideoConfig, ImageGenConfig
from agents.discussion import DiscussionOrchestrator, DiscussionResult
from agents.novel_discussion import NovelDiscussionOrchestrator, NovelPipelineResult
from agents.prompt_optimizer import PromptOptimizerAgent
from agents.image_creator import ImageArchitect, ImageDescriptor
from video.comfyui_image import ComfyUIImageClient, ImageJob
from video.i2v_generator import I2VGenerator, I2VJob
from video.ltx_i2v_generator import LtxI2VGenerator, LtxI2VJob
from video.keyframe_i2v_generator import KeyframeI2VGenerator, KeyframeI2VJob
from templates import TemplateStore


# ── 空白图像生成（文生图模式，不需要用户上传图片）─────────────────

def _make_blank_png_b64(width: int = 512, height: int = 512) -> str:
    """用标准库生成白色 PNG（RGB）并返回 base64。"""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    sig   = b'\x89PNG\r\n\x1a\n'
    ihdr  = _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    raw   = b''.join(b'\x00' + b'\xff\xff\xff' * width for _ in range(height))
    idat  = _chunk(b'IDAT', zlib.compress(raw, 1))
    iend  = _chunk(b'IEND', b'')
    return _b64encode(sig + ihdr + idat + iend).decode()


# ── 持久化 Job 存储 ──────────────────────────────────────────

class JobStore:
    """管理 pipeline Job，所有数据持久化到 output/{job_id}/ 目录。
    
    Job ID 格式: YYYYMMDD_HHMMSS（如 20260225_203423）
    重启后自动从磁盘恢复。
    """

    def __init__(self, output_dir: str = "./output") -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        # 启动时从磁盘恢复
        self._discover_jobs()

    # ── Job ID 生成 ──

    @staticmethod
    def generate_id() -> str:
        """生成新的 Job ID（时间戳格式）"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _job_dir(self, job_id: str) -> Path:
        return self._output_dir / job_id

    # ── 创建 & 获取 ──

    def create(self, mode: str = "topic", title: str = "") -> str:
        """创建新 Job 并立即持久化"""
        job_id = self.generate_id()
        # 防止同一秒内重复
        while job_id in self._jobs:
            time.sleep(0.1)
            job_id = self.generate_id()

        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        job = {
            "id": job_id,
            "status": "created",   # created | running | done | error
            "mode": mode,          # topic | novel
            "title": title,        # 主题或小说摘要
            "logs": [],            # 实时日志行（仅内存，不持久化）
            "result": None,        # 最终结果 JSON
            "error": "",
            "created_at": time.time(),
            "finished_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        self._save_meta(job_id)
        return job_id

    def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def list_all(self) -> list[dict]:
        """返回所有 Job 的摘要信息（按创建时间倒序）"""
        items = []
        for jid, j in self._jobs.items():
            result = j.get("result") or {}
            items.append({
                "id": jid,
                "mode": j.get("mode", "topic"),
                "title": j.get("title", ""),
                "status": j["status"],
                "created_at": j["created_at"],
                "finished_at": j.get("finished_at"),
                "has_video": bool(result.get("final_video")),
                "clip_count": len(result.get("clips", [])),
            })
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items

    # ── 状态更新（自动持久化）──

    def append_log(self, job_id: str, line: str) -> None:
        j = self._jobs.get(job_id)
        if j:
            j["logs"].append(line)

    def set_status(self, job_id: str, status: str) -> None:
        j = self._jobs.get(job_id)
        if j:
            j["status"] = status
            if status in ("done", "error"):
                j["finished_at"] = time.time()
            self._save_meta(job_id)

    def set_result(self, job_id: str, result: Any) -> None:
        j = self._jobs.get(job_id)
        if j:
            j["result"] = result
            self._save_meta(job_id)

    def set_error(self, job_id: str, error: str) -> None:
        j = self._jobs.get(job_id)
        if j:
            j["error"] = error
            j["status"] = "error"
            j["finished_at"] = time.time()
            self._save_meta(job_id)

    # ── 持久化 ──

    def _save_meta(self, job_id: str) -> None:
        """将 Job 元数据写入 output/{job_id}/job.json"""
        j = self._jobs.get(job_id)
        if not j:
            return
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        meta_path = job_dir / "job.json"
        # 持久化时排除大日志（日志太大，只保留运行期间的内存版本）
        meta = {k: v for k, v in j.items() if k != "logs"}
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] 保存 job.json 失败 [{job_id}]: {e}")

    # ── 启动时恢复 ──

    def _discover_jobs(self) -> None:
        """扫描 output/ 目录，从磁盘恢复所有历史 Job"""
        count_new = 0
        count_legacy = 0

        # 1) 扫描有 job.json 的目录（新格式）
        for job_json in sorted(self._output_dir.glob("*/job.json")):
            job_id = job_json.parent.name
            if job_id in self._jobs:
                continue
            try:
                with open(job_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["logs"] = []  # 日志不持久化
                meta.setdefault("id", job_id)
                self._jobs[job_id] = meta
                count_new += 1
            except Exception as e:
                print(f"[WARN] 读取 {job_json} 失败: {e}")

        # 2) 扫描旧格式数据（output/prompts_YYYYMMDD_HHMMSS.json + 同名文件夹）
        #    为它们创建 job.json 以便统一管理
        for prompts_file in sorted(self._output_dir.glob("prompts_????????_??????.json")):
            match = re.search(r"prompts_(\d{8}_\d{6})\.json", prompts_file.name)
            if not match:
                continue
            job_id = match.group(1)
            if job_id in self._jobs:
                continue
            try:
                job = self._import_legacy_job(job_id, prompts_file)
                if job:
                    self._jobs[job_id] = job
                    self._save_meta(job_id)
                    count_legacy += 1
            except Exception as e:
                print(f"[WARN] 导入旧数据 {prompts_file.name} 失败: {e}")

        # 3) 扫描旧格式小说数据（output/novel_prompts_YYYYMMDD_HHMMSS.json）
        for prompts_file in sorted(self._output_dir.glob("novel_prompts_????????_??????.json")):
            match = re.search(r"novel_prompts_(\d{8}_\d{6})\.json", prompts_file.name)
            if not match:
                continue
            job_id = match.group(1)
            if job_id in self._jobs:
                continue
            try:
                job = self._import_legacy_novel_job(job_id, prompts_file)
                if job:
                    self._jobs[job_id] = job
                    self._save_meta(job_id)
                    count_legacy += 1
            except Exception as e:
                print(f"[WARN] 导入旧数据 {prompts_file.name} 失败: {e}")

        if count_new or count_legacy:
            print(f"[INFO] 已恢复 {count_new + count_legacy} 个历史 Job（新格式 {count_new}，旧数据导入 {count_legacy}）")

    def _import_legacy_job(self, job_id: str, prompts_file: Path) -> dict | None:
        """从旧格式 prompts_*.json 导入为标准 Job"""
        with open(prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        topic = data.get("topic", "")
        segments = data.get("segments", [])

        # 检查是否有对应的 clips 文件夹
        clip_dir = self._output_dir / job_id
        clips = []
        if clip_dir.is_dir():
            for mp4 in sorted(clip_dir.glob("clip_*.mp4")):
                idx_match = re.search(r"clip_(\d+)\.mp4", mp4.name)
                if idx_match:
                    clips.append({
                        "index": int(idx_match.group(1)),
                        "file_path": str(mp4),
                        "status": "success",
                        "error": "",
                    })

        # 检查最终视频
        final_video = ""
        final_path = self._output_dir / f"final_{job_id}.mp4"
        if final_path.exists():
            # 移动到 job 目录内
            new_final = clip_dir / "final.mp4" if clip_dir.is_dir() else final_path
            if clip_dir.is_dir() and not (clip_dir / "final.mp4").exists():
                try:
                    import shutil
                    shutil.copy2(final_path, new_final)
                except Exception:
                    new_final = final_path
            final_video = str(new_final)

        # 检查讨论记录
        discussion_file = self._output_dir / f"discussion_{job_id}.md"

        # 推算创建时间
        try:
            dt = datetime.strptime(job_id, "%Y%m%d_%H%M%S")
            created_at = dt.timestamp()
        except ValueError:
            created_at = prompts_file.stat().st_mtime

        result_data = {
            "topic": topic,
            "visual_style": data.get("visual_style", ""),
            "segments": [
                {
                    "index": s.get("index", i + 1),
                    "time_range": s.get("time_range", ""),
                    "copywriting": s.get("copywriting", ""),
                    "scene_description": s.get("scene_description", ""),
                    "camera_type": s.get("camera_type", ""),
                    "positive_prompt": s.get("positive_prompt", ""),
                    "negative_prompt": s.get("negative_prompt", ""),
                }
                for i, s in enumerate(segments)
            ],
            "clips": clips,
            "prompts_json": str(prompts_file),
        }
        if final_video:
            result_data["final_video"] = final_video
        if discussion_file.exists():
            result_data["discussion_file"] = str(discussion_file)

        return {
            "id": job_id,
            "status": "done",
            "mode": "topic",
            "title": topic[:100] if topic else f"旧任务 {job_id}",
            "logs": [],
            "result": result_data,
            "error": "",
            "created_at": created_at,
            "finished_at": created_at,
        }

    def _import_legacy_novel_job(self, job_id: str, prompts_file: Path) -> dict | None:
        """从旧格式 novel_prompts_*.json 导入为标准 Job"""
        with open(prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        novel_text = data.get("novel_text", "")
        segments = data.get("segments", [])

        try:
            dt = datetime.strptime(job_id, "%Y%m%d_%H%M%S")
            created_at = dt.timestamp()
        except ValueError:
            created_at = prompts_file.stat().st_mtime

        result_data = {
            "novel_text": novel_text[:200] if novel_text else "",
            "visual_style": data.get("visual_style", ""),
            "segments": [
                {
                    "index": s.get("index", i + 1),
                    "time_range": s.get("time_range", ""),
                    "narration": s.get("narration", ""),
                    "scene_description": s.get("scene_description", ""),
                    "camera_type": s.get("camera_type", ""),
                    "image_prompt": s.get("image_prompt", ""),
                    "video_prompt": s.get("video_prompt", ""),
                    "negative_prompt": s.get("negative_prompt", ""),
                }
                for i, s in enumerate(segments)
            ],
            "prompts_json": str(prompts_file),
        }

        return {
            "id": job_id,
            "status": "done",
            "mode": "novel",
            "title": novel_text[:100] if novel_text else f"旧任务 {job_id}",
            "logs": [],
            "result": result_data,
            "error": "",
            "created_at": created_at,
            "finished_at": created_at,
        }


jobs = JobStore()
template_store = TemplateStore()

# ── 当前配置（可通过 API 修改）────────────────────────────────

_current_config: dict = {
    "llm_api_key": os.getenv("LLM_API_KEY", "no-key"),
    "llm_base_url": os.getenv("LLM_BASE_URL", "http://localhost:23333/api/openai/v1"),
    "llm_model": os.getenv("LLM_MODEL", "claude-opus-4.6"),
    "comfyui_url": os.getenv("COMFYUI_URL", "http://localhost:8188"),
    "quality_mode": "fast",
    "width": 640,
    "height": 640,
    "length": 81,
    "fps": 16,
    "max_rounds": 3,
    "output_dir": "./output",
    "image_api_url": os.getenv("IMAGE_GEN_URL", ""),
    "image_api_key": os.getenv("IMAGE_GEN_KEY", ""),
}


def _build_config() -> PipelineConfig:
    c = _current_config
    return PipelineConfig(
        llm=LLMConfig(
            api_key=c["llm_api_key"],
            base_url=c["llm_base_url"],
            model=c["llm_model"],
        ),
        video=VideoConfig(
            comfyui_url=c["comfyui_url"],
            quality_mode=c["quality_mode"],
            width=c["width"],
            height=c["height"],
            length=c["length"],
            fps=c["fps"],
            output_dir=c["output_dir"],
        ),
        image_gen=ImageGenConfig(
            api_url=c["image_api_url"],
            api_key=c["image_api_key"],
        ),
        max_discussion_rounds=c["max_rounds"],
    )


# ── 日志捕获 ─────────────────────────────────────────────────

class LogCapture(io.StringIO):
    """捕获 print 输出并推送到 job logs"""

    def __init__(self, job_id: str, original_stdout) -> None:
        super().__init__()
        self.job_id = job_id
        self.original = original_stdout

    def write(self, s: str) -> int:
        if s.strip():
            jobs.append_log(self.job_id, s.rstrip())
        try:
            self.original.write(s)
        except (UnicodeEncodeError, OSError):
            pass
        return len(s)

    def flush(self) -> None:
        self.original.flush()


# ── Pipeline 运行线程 ────────────────────────────────────────

def _run_topic_pipeline(job_id: str, topic: str, discuss_only: bool) -> None:
    """在后台线程中运行主题管线"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        config = _build_config()
        orchestrator = DiscussionOrchestrator(config)
        result = orchestrator.run(topic)

        # 保存讨论结果到 Job 目录
        job_dir = str(jobs._job_dir(job_id))
        from main import save_discussion_result, save_prompts_json
        save_discussion_result(result, job_dir)
        json_path = save_prompts_json(result, job_dir)

        # 构建结果
        result_data = {
            "topic": result.topic,
            "rounds_used": result.rounds_used,
            "approved": result.approved,
            "visual_style": result.visual_style,
            "prompts_json": json_path,
            "segments": [
                {
                    "index": p.index,
                    "time_range": p.time_range,
                    "duration_seconds": getattr(p, "duration_seconds", 5),
                    "copywriting": p.copywriting,
                    "scene_description": p.scene_description,
                    "camera_type": p.camera_type,
                    "positive_prompt": p.video_prompt,
                    "negative_prompt": p.negative_prompt,
                }
                for p in result.final_prompts
            ],
        }

        if not discuss_only and result.final_prompts:
            # 视频生成 — 使用 job_id 作为 session_name，clips 存到 job 目录
            from video.generator import VideoGenerator
            from video.composer import VideoComposer
            generator = VideoGenerator(config.video)
            clips = generator.generate_all(result.final_prompts, job_id)
            result_data["clips"] = [
                {"index": c.index, "file_path": c.file_path, "status": c.status, "error": c.error}
                for c in clips
            ]

            # 视频合成
            valid_clips = [c for c in clips if c.status == "success"]
            if valid_clips:
                try:
                    composer = VideoComposer(config.video.output_dir)
                    output_name = f"{job_id}/final.mp4"
                    final_path = composer.compose(valid_clips, output_name)
                    result_data["final_video"] = final_path
                    print(f"\n[OK] 最终视频已合成: {final_path}")
                except Exception as e:
                    print(f"\n[WARN] 视频合成失败: {e}")
                    result_data["compose_error"] = str(e)
            else:
                print("\n[WARN] 没有成功的视频片段，跳过合成")

        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


def _run_novel_pipeline(job_id: str, novel_text: str, discuss_only: bool) -> None:
    """在后台线程中运行小说改编管线"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        config = _build_config()
        orchestrator = NovelDiscussionOrchestrator(config)
        result: NovelPipelineResult = orchestrator.run(novel_text)

        # 保存到 Job 目录
        job_dir = str(jobs._job_dir(job_id))
        from main import save_novel_result, save_novel_prompts_json
        save_novel_result(result, job_dir)
        json_path = save_novel_prompts_json(result, job_dir)

        result_data = {
            "novel_text": result.novel_text[:200],
            "rounds_used": result.rounds_used,
            "approved": result.approved,
            "visual_style": result.visual_style,
            "prompts_json": json_path,
            "segments": [
                {
                    "index": p.index,
                    "time_range": p.time_range,
                    "duration_seconds": getattr(p, "duration_seconds", 5),
                    "narration": p.narration,
                    "scene_description": p.scene_description,
                    "camera_type": p.camera_type,
                    "image_prompt": p.image_prompt,
                    "video_prompt": p.video_prompt,
                    "negative_prompt": p.negative_prompt,
                }
                for p in result.final_prompts
            ],
        }

        if not discuss_only and result.final_prompts:
            from video.generator import VideoGenerator
            from video.composer import VideoComposer
            generator = VideoGenerator(config.video)
            clips = generator.generate_all(result.final_prompts, job_id)
            result_data["clips"] = [
                {"index": c.index, "file_path": c.file_path, "status": c.status, "error": c.error}
                for c in clips
            ]

            valid_clips = [c for c in clips if c.status == "success"]
            if valid_clips:
                try:
                    composer = VideoComposer(config.video.output_dir)
                    output_name = f"{job_id}/final.mp4"
                    final_path = composer.compose(valid_clips, output_name)
                    result_data["final_video"] = final_path
                    print(f"\n[OK] 最终视频已合成: {final_path}")
                except Exception as e:
                    print(f"\n[WARN] 视频合成失败: {e}")
                    result_data["compose_error"] = str(e)
            else:
                print("\n[WARN] 没有成功的视频片段，跳过合成")

        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


# ── 图片生成线程 ──────────────────────────────────────────────

def _run_image_task(job_id: str, mode: str, positive_prompt: str,
                    negative_prompt: str, input_image_b64: str,
                    seed: int | None, steps: int | None,
                    denoise: float | None,
                    workflow_version: str = "v2") -> None:
    """在后台线程运行图片创建/编辑任务"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")
        client = ComfyUIImageClient(comfyui_url, output_dir)

        if not client.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        mode_label = "图片创建" if mode == "create" else "图片编辑"
        print(f"[{mode.upper()}] {mode_label}")
        print(f"[{mode.upper()}] 正向提示: {positive_prompt[:100]}")
        print(f"[{mode.upper()}] 输入图片: {len(input_image_b64) / 1024:.0f} KB (base64)")

        if mode == "create":
            result = client.image_create(
                positive_prompt=positive_prompt,
                input_image_b64=input_image_b64,
                negative_prompt=negative_prompt,
                seed=seed, steps=steps, denoise=denoise,
                output_name=f"create_{job_id}.png",
                workflow_version=workflow_version,
            )
        else:
            result = client.image_edit(
                positive_prompt=positive_prompt,
                input_image_b64=input_image_b64,
                negative_prompt=negative_prompt,
                seed=seed, steps=steps, denoise=denoise,
                output_name=f"edit_{job_id}.png",
            )

        result_data = {
            "mode": mode,
            "status": result.status,
            "file_path": result.file_path,
            "error": result.error,
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
        }
        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done" if result.status == "success" else "error")

        if result.status == "success":
            print(f"[OK] {mode_label}完成: {result.file_path}")
        else:
            print(f"[FAIL] {mode_label}失败: {result.error}")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


# ── 双智能体图片创作线程 ─────────────────────────────────────

def _run_image_agent_task(
    job_id: str,
    user_intent: str,
    input_image_b64: str,
    count: int,
    steps: int | None,
    denoise: float | None,
    seed: int | None,
    use_agent: bool = True,
    workflow_version: str = "v2",
) -> None:
    """在后台线程运行图片创作流水线。use_agent=True 时启用建筑师+描述师润色；False 时直接提交用户输入。"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        llm_cfg = LLMConfig(
            api_key=_current_config.get("llm_api_key", "no-key"),
            base_url=_current_config.get("llm_base_url", "http://localhost:23333/api/openai/v1"),
            model=_current_config.get("llm_model", "claude-opus-4.6"),
        )
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")

        client = ComfyUIImageClient(comfyui_url, output_dir)
        if not client.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        # V1模式需要参考图；无图时自动使用白色画布
        if not input_image_b64 and workflow_version == "v1":
            input_image_b64 = _make_blank_png_b64()
            print("[创作] V1 模式：使用空白画布作为基础")

        architect = ImageArchitect(llm_cfg) if use_agent else None
        descriptor = ImageDescriptor(llm_cfg) if use_agent else None

        slots: list[dict] = []

        for i in range(count):
            slot: dict = {
                "index": i,
                "user_intent": user_intent,
                "blueprint": "",
                "prompt": "",
                "file_path": "",
                "status": "pending",
                "error": "",
            }
            slots.append(slot)

            print(f"\n{'='*50}")
            if use_agent:
                print(f"[创作 {i+1}/{count}] 建筑师开始扩充蓝图...")
            else:
                print(f"[创作 {i+1}/{count}] 直接模式，直接提交 Prompt...")
            print(f"{'='*50}")

            try:
                if use_agent:
                    # 1. 建筑师扩充
                    blueprint = architect.expand(user_intent)
                    slot["blueprint"] = blueprint
                    print(f"[建筑师] 蓝图生成完毕（{len(blueprint)} 字）")
                    print(f"\n--- 蓝图预览 ---\n{blueprint[:600]}{'...' if len(blueprint)>600 else ''}\n")

                    # 实时通知前端（把蓝图 + 阶段更新写入 result 供轮询）
                    jobs.set_result(job_id, {
                        "mode": "create-agent",
                        "status": "running",
                        "slots": [dict(s) for s in slots],
                    })

                    # 2. 描述师生成 Prompt
                    print(f"[创作 {i+1}/{count}] 描述师生成 Prompt...")
                    prompt = descriptor.generate_prompt(blueprint)
                    slot["prompt"] = prompt
                    print(f"[描述师] Prompt（{len(prompt)} 字）：\n{prompt}\n")

                    # 再次通知前端（prompt 已生成）
                    jobs.set_result(job_id, {
                        "mode": "create-agent",
                        "status": "running",
                        "slots": [dict(s) for s in slots],
                    })
                else:
                    # 直接模式：跳过智能体，直接用用户输入作为 Prompt
                    slot["blueprint"] = ""
                    slot["prompt"] = user_intent
                    print(f"[直接模式] 跳过智能体，使用原始输入作为 Prompt")
                    jobs.set_result(job_id, {
                        "mode": "create-agent",
                        "status": "running",
                        "slots": [dict(s) for s in slots],
                    })

                # 3. 提交 ComfyUI 生图
                print(f"[创作 {i+1}/{count}] 提交 ComfyUI 生图中...")
                slot["status"] = "generating"
                jobs.set_result(job_id, {
                    "mode": "create-agent",
                    "status": "running",
                    "slots": [dict(s) for s in slots],
                })

                slot_seed = (seed + i) if seed is not None else None
                output_name = f"agent_create_{job_id}_{i:02d}.png"
                result = client.image_create(
                    positive_prompt=slot["prompt"],
                    input_image_b64=input_image_b64,
                    negative_prompt="",
                    seed=slot_seed,
                    steps=steps,
                    denoise=denoise,
                    output_name=output_name,
                    workflow_version=workflow_version,
                )

                if result.status == "success":
                    slot["file_path"] = result.file_path
                    slot["status"] = "success"
                    print(f"[OK] 第 {i+1} 张图片已保存: {result.file_path}")
                else:
                    slot["status"] = "failed"
                    slot["error"] = result.error
                    print(f"[FAIL] 第 {i+1} 张图片生成失败: {result.error}")

            except Exception as e:
                slot["status"] = "failed"
                slot["error"] = str(e)
                print(f"[ERROR] 第 {i+1} 槽出错: {e}")

            # 每个 slot 完成后更新结果
            jobs.set_result(job_id, {
                "mode": "create-agent",
                "status": "running",
                "slots": [dict(s) for s in slots],
            })

        # 全部完成
        all_ok = all(s["status"] == "success" for s in slots)
        final_result = {
            "mode": "create-agent",
            "status": "success" if all_ok else "partial",
            "slots": slots,
        }
        jobs.set_result(job_id, final_result)
        jobs.set_status(job_id, "done")
        print(f"\n[完成] 全部 {count} 张图片创作结束。")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


def _run_image_regen_task(
    job_id: str,
    slot_index: int,
    prompt: str,
    input_image_b64: str,
    steps: int | None,
    denoise: float | None,
    seed: int | None,
    workflow_version: str = "v2",
) -> None:
    """重新生成某一个 slot 的图片（保留 prompt，只换 seed 重新跑 ComfyUI）"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")
        client = ComfyUIImageClient(comfyui_url, output_dir)

        if not client.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        # V1模式需要参考图
        if not input_image_b64 and workflow_version == "v1":
            input_image_b64 = _make_blank_png_b64()

        print(f"[Regen] 重新生成 slot {slot_index}，prompt：{prompt[:80]}")

        ts = int(time.time())
        output_name = f"agent_regen_{job_id}_{slot_index:02d}_{ts}.png"
        result = client.image_create(
            positive_prompt=prompt,
            input_image_b64=input_image_b64,
            negative_prompt="",
            seed=seed,
            steps=steps,
            denoise=denoise,
            output_name=output_name,
            workflow_version=workflow_version,
        )

        # 更新对应 slot
        meta = jobs.get(job_id)
        if meta:
            res = meta.get("result", {})
            slots: list = res.get("slots", [])
            for s in slots:
                if s.get("index") == slot_index:
                    if result.status == "success":
                        s["file_path"] = result.file_path
                        s["status"] = "success"
                        s["error"] = ""
                        print(f"[OK] Regen 完成: {result.file_path}")
                    else:
                        s["status"] = "failed"
                        s["error"] = result.error
                        print(f"[FAIL] Regen 失败: {result.error}")
                    break
            jobs.set_result(job_id, res)

    except Exception as e:
        print(f"[ERROR] Regen 出错: {e}")
    finally:
        sys.stdout = old_stdout


# ── I2V 视频生成线程 ─────────────────────────────────────────

def _run_i2v_task(job_id: str, positive_prompt: str, negative_prompt: str,
                  input_image_b64: str, width: int, height: int,
                  length: int, seed: int | None, use_fast_lora: bool) -> None:
    """在后台线程运行 I2V 图生视频任务"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")
        generator = I2VGenerator(comfyui_url, output_dir)

        if not generator.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        mode_label = "4步快速" if use_fast_lora else "20步标准"
        print(f"[I2V] 图生视频 ({mode_label})")
        print(f"[I2V] 正向提示: {positive_prompt[:100]}")
        print(f"[I2V] 输入图片: {len(input_image_b64) / 1024:.0f} KB (base64)")
        print(f"[I2V] 参数: {width}x{height}, {length}帧")

        result = generator.generate(
            positive_prompt=positive_prompt,
            input_image_b64=input_image_b64,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            length=length,
            seed=seed,
            use_fast_lora=use_fast_lora,
            output_name=f"i2v_{job_id}.mp4",
        )

        result_data = {
            "mode": "i2v",
            "status": result.status,
            "file_path": result.file_path,
            "error": result.error,
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "length": length,
            "use_fast_lora": use_fast_lora,
        }
        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done" if result.status == "success" else "error")

        if result.status == "success":
            print(f"[OK] I2V 视频完成: {result.file_path}")
        else:
            print(f"[FAIL] I2V 视频失败: {result.error}")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


# ── LTX I2V 视频生成线程 ─────────────────────────────────────

def _run_ltx_i2v_task(job_id: str, positive_prompt: str, negative_prompt: str,
                      input_image_b64: str, width: int, height: int,
                      length: int, seed: int | None,
                      steps: int, cfg_pass1: float, cfg_pass2: float) -> None:
    """在后台线程运行 LTX-2.0 I2V 图生视频任务"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")
        generator = LtxI2VGenerator(comfyui_url, output_dir)

        if not generator.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        print(f"[LTX-I2V] 图生视频 (LTX-2.0)")
        print(f"[LTX-I2V] 正向提示: {positive_prompt[:100]}")
        print(f"[LTX-I2V] 输入图片: {len(input_image_b64) / 1024:.0f} KB (base64)")
        print(f"[LTX-I2V] 参数: {width}x{height}, {length}帧, {steps}步, CFG={cfg_pass1}/{cfg_pass2}")

        result = generator.generate(
            positive_prompt=positive_prompt,
            input_image_b64=input_image_b64,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            length=length,
            seed=seed,
            steps=steps,
            cfg_pass1=cfg_pass1,
            cfg_pass2=cfg_pass2,
            output_name=f"ltx_i2v_{job_id}.mp4",
        )

        result_data = {
            "mode": "ltx-i2v",
            "status": result.status,
            "file_path": result.file_path,
            "error": result.error,
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "length": length,
            "steps": steps,
            "cfg_pass1": cfg_pass1,
            "cfg_pass2": cfg_pass2,
        }
        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done" if result.status == "success" else "error")

        if result.status == "success":
            print(f"[OK] LTX I2V 视频完成: {result.file_path}")
        else:
            print(f"[FAIL] LTX I2V 视频失败: {result.error}")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


# ── 6关键帧 I2V 视频生成线程 ─────────────────────────────────

def _run_keyframe_i2v_task(
    job_id: str,
    images_b64: list[str],
    prompts: list[str],
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    seed: int | None,
    fps: int,
) -> None:
    """在后台线程运行 6关键帧 I2V 视频生成任务"""
    capture = LogCapture(job_id, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        jobs.set_status(job_id, "running")
        comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
        output_dir = _current_config.get("output_dir", "./output")
        generator = KeyframeI2VGenerator(comfyui_url, output_dir)

        if not generator.check_connection():
            raise ConnectionError(f"无法连接 ComfyUI: {comfyui_url}")

        print(f"[KF6-I2V] 6关键帧视频生成")
        print(f"[KF6-I2V] 收到 {len(images_b64)} 张关键帧, {len(prompts)} 段提示词")
        print(f"[KF6-I2V] 参数: {width}x{height}, 每段{length}帧, fps={fps}")

        result = generator.generate(
            images_b64=images_b64,
            prompts=prompts,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            length=length,
            seed=seed,
            fps=fps,
            output_name=f"kf6_i2v_{job_id}.mp4",
        )

        result_data = {
            "mode": "keyframe-i2v",
            "status": result.status,
            "file_path": result.file_path,
            "error": result.error,
            "prompts": prompts,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "length": length,
            "fps": fps,
            "frame_count": len(images_b64),
        }
        jobs.set_result(job_id, result_data)
        jobs.set_status(job_id, "done" if result.status == "success" else "error")

        if result.status == "success":
            print(f"[OK] 6关键帧视频完成: {result.file_path}")
        else:
            print(f"[FAIL] 6关键帧视频失败: {result.error}")

    except Exception as e:
        jobs.set_error(job_id, str(e))
    finally:
        sys.stdout = old_stdout


# ── HTTP API Handler ─────────────────────────────────────────

class APIHandler(BaseHTTPRequestHandler):
    """简单的 HTTP API 服务"""

    def _set_headers(self, status: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json_response(self, data: Any, status: int = 200) -> None:
        self._set_headers(status)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, file_path: str) -> None:
        """服务静态文件（Electron 离线时的备用）"""
        ext_map = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        ext = Path(file_path).suffix.lower()
        content_type = ext_map.get(ext, "application/octet-stream")

        full_path = Path(__file__).parent / "ui" / "renderer" / file_path.lstrip("/")
        if not full_path.is_file():
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        with open(full_path, "rb") as f:
            self.wfile.write(f.read())

    def _serve_output_file(self, file_path: str) -> None:
        """安全地从 output 目录提供文件（视频等）"""
        from urllib.parse import unquote
        file_path = unquote(file_path)
        resolved = Path(file_path).resolve()
        output_root = Path(_current_config["output_dir"]).resolve()
        # 安全检查：只允许访问 output 目录下的文件
        if not str(resolved).startswith(str(output_root)):
            self.send_error(403, "Access denied")
            return
        if not resolved.is_file():
            self.send_error(404, "File not found")
            return
        ext = resolved.suffix.lower()
        mime_map = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".gif": "image/gif",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".json": "application/json",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }
        content_type = mime_map.get(ext, "application/octet-stream")
        file_size = resolved.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(resolved, "rb") as f:
            self.wfile.write(f.read())

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── API 路由 ──
        if path == "/api/config":
            self._json_response(_current_config)

        elif path == "/api/templates":
            templates = template_store.list_templates()
            self._json_response([
                {
                    "name": t.name,
                    "positive_prompt": t.positive_prompt,
                    "negative_prompt": t.negative_prompt,
                    "tags": t.tags,
                    "description": t.description,
                    "source_topic": t.source_topic,
                    "source_segment": t.source_segment,
                    "quality_score": t.quality_score,
                    "created_at": t.created_at,
                }
                for t in templates
            ])

        elif path.startswith("/api/session/"):
            sid = path.split("/")[-1]
            job = jobs.get(sid)
            if not job:
                self._json_response({"error": "Job not found"}, 404)
                return
            self._json_response({
                "status": job["status"],
                "log_count": len(job["logs"]),
                "error": job["error"],
                "result": job["result"],
            })

        elif path.startswith("/api/session-logs/"):
            sid = path.split("/")[-1]
            job = jobs.get(sid)
            if not job:
                self._json_response({"error": "Job not found"}, 404)
                return
            after = int(params.get("after", [0])[0])
            logs = job["logs"][after:]
            self._json_response({
                "logs": logs,
                "total": len(job["logs"]),
                "status": job["status"],
                "result": job.get("result"),   # 实时结果，供智能体进度轮询使用
            })

        elif path == "/api/jobs":
            self._json_response(jobs.list_all())

        elif path.startswith("/api/jobs/"):
            job_id = path.split("/api/jobs/", 1)[1]
            job = jobs.get(job_id)
            if not job:
                self._json_response({"error": "Job not found"}, 404)
                return
            self._json_response({
                "id": job_id,
                "mode": job.get("mode", "topic"),
                "title": job.get("title", ""),
                "status": job["status"],
                "error": job["error"],
                "created_at": job["created_at"],
                "finished_at": job.get("finished_at"),
                "log_count": len(job["logs"]),
                "logs": job["logs"],
                "result": job["result"],
            })

        elif path == "/api/file":
            file_path = params.get("path", [""])[0]
            if not file_path:
                self._json_response({"error": "path is required"}, 400)
                return
            self._serve_output_file(file_path)

        elif path == "/api/health":
            # 检测 ComfyUI 连接
            comfyui_ok = False
            comfyui_url = _current_config.get("comfyui_url", "http://localhost:8188")
            try:
                from video.generator import ComfyUIClient
                comfyui_ok = ComfyUIClient(comfyui_url).is_alive()
            except Exception:
                pass
            self._json_response({
                "status": "ok",
                "time": datetime.now().isoformat(),
                "comfyui_connected": comfyui_ok,
                "comfyui_url": comfyui_url,
            })

        # ── 静态文件 ──
        elif path == "/" or path == "/index.html":
            self._serve_static("index.html")
        elif path.startswith("/"):
            self._serve_static(path)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/topic/start":
            body = self._read_body()
            topic = body.get("topic", "")
            discuss_only = body.get("discuss_only", False)
            if not topic:
                self._json_response({"error": "topic is required"}, 400)
                return
            job_id = jobs.create(mode="topic", title=topic[:100])
            t = threading.Thread(
                target=_run_topic_pipeline,
                args=(job_id, topic, discuss_only),
                daemon=True,
            )
            t.start()
            self._json_response({"session_id": job_id, "job_id": job_id})

        elif path == "/api/novel/start":
            body = self._read_body()
            novel_text = body.get("novel_text", "")
            discuss_only = body.get("discuss_only", False)
            if not novel_text:
                self._json_response({"error": "novel_text is required"}, 400)
                return
            job_id = jobs.create(mode="novel", title=novel_text[:100])
            t = threading.Thread(
                target=_run_novel_pipeline,
                args=(job_id, novel_text, discuss_only),
                daemon=True,
            )
            t.start()
            self._json_response({"session_id": job_id, "job_id": job_id})

        elif path == "/api/config":
            body = self._read_body()
            _current_config.update(body)
            self._json_response({"status": "ok"})

        elif path == "/api/prompt/optimize":
            body = self._read_body()
            text = body.get("text", "")
            mode = body.get("mode", "t2v")  # "t2v" | "i2v" | "ltx-i2v"
            if not text:
                self._json_response({"error": "text is required"}, 400)
                return
            try:
                config = _build_config()
                optimizer = PromptOptimizerAgent(config.llm)
                result = optimizer.optimize(text, mode=mode)
                self._json_response({
                    "original_text": result.original_text,
                    "positive_prompt": result.positive_prompt,
                    "negative_prompt": result.negative_prompt,
                    "analysis": result.analysis,
                })
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        elif path == "/api/templates":
            body = self._read_body()
            template_store.save_from_segment(
                name=body.get("name", ""),
                positive_prompt=body.get("positive_prompt", ""),
                negative_prompt=body.get("negative_prompt", ""),
                tags=body.get("tags", []),
                description=body.get("description", ""),
                source_topic=body.get("source_topic", ""),
                source_segment=body.get("source_segment", 0),
                quality_score=body.get("quality_score", 0.0),
            )
            self._json_response({"status": "ok"})

        elif path in ("/api/image/create", "/api/image/edit"):
            body = self._read_body()
            mode = "create" if path.endswith("/create") else "edit"
            positive_prompt = body.get("positive_prompt", "")
            input_image = body.get("input_image", "")
            workflow_version = body.get("workflow_version", "v2")
            if not positive_prompt:
                self._json_response({"error": "positive_prompt is required"}, 400)
                return
            # V2 create 是纯文生图，无需输入图；V1 create 和 edit 需要输入图
            needs_image = (mode == "edit") or (mode == "create" and workflow_version == "v1")
            if needs_image and not input_image:
                self._json_response({"error": "input_image (base64) is required"}, 400)
                return
            negative_prompt = body.get("negative_prompt", "")
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)
            steps = body.get("steps")
            if steps is not None:
                steps = int(steps)
            denoise = body.get("denoise")
            if denoise is not None:
                denoise = float(denoise)

            mode_label = "Create" if mode == "create" else "Edit"
            job_id = jobs.create(mode=mode, title=f"{mode_label}: {positive_prompt[:60]}")
            t = threading.Thread(
                target=_run_image_task,
                args=(job_id, mode, positive_prompt, negative_prompt,
                      input_image, seed, steps, denoise, workflow_version),
                daemon=True,
            )
            t.start()
            self._json_response({"job_id": job_id, "session_id": job_id})

        elif path == "/api/image/create-with-agent":
            body = self._read_body()
            user_intent = body.get("user_intent", "").strip()
            input_image = body.get("input_image", "")   # 可选，空则自动使用白色画布
            use_agent = bool(body.get("use_agent", True))
            workflow_version = body.get("workflow_version", "v2")
            if not user_intent:
                self._json_response({"error": "user_intent is required"}, 400)
                return
            count = max(1, min(8, int(body.get("count", 1))))
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)
            steps = body.get("steps")
            if steps is not None:
                steps = int(steps)
            denoise = body.get("denoise")
            if denoise is not None:
                denoise = float(denoise)

            mode_label = "AI创作(智能体)" if use_agent else "AI创作(直接)"
            job_id = jobs.create(mode="create-agent", title=f"{mode_label}: {user_intent[:50]}")
            t = threading.Thread(
                target=_run_image_agent_task,
                args=(job_id, user_intent, input_image, count, steps, denoise, seed, use_agent, workflow_version),
                daemon=True,
            )
            t.start()
            self._json_response({"job_id": job_id, "session_id": job_id})

        elif path == "/api/image/regenerate":
            body = self._read_body()
            job_id = body.get("job_id", "")
            slot_index = int(body.get("slot_index", 0))
            prompt = body.get("prompt", "")
            input_image = body.get("input_image", "")   # 可选
            workflow_version = body.get("workflow_version", "v2")
            if not job_id or not prompt:
                self._json_response({"error": "job_id, prompt required"}, 400)
                return
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)
            steps = body.get("steps")
            if steps is not None:
                steps = int(steps)
            denoise = body.get("denoise")
            if denoise is not None:
                denoise = float(denoise)

            # 先把对应 slot 标记为 regenerating
            meta = jobs.get(job_id)
            if meta:
                res = meta.get("result", {})
                for s in res.get("slots", []):
                    if s.get("index") == slot_index:
                        s["status"] = "generating"
                        break
                jobs.set_result(job_id, res)

            t = threading.Thread(
                target=_run_image_regen_task,
                args=(job_id, slot_index, prompt, input_image, steps, denoise, seed, workflow_version),
                daemon=True,
            )
            t.start()
            self._json_response({"status": "ok", "job_id": job_id})

        elif path == "/api/video/i2v":
            body = self._read_body()
            positive_prompt = body.get("positive_prompt", "")
            input_image = body.get("input_image", "")
            if not positive_prompt:
                self._json_response({"error": "positive_prompt is required"}, 400)
                return
            if not input_image:
                self._json_response({"error": "input_image (base64) is required"}, 400)
                return
            negative_prompt = body.get("negative_prompt", "")
            width = int(body.get("width", 1088))
            height = int(body.get("height", 720))
            length = int(body.get("length", 81))
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)
            use_fast_lora = body.get("use_fast_lora", True)

            job_id = jobs.create(mode="i2v", title=f"I2V: {positive_prompt[:60]}")
            t = threading.Thread(
                target=_run_i2v_task,
                args=(job_id, positive_prompt, negative_prompt, input_image,
                      width, height, length, seed, use_fast_lora),
                daemon=True,
            )
            t.start()
            self._json_response({"job_id": job_id, "session_id": job_id})

        elif path == "/api/video/ltx-i2v":
            body = self._read_body()
            positive_prompt = body.get("positive_prompt", "")
            input_image = body.get("input_image", "")
            if not positive_prompt:
                self._json_response({"error": "positive_prompt is required"}, 400)
                return
            if not input_image:
                self._json_response({"error": "input_image (base64) is required"}, 400)
                return
            negative_prompt = body.get("negative_prompt", "")
            width = int(body.get("width", 1280))
            height = int(body.get("height", 720))
            length = int(body.get("length", 241))
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)
            steps = int(body.get("steps", 20))
            cfg_pass1 = float(body.get("cfg_pass1", 4.0))
            cfg_pass2 = float(body.get("cfg_pass2", 1.0))

            job_id = jobs.create(mode="ltx-i2v", title=f"LTX-I2V: {positive_prompt[:60]}")
            t = threading.Thread(
                target=_run_ltx_i2v_task,
                args=(job_id, positive_prompt, negative_prompt, input_image,
                      width, height, length, seed,
                      steps, cfg_pass1, cfg_pass2),
                daemon=True,
            )
            t.start()
            self._json_response({"job_id": job_id, "session_id": job_id})

        elif path == "/api/video/keyframe-i2v":
            body = self._read_body()
            # images: list of 6 base64 strings
            images_b64 = body.get("images", [])
            if len(images_b64) != 6:
                self._json_response(
                    {"error": f"images must contain exactly 6 base64 frames, got {len(images_b64)}"}, 400
                )
                return
            # prompts: list of up to 5 strings (one per segment)
            prompts = body.get("prompts", [])
            if not isinstance(prompts, list):
                prompts = [prompts] if prompts else []
            negative_prompt = body.get("negative_prompt", "")
            width = int(body.get("width", 720))
            height = int(body.get("height", 720))
            length = int(body.get("length", 25))
            fps = int(body.get("fps", 24))
            seed = body.get("seed")
            if seed is not None:
                seed = int(seed)

            title_preview = (prompts[0][:50] if prompts else "6关键帧视频")
            job_id = jobs.create(mode="keyframe-i2v", title=f"KF6-I2V: {title_preview}")
            t = threading.Thread(
                target=_run_keyframe_i2v_task,
                args=(job_id, images_b64, prompts, negative_prompt,
                      width, height, length, seed, fps),
                daemon=True,
            )
            t.start()
            self._json_response({"job_id": job_id, "session_id": job_id})

        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/templates/"):
            name = path.split("/api/templates/", 1)[1]
            from urllib.parse import unquote
            name = unquote(name)
            ok = template_store.delete_template(name)
            self._json_response({"deleted": ok})
        else:
            self.send_error(404)

    def log_message(self, format, *args) -> None:
        """安静一点，不打印每个 HTTP 请求"""
        pass


def start_server(port: int = 5678) -> None:
    # Windows 控制台可能不支持 UTF-8 emoji，设置 stdout 编码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    server = HTTPServer(("127.0.0.1", port), APIHandler)
    print(f"API Server running at http://127.0.0.1:{port}")
    print(f"   UI: http://127.0.0.1:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Video Pipeline API Server")
    parser.add_argument("--port", type=int, default=5678, help="Server port")
    args = parser.parse_args()
    start_server(args.port)
