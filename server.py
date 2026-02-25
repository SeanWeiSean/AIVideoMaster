"""
Video Pipeline API Server
为 Electron UI 提供 HTTP API，桥接现有的 Pipeline 功能。
支持 SSE 实时推送讨论进度。
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import uuid
from contextlib import redirect_stdout
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
from templates import TemplateStore


# ── 全局状态 ──────────────────────────────────────────────────

class SessionStore:
    """管理运行中的 pipeline 会话"""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        sid = str(uuid.uuid4())[:8]
        with self._lock:
            self._sessions[sid] = {
                "status": "created",   # created | running | done | error
                "logs": [],            # 实时日志行
                "result": None,        # 最终结果 JSON
                "error": "",
                "created_at": time.time(),
            }
        return sid

    def get(self, sid: str) -> dict | None:
        return self._sessions.get(sid)

    def append_log(self, sid: str, line: str) -> None:
        s = self._sessions.get(sid)
        if s:
            s["logs"].append(line)

    def set_status(self, sid: str, status: str) -> None:
        s = self._sessions.get(sid)
        if s:
            s["status"] = status

    def set_result(self, sid: str, result: Any) -> None:
        s = self._sessions.get(sid)
        if s:
            s["result"] = result

    def set_error(self, sid: str, error: str) -> None:
        s = self._sessions.get(sid)
        if s:
            s["error"] = error
            s["status"] = "error"


sessions = SessionStore()
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
    """捕获 print 输出并推送到 session logs"""

    def __init__(self, session_id: str, original_stdout) -> None:
        super().__init__()
        self.session_id = session_id
        self.original = original_stdout

    def write(self, s: str) -> int:
        if s.strip():
            sessions.append_log(self.session_id, s.rstrip())
        try:
            self.original.write(s)
        except (UnicodeEncodeError, OSError):
            # Windows 控制台编码问题，忽略
            pass
        return len(s)

    def flush(self) -> None:
        self.original.flush()


# ── Pipeline 运行线程 ────────────────────────────────────────

def _run_topic_pipeline(sid: str, topic: str, discuss_only: bool) -> None:
    """在后台线程中运行主题管线"""
    capture = LogCapture(sid, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        sessions.set_status(sid, "running")
        config = _build_config()
        orchestrator = DiscussionOrchestrator(config)
        result = orchestrator.run(topic)

        # 保存讨论结果
        from main import save_discussion_result, save_prompts_json
        save_discussion_result(result, config.video.output_dir)
        json_path = save_prompts_json(result, config.video.output_dir)

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
            # 视频生成
            from video.generator import VideoGenerator
            session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
            generator = VideoGenerator(config.video)
            clips = generator.generate_all(result.final_prompts, session_name)
            result_data["clips"] = [
                {"index": c.index, "file_path": c.file_path, "status": c.status, "error": c.error}
                for c in clips
            ]

        sessions.set_result(sid, result_data)
        sessions.set_status(sid, "done")

    except Exception as e:
        sessions.set_error(sid, str(e))
    finally:
        sys.stdout = old_stdout


def _run_novel_pipeline(sid: str, novel_text: str, discuss_only: bool) -> None:
    """在后台线程中运行小说改编管线"""
    capture = LogCapture(sid, sys.stdout)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        sessions.set_status(sid, "running")
        config = _build_config()
        orchestrator = NovelDiscussionOrchestrator(config)
        result = orchestrator.run(novel_text)

        from main import save_novel_result, save_novel_prompts_json
        save_novel_result(result, config.video.output_dir)
        json_path = save_novel_prompts_json(result, config.video.output_dir)

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
        sessions.set_result(sid, result_data)
        sessions.set_status(sid, "done")

    except Exception as e:
        sessions.set_error(sid, str(e))
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
            session = sessions.get(sid)
            if not session:
                self._json_response({"error": "Session not found"}, 404)
                return
            self._json_response({
                "status": session["status"],
                "log_count": len(session["logs"]),
                "error": session["error"],
                "result": session["result"],
            })

        elif path.startswith("/api/session-logs/"):
            sid = path.split("/")[-1]
            session = sessions.get(sid)
            if not session:
                self._json_response({"error": "Session not found"}, 404)
                return
            after = int(params.get("after", [0])[0])
            logs = session["logs"][after:]
            self._json_response({
                "logs": logs,
                "total": len(session["logs"]),
                "status": session["status"],
            })

        elif path == "/api/health":
            self._json_response({"status": "ok", "time": datetime.now().isoformat()})

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
            sid = sessions.create()
            t = threading.Thread(
                target=_run_topic_pipeline,
                args=(sid, topic, discuss_only),
                daemon=True,
            )
            t.start()
            self._json_response({"session_id": sid})

        elif path == "/api/novel/start":
            body = self._read_body()
            novel_text = body.get("novel_text", "")
            discuss_only = body.get("discuss_only", False)
            if not novel_text:
                self._json_response({"error": "novel_text is required"}, 400)
                return
            sid = sessions.create()
            t = threading.Thread(
                target=_run_novel_pipeline,
                args=(sid, novel_text, discuss_only),
                daemon=True,
            )
            t.start()
            self._json_response({"session_id": sid})

        elif path == "/api/config":
            body = self._read_body()
            _current_config.update(body)
            self._json_response({"status": "ok"})

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
