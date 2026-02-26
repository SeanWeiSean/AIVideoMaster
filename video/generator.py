"""
VideoGenerator - ComfyUI 视频生成客户端
通过 ComfyUI API 提交 Wan2.2 工作流，轮询任务状态，下载生成的视频。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import request, error, parse

from config import VideoConfig
from agents.discussion import VideoSegmentPrompt


# ── 工作流配置 ────────────────────────────────────────────────
_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

# 每种模式的工作流文件和节点映射
# file 路径相对于 _WORKFLOWS_DIR，按 模型名/文件名 组织
_WORKFLOW_PROFILES: dict[str, dict] = {
    "fast": {
        # Wan2.2 14B + LightX2V Lora 4步（~60s）
        "file": "wan2.2/wan22_lora4.json",
        "positive_prompt_nodes": ("9",),
        "negative_prompt_nodes": ("13",),
        "latent_nodes": ("14",),
        "seed_nodes": ("10",),
        "output_nodes": ("16",),
    },
    "quality": {
        # Wan2.2 14B 标准 20步（~10min）
        "file": "wan2.2/wan22_full.json",
        "positive_prompt_nodes": ("11",),
        "negative_prompt_nodes": ("12",),
        "latent_nodes": ("4",),
        "seed_nodes": ("6",),
        "output_nodes": ("14",),
    },
    "cocktail_lora": {
        # Wan2.2 14B 鸡尾酒 LoRA 工作流（10步）
        "file": "wan2.2/wan22_cocktail_lora.json",
        "positive_prompt_nodes": ("9",),
        "negative_prompt_nodes": ("13",),
        "latent_nodes": ("14",),
        "seed_nodes": ("10", "17"),
        "output_nodes": ("16",),
    },
}


@dataclass
class GeneratedClip:
    """已生成的视频片段"""
    index: int
    prompt: str
    file_path: str
    status: str  # "success" | "failed" | "pending"
    error: str = ""


class ComfyUIClient:
    """ComfyUI HTTP API 封装"""

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def submit_workflow(self, workflow: dict) -> str:
        """提交工作流，返回 prompt_id"""
        payload = {
            "prompt": workflow,
            "client_id": str(uuid.uuid4()),
        }
        result = self._request("/prompt", method="POST", payload=payload)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id: {json.dumps(result, ensure_ascii=False)}")
        return prompt_id

    def get_queue(self) -> dict:
        return self._request("/queue")

    def get_history(self, prompt_id: str) -> dict:
        return self._request(f"/history/{prompt_id}")

    def download_output(self, filename: str, subfolder: str = "", output_type: str = "output") -> bytes:
        """从 ComfyUI 下载输出文件"""
        params = parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": output_type,
        })
        url = f"{self.base_url}/view?{params}"
        req = request.Request(url)
        with request.urlopen(req, timeout=120) as resp:
            return resp.read()

    def is_alive(self) -> bool:
        try:
            self._request("/queue")
            return True
        except Exception:
            return False


class VideoGenerator:
    """通过 ComfyUI + Wan2.2 工作流生成视频片段"""

    def __init__(self, config: VideoConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = ComfyUIClient(config.comfyui_url)
        self._profile = self._resolve_profile()
        self._base_workflow = self._load_workflow()

    def _resolve_profile(self) -> dict:
        """根据 quality_mode 选择工作流配置"""
        mode = self.config.quality_mode.lower()
        if mode not in _WORKFLOW_PROFILES:
            print(f"[WARN] 未知 quality_mode '{mode}'，回退到 fast")
            mode = "fast"
        profile = _WORKFLOW_PROFILES[mode]
        labels = {
            "fast": "快速模式 (Lora 4步)",
            "quality": "高质量模式 (标准 20步)",
            "cocktail_lora": "鸡尾酒LoRA模式 (10步)",
        }
        label = labels.get(mode, mode)
        print(f"[INFO] {label}")
        return profile

    def _load_workflow(self) -> dict:
        """加载工作流（优先用户指定 → 否则按 profile 选择内置文件）"""
        path = self.config.workflow_path or ""
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                print(f"[INFO] 使用自定义工作流: {path}")
                return json.load(f)
        default_path = _WORKFLOWS_DIR / self._profile["file"]
        if default_path.is_file():
            with open(default_path, "r", encoding="utf-8") as f:
                print(f"[INFO] 使用内置工作流: {default_path.name}")
                return json.load(f)
        raise FileNotFoundError(
            f"找不到工作流文件 {default_path}。请指定 --workflow 或将 JSON 放到 workflows/ 目录"
        )

    def _build_workflow(self, prompt: VideoSegmentPrompt, seed: int | None = None) -> dict:
        """基于模板构建单个片段的工作流，动态注入 prompt、分辨率、种子等"""
        wf = json.loads(json.dumps(self._base_workflow))  # deep copy
        p = self._profile

        actual_seed = seed if seed is not None else int(time.time() * 1000 + prompt.index) % (2**53)

        # 注入正向提示词
        for nid in p["positive_prompt_nodes"]:
            if nid in wf and "text" in wf[nid].get("inputs", {}):
                wf[nid]["inputs"]["text"] = prompt.video_prompt

        # 注入反向提示词
        for nid in p["negative_prompt_nodes"]:
            if nid in wf and "text" in wf[nid].get("inputs", {}):
                wf[nid]["inputs"]["text"] = self.config.negative_prompt

        # 注入分辨率 & 帧数
        for nid in p["latent_nodes"]:
            if nid in wf:
                inputs = wf[nid]["inputs"]
                inputs["width"] = self.config.width
                inputs["height"] = self.config.height
                inputs["length"] = self.config.length

        # 注入种子
        for nid in p["seed_nodes"]:
            if nid in wf and "noise_seed" in wf[nid].get("inputs", {}):
                wf[nid]["inputs"]["noise_seed"] = actual_seed

        # 注入输出文件名前缀
        for nid in p["output_nodes"]:
            if nid in wf:
                wf[nid]["inputs"]["filename_prefix"] = f"video/clip{prompt.index:03d}"

        return wf

    def check_connection(self) -> bool:
        if self.client.is_alive():
            print(f"[OK] ComfyUI 连接正常: {self.config.comfyui_url}")
            return True
        print(f"[ERROR] 无法连接 ComfyUI: {self.config.comfyui_url}")
        return False

    def generate_all(
        self,
        prompts: list[VideoSegmentPrompt],
        session_name: str = "default",
    ) -> list[GeneratedClip]:
        """依次生成所有视频片段"""
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)

        if not self.check_connection():
            return [
                GeneratedClip(
                    index=p.index, prompt=p.video_prompt,
                    file_path="", status="failed",
                    error=f"无法连接 ComfyUI ({self.config.comfyui_url})",
                )
                for p in prompts
            ]

        clips: list[GeneratedClip] = []
        total = len(prompts)

        for i, prompt_seg in enumerate(prompts, 1):
            print(f"\n{'─'*50}")
            print(f"[INFO] 生成片段 {i}/{total}：{prompt_seg.time_range}")
            print(f"   Prompt: {prompt_seg.video_prompt[:100]}...")
            print(f"{'─'*50}")

            clip = self._generate_single(prompt_seg, session_dir)
            clips.append(clip)

            if clip.status == "success":
                print(f"   [OK] 生成完成: {clip.file_path}")
            else:
                print(f"   [ERROR] 生成失败: {clip.error}")

        return clips

    def _generate_single(
        self,
        prompt: VideoSegmentPrompt,
        session_dir: Path,
        seed: int | None = None,
    ) -> GeneratedClip:
        """提交单个工作流到 ComfyUI 并等待完成"""
        output_path = str(session_dir / f"clip_{prompt.index:03d}.mp4")

        try:
            workflow = self._build_workflow(prompt, seed=seed)
            prompt_id = self.client.submit_workflow(workflow)
            print(f"   [INFO] 已提交 prompt_id={prompt_id}")

            task_data = self._wait_for_completion(prompt_id)
            self._download_output(task_data, output_path)

            return GeneratedClip(
                index=prompt.index,
                prompt=prompt.video_prompt,
                file_path=output_path,
                status="success",
            )
        except Exception as e:
            return GeneratedClip(
                index=prompt.index,
                prompt=prompt.video_prompt,
                file_path=output_path,
                status="failed",
                error=str(e),
            )

    def _wait_for_completion(self, prompt_id: str) -> dict:
        """轮询 ComfyUI 直到任务完成"""
        start = time.time()
        timeout = self.config.generation_timeout
        interval = self.config.poll_interval

        while True:
            elapsed = int(time.time() - start)
            try:
                queue = self.client.get_queue()
                history = self.client.get_history(prompt_id)

                running = queue.get("queue_running", [])
                pending = queue.get("queue_pending", [])
                in_running = any((len(item) > 1 and item[1] == prompt_id) for item in running)
                in_pending = any((len(item) > 1 and item[1] == prompt_id) for item in pending)
                state = "running" if in_running else ("pending" if in_pending else "—")

                print(f"   [{elapsed}s] 状态={state}  运行中={len(running)}  排队={len(pending)}")

                if prompt_id in history:
                    task_data = history[prompt_id]
                    status_info = task_data.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        raise RuntimeError(f"ComfyUI 工作流出错: {msgs}")
                    print(f"   [OK] 任务完成（耗时 {elapsed}s）")
                    return task_data

            except error.URLError:
                print(f"   [WARN] [{elapsed}s] ComfyUI 暂时无响应，继续等待...")

            if timeout > 0 and (time.time() - start) >= timeout:
                raise TimeoutError(f"视频生成超时（{timeout}s），prompt_id={prompt_id}")

            time.sleep(interval)

    def _download_output(self, task_data: dict, output_path: str) -> None:
        """从 ComfyUI history 提取输出视频并下载到本地
        
        双管线工作流会产出两个视频（快速版 + 高质量版），
        优先下载标准管线(节点98)的高质量输出，快速版作为备用存到同目录。
        """
        outputs = task_data.get("outputs", {})

        # 收集所有视频文件，按节点 ID 分组
        video_files: list[tuple[str, dict]] = []  # (node_id, file_info)
        for node_id, node_output in outputs.items():
            for key in ("videos", "gifs", "images"):
                for item in node_output.get(key, []):
                    fname = item.get("filename", "")
                    if fname.endswith((".mp4", ".webm", ".gif")):
                        video_files.append((node_id, item))

        if not video_files:
            raise RuntimeError(
                f"ComfyUI 输出中未找到视频文件。输出: {json.dumps(outputs, ensure_ascii=False)[:500]}"
            )

        # 优先拿标准管线 (节点 98) 的输出，否则取第一个
        primary = None
        secondary = None
        for nid, finfo in video_files:
            if nid == "98":
                primary = finfo
            elif nid == "80":
                secondary = finfo
            elif primary is None:
                primary = finfo

        if primary is None:
            primary = video_files[0][1]

        # 下载主输出
        self._download_file(primary, output_path)

        # 下载副输出（快速版），如果存在
        if secondary and secondary != primary:
            base, ext = os.path.splitext(output_path)
            fast_path = f"{base}_fast{ext}"
            try:
                self._download_file(secondary, fast_path)
            except Exception as e:
                print(f"   [WARN] 快速版下载失败（不影响主输出）: {e}")

    def _download_file(self, file_info: dict, output_path: str) -> None:
        """下载单个文件"""
        filename = file_info["filename"]
        subfolder = file_info.get("subfolder", "")
        file_type = file_info.get("type", "output")

        print(f"   [INFO] 下载: {filename}")
        data = self.client.download_output(filename, subfolder, file_type)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)
        print(f"   [OK] 已保存: {output_path} ({len(data) / 1024:.1f} KB)")
