"""
ComfyUI 图片生成客户端 (Qwen Image Create V2 / Image Edit)

通过 ComfyUI API 提交 Qwen Image 工作流：
- 图片创建 (Image Create): 纯文生图，基于 QwenImage V2 T2I 工作流
- 图片编辑 (Image Edit): 原图 + 编辑指令 → 修改后的图片

Create 模式关键节点映射（qwen_image_create.json / Qwen T2I V2）：
  "76:6"    — 正向 prompt (CLIPTextEncode, inputs.text)
  "76:7"    — 反向 prompt (CLIPTextEncode, inputs.text)
  "76:3"    — KSampler（seed, steps, denoise）
  "76:58"   — EmptySD3LatentImage（width, height）
  "60"      — SaveImage（输出）

Edit 模式关键节点映射（qwen_image_edit.json）：
  "78"      — LoadImage（输入图片文件名）
  "102:76"  — 正向 prompt (TextEncodeQwenImageEdit, inputs.prompt)
  "102:77"  — 反向 prompt (TextEncodeQwenImageEdit, inputs.prompt)
  "102:3"   — KSampler（seed, steps, denoise）
  "60"      — SaveImage（输出）
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

from video.generator import ComfyUIClient


_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

# ── 预设工作流配置 ────────────────────────────────────────────

IMAGE_WORKFLOW_PROFILES: dict[str, dict] = {
    # V2 — 纯文生图（QwenImage T2I V2，无需输入图片）
    "create": {
        "file": "qwen_image_create.json",
        "positive_prompt_node": "76:6",     # CLIPTextEncode — 正向 (inputs.text)
        "negative_prompt_node": "76:7",     # CLIPTextEncode — 反向 (inputs.text)
        "prompt_field": "text",             # CLIPTextEncode 使用 text 字段
        "sampler_node": "76:3",             # KSampler — seed / steps / denoise
        "latent_image_node": "76:58",       # EmptySD3LatentImage — 尺寸
        "output_node": "60",                # SaveImage — 输出
    },
    # V1 — 参考图+创意 prompt → 新图（QwenImage Edit LoRA，需要输入图片）
    "create-v1": {
        "file": "qwen_image_createV1.json",
        "positive_prompt_node": "102:76",   # TextEncodeQwenImageEdit — 正向 (inputs.prompt)
        "negative_prompt_node": "102:77",   # TextEncodeQwenImageEdit — 反向 (inputs.prompt)
        "prompt_field": "prompt",
        "load_image_node": "78",            # LoadImage — 输入参考图
        "sampler_node": "102:3",            # KSampler — seed / steps / denoise
        "output_node": "60",                # SaveImage — 输出
    },
    "edit": {
        "file": "qwen_image_edit.json",
        "positive_prompt_node": "102:76",
        "negative_prompt_node": "102:77",
        "load_image_node": "78",
        "sampler_node": "102:3",
        "output_node": "60",
    },
}


@dataclass
class ImageJob:
    """图片生成任务结果"""
    job_id: str
    mode: str           # "create" | "edit"
    prompt: str
    status: str         # "pending" | "running" | "success" | "failed"
    file_path: str = ""
    error: str = ""
    comfyui_prompt_id: str = ""


class ComfyUIImageClient:
    """
    ComfyUI 图片生成客户端（Qwen Image Edit 工作流）。

    两个模式的核心流程一致：
    1. 将用户上传的图片（base64）上传到 ComfyUI input 目录
    2. 加载工作流 JSON，注入：图片文件名、prompt、seed
    3. 提交工作流，轮询等待完成
    4. 下载生成的图片
    """

    def __init__(self, comfyui_url: str, output_dir: str = "./output") -> None:
        self.client = ComfyUIClient(comfyui_url)
        self.comfyui_url = comfyui_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._workflow_cache: dict[str, dict] = {}

    def check_connection(self) -> bool:
        return self.client.is_alive()

    # ── 工作流加载 ────────────────────────────────────────────

    def _load_workflow(self, workflow_file: str) -> dict:
        """加载工作流 JSON"""
        if workflow_file in self._workflow_cache:
            return self._workflow_cache[workflow_file]

        p = Path(workflow_file)
        if not p.is_file():
            p = _WORKFLOWS_DIR / workflow_file
        if not p.is_file():
            raise FileNotFoundError(f"工作流文件不存在: {workflow_file}")

        with open(p, "r", encoding="utf-8") as f:
            wf = json.load(f)
        self._workflow_cache[workflow_file] = wf
        return wf

    # ── 工作流注入 ────────────────────────────────────────────

    def _build_workflow(
        self,
        profile: dict,
        *,
        image_filename: str,
        positive_prompt: str,
        negative_prompt: str = "",
        seed: int | None = None,
        steps: int | None = None,
        denoise: float | None = None,
    ) -> dict:
        """
        加载并注入参数到工作流。

        Args:
            profile: 工作流配置字典
            image_filename: 已上传到 ComfyUI 的图片文件名
            positive_prompt: 正向 prompt
            negative_prompt: 反向 prompt
            seed: 随机种子（None 自动生成）
            steps: 采样步数（None 使用工作流默认值 4）
            denoise: 去噪强度（None 使用工作流默认值 1.0）
        """
        base_wf = self._load_workflow(profile["file"])
        wf = json.loads(json.dumps(base_wf))  # deep copy

        actual_seed = seed if seed is not None else int(time.time() * 1000) % (2**53)

        # 注入输入图片文件名到 LoadImage 节点（仅图片编辑模式）
        load_node = profile.get("load_image_node")
        if load_node and load_node in wf:
            wf[load_node]["inputs"]["image"] = image_filename

        # 注入正向 prompt（字段名由 profile 决定：text 或 prompt）
        pos_node = profile.get("positive_prompt_node", "102:76")
        prompt_field = profile.get("prompt_field", "prompt")
        if pos_node in wf:
            wf[pos_node]["inputs"][prompt_field] = positive_prompt

        # 注入反向 prompt
        neg_node = profile.get("negative_prompt_node", "102:77")
        if neg_node in wf:
            wf[neg_node]["inputs"][prompt_field] = negative_prompt

        # 注入 KSampler 参数
        sampler_node = profile.get("sampler_node", "102:3")
        if sampler_node in wf:
            inputs = wf[sampler_node]["inputs"]
            inputs["seed"] = actual_seed
            if steps is not None:
                inputs["steps"] = steps
            if denoise is not None:
                inputs["denoise"] = denoise

        return wf

    # ── 图片上传 ──────────────────────────────────────────────

    def _upload_input_image(self, image_b64: str, filename: str) -> str:
        """
        将 base64 图片上传到 ComfyUI 的 input 目录。
        返回 ComfyUI 服务端的实际文件名。
        """
        image_data = base64.b64decode(image_b64)
        server_filename = self.client.upload_image(image_data, filename, overwrite=True)
        print(f"   [OK] 图片已上传到 ComfyUI: {server_filename} ({len(image_data) / 1024:.1f} KB)")
        return server_filename

    # ── 图片创建 (Image Create) ──────────────────────────────

    def image_create(
        self,
        positive_prompt: str,
        input_image_b64: str = "",
        negative_prompt: str = "",
        seed: int | None = None,
        steps: int | None = None,
        denoise: float | None = None,
        output_name: str = "",
        workflow_version: str = "v2",
    ) -> ImageJob:
        """
        图片创建。

        Args:
            positive_prompt: 创作描述
            input_image_b64: 参考图 base64（V1 必填，V2 忽略）
            negative_prompt: 反向 prompt
            seed: 随机种子
            steps: 采样步数
            denoise: 去噪强度
            output_name: 输出文件名
            workflow_version: "v2"（纯文生图，默认）| "v1"（参考图+创意 prompt）
        """
        mode = "create-v1" if workflow_version == "v1" else "create"
        return self._run(
            mode=mode,
            positive_prompt=positive_prompt,
            input_image_b64=input_image_b64,
            negative_prompt=negative_prompt,
            seed=seed, steps=steps, denoise=denoise,
            output_name=output_name,
        )

    # ── 图片编辑 (Image Edit) ────────────────────────────────

    def image_edit(
        self,
        positive_prompt: str,
        input_image_b64: str,
        negative_prompt: str = "",
        seed: int | None = None,
        steps: int | None = None,
        denoise: float | None = None,
        output_name: str = "",
    ) -> ImageJob:
        """
        图片编辑：原图 + 编辑指令 → 修改后的图片。

        Args:
            positive_prompt: 编辑指令（如 "Remove the text, keep the background"）
            input_image_b64: 待编辑图片 base64
            negative_prompt: 反向 prompt
            seed: 随机种子
            steps: 采样步数
            denoise: 去噪强度
            output_name: 输出文件名
        """
        return self._run(
            mode="edit",
            positive_prompt=positive_prompt,
            input_image_b64=input_image_b64,
            negative_prompt=negative_prompt,
            seed=seed, steps=steps, denoise=denoise,
            output_name=output_name,
        )

    # ── 核心执行流程 ──────────────────────────────────────────

    def _run(
        self,
        mode: str,
        positive_prompt: str,
        input_image_b64: str,
        negative_prompt: str = "",
        seed: int | None = None,
        steps: int | None = None,
        denoise: float | None = None,
        output_name: str = "",
    ) -> ImageJob:
        """统一的执行流程"""
        profile = IMAGE_WORKFLOW_PROFILES.get(mode)
        if not profile:
            return ImageJob(
                job_id="", mode=mode, prompt=positive_prompt,
                status="failed", error=f"未知模式: {mode}",
            )

        load_image_node = profile.get("load_image_node")
        if not input_image_b64 and load_image_node:
            return ImageJob(
                job_id="", mode=mode, prompt=positive_prompt,
                status="failed", error="需要上传输入图片",
            )

        try:
            # 1. 上传图片到 ComfyUI（仅当工作流有 LoadImage 节点时）
            ts = int(time.time())
            server_filename = ""
            if load_image_node and input_image_b64:
                upload_filename = f"avm_{mode}_{ts}.png"
                server_filename = self._upload_input_image(input_image_b64, upload_filename)

            # 2. 构建工作流
            wf = self._build_workflow(
                profile,
                image_filename=server_filename,
                positive_prompt=positive_prompt,
                negative_prompt=negative_prompt,
                seed=seed, steps=steps, denoise=denoise,
            )

            # 3. 提交并轮询
            prompt_id = self.client.submit_workflow(wf)
            mode_label = "图片创建" if mode == "create" else "图片编辑"
            print(f"[INFO] {mode_label} 已提交 prompt_id={prompt_id}")

            task_data = self._wait_for_completion(prompt_id)

            # 4. 下载结果
            output_path = self._save_image_output(
                task_data,
                output_name or f"{mode}_{ts}.png",
                output_node=profile.get("output_node", "60"),
            )

            return ImageJob(
                job_id=prompt_id, mode=mode, prompt=positive_prompt,
                status="success", file_path=output_path,
                comfyui_prompt_id=prompt_id,
            )

        except Exception as e:
            return ImageJob(
                job_id="", mode=mode, prompt=positive_prompt,
                status="failed", error=str(e),
            )

    # ── 轮询 & 下载 ──────────────────────────────────────────

    def _wait_for_completion(self, prompt_id: str, timeout: int = 600, poll_interval: int = 3) -> dict:
        """轮询 ComfyUI 直到任务完成"""
        start = time.time()
        while True:
            elapsed = int(time.time() - start)
            try:
                history = self.client.get_history(prompt_id)
                if prompt_id in history:
                    task_data = history[prompt_id]
                    status_info = task_data.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        raise RuntimeError(f"ComfyUI 工作流出错: {msgs}")
                    print(f"   [OK] 图片生成完成（耗时 {elapsed}s）")
                    return task_data

                queue = self.client.get_queue()
                running = len(queue.get("queue_running", []))
                pending = len(queue.get("queue_pending", []))
                print(f"   [{elapsed}s] 等待中... 运行中={running} 排队={pending}")

            except Exception as e:
                if "URLError" in type(e).__name__:
                    print(f"   [WARN] [{elapsed}s] ComfyUI 暂时无响应...")
                elif timeout > 0 and elapsed >= timeout:
                    raise

            if timeout > 0 and (time.time() - start) >= timeout:
                raise TimeoutError(f"图片生成超时（{timeout}s），prompt_id={prompt_id}")

            time.sleep(poll_interval)

    def _save_image_output(self, task_data: dict, output_name: str, output_node: str = "60") -> str:
        """从 ComfyUI 输出中下载生成的图片"""
        outputs = task_data.get("outputs", {})

        # 收集所有图片文件
        image_files: list[tuple[str, dict]] = []
        for node_id, node_output in outputs.items():
            for item in node_output.get("images", []):
                fname = item.get("filename", "")
                if fname.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    image_files.append((node_id, item))

        if not image_files:
            raise RuntimeError(
                f"ComfyUI 输出中未找到图片。outputs: {json.dumps(outputs, ensure_ascii=False)[:500]}"
            )

        # 优先拿指定输出节点的图片
        target = None
        for nid, finfo in image_files:
            if nid == output_node:
                target = finfo
                break
        if target is None:
            target = image_files[0][1]

        # 下载
        filename = target["filename"]
        subfolder = target.get("subfolder", "")
        file_type = target.get("type", "output")
        data = self.client.download_output(filename, subfolder, file_type)

        # 保存
        images_dir = self.output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(images_dir / output_name)
        with open(output_path, "wb") as f:
            f.write(data)
        print(f"   [OK] 图片已保存: {output_path} ({len(data) / 1024:.1f} KB)")
        return output_path
