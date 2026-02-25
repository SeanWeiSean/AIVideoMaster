# AI Video Master（Video Pipeline）

多 Agent 协作的视频生成项目，支持两条主流程：

- **主题创作模式（T2V）**：输入一个主题，自动讨论并生成视频片段
- **小说改编模式（I2V）**：输入小说文字，按场景拆分并产出参考图/视频动作 Prompt

项目同时提供：

- **CLI 模式**（`main.py`）
- **桌面 UI 模式**（Electron + Python API Server）

---

## 1. 当前能力概览

### 1.1 主题创作（T2V）

流程：文案师 → 镜头师 → 裁判（最多 3 轮）→ 裁判产出最终 Enriched Prompts → ComfyUI 生成视频 → 审核 → ffmpeg 合成。

### 1.2 小说改编（I2V）

流程：场景分析师 → 小说镜头师 → 裁判（最多 3 轮）→ 裁判产出最终 Prompt 集合：

- `image_prompt`（参考图生成）
- `video_prompt`（I2V 动作描述）
- `negative_prompt`
- `narration`（旁白保留接口）

> 当前已接入参考图 API 抽象层（`video/image_generator.py`），你可以按自己的 Qwen-Image 接口格式改造。I2V 自动化步骤留了接口位，便于你后续接入自己的 ComfyUI I2V 工作流。

### 1.3 优秀模板存储

支持将效果好的 Prompt 存为模板（`templates.py` + `templates.json`），可在 UI 里管理。

---

## 2. 目录结构（与当前代码一致）

```text
videopipeline/
├─ main.py                         # CLI 主入口（topic + novel）
├─ server.py                       # Python HTTP API（给 Electron UI 用）
├─ config.py                       # 配置 dataclass
├─ templates.py                    # 模板存储逻辑
├─ templates.json                  # 模板数据
├─ requirements.txt                # Python 依赖
│
├─ agents/
│  ├─ base.py
│  ├─ copywriter.py
│  ├─ cinematographer.py
│  ├─ judge.py
│  ├─ discussion.py                # 主题模式 orchestrator
│  ├─ scene_analyzer.py            # 小说模式：场景分析师
│  ├─ novel_cinematographer.py     # 小说模式：镜头师
│  └─ novel_discussion.py          # 小说模式 orchestrator + NovelJudge
│
├─ video/
│  ├─ generator.py                 # ComfyUI 视频生成（T2V）
│  ├─ composer.py                  # ffmpeg 合成
│  └─ image_generator.py           # 参考图生成抽象（Qwen-Image/ComfyUI）
│
├─ workflows/
│  └─ wan2.2/
│     ├─ wan22_full.json
│     ├─ wan22_lora4.json
│     ├─ wan22_cocktail_lora.json
│     └─ wan22_14B_t2v.json
│
├─ ui/
│  ├─ package.json
│  ├─ main.js                      # Electron 主进程（自动启动 server.py）
│  ├─ preload.js
│  └─ renderer/
│     ├─ index.html
│     ├─ app.js
│     └─ styles.css
│
└─ output/                         # 讨论记录、prompts JSON、视频片段、最终视频
```

---

## 3. 工作流模式清单

`VideoConfig.quality_mode` 当前支持：

- `fast`：Wan2.2 Lora4 快速模式
- `quality`：Wan2.2 标准高质量模式
- `cocktail_lora`：鸡尾酒 LoRA 工作流（`wan22_cocktail_lora.json`）

CLI 对应参数：

```bash
python main.py --quality fast
python main.py --quality quality
python main.py --quality cocktail_lora
```

---

## 4. 配置说明

### 4.1 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | LLM Key | `no-key` |
| `LLM_BASE_URL` | LLM Base URL | `http://localhost:23333/api/openai/v1` |
| `LLM_MODEL` | LLM 模型名 | `claude-opus-4.6` |
| `COMFYUI_URL` | ComfyUI 地址 | `http://localhost:8188` |
| `COMFYUI_WORKFLOW` | 自定义工作流路径 | 空 |
| `VIDEO_QUALITY` | 工作流模式 | `fast` |
| `VIDEO_OUTPUT_DIR` | 输出目录 | `./output` |
| `IMAGE_GEN_URL` | 参考图 API URL | 空 |
| `IMAGE_GEN_KEY` | 参考图 API Key | 空 |

### 4.2 关键 dataclass

- `LLMConfig`
- `VideoConfig`
- `ImageGenConfig`
- `PipelineConfig`

---

## 5. 安装

### 5.1 Python 依赖

```bash
pip install -r requirements.txt
```

### 5.2 Electron UI 依赖

```bash
cd ui
npm install
```

### 5.3 外部前置

- 已安装并可访问的 ComfyUI
- 已配置 Wan2.2 模型及对应 LoRA
- 系统可用 `ffmpeg`（PATH 中）

---

## 6. 使用方式

### 6.1 CLI：主题创作（T2V）

```bash
python main.py --mode topic --topic "4个星座的末日庇护所" --quality cocktail_lora
```

仅讨论：

```bash
python main.py --mode topic --topic "末日避难所" --discuss-only
```

### 6.2 CLI：小说改编（I2V Prompt 流程）

直接传文本：

```bash
python main.py --mode novel --novel "你的小说段落..." --discuss-only
```

从文件读取：

```bash
python main.py --mode novel --novel-file story.txt --discuss-only
```

带参考图 API：

```bash
python main.py --mode novel --novel-file story.txt --image-api http://your-image-api
```

---

## 7. 启动桌面 UI（Electron）

```bash
cd ui
npm start
```

UI 启动时会自动拉起 `server.py`。

### 若遇到 Windows 缓存目录权限问题

使用独立 user-data-dir：

```bash
cd ui
npx electron . --user-data-dir="D:\videopipeline\ui\.electron-data"
```

---

## 8. Python API（server.py）

默认地址：`http://127.0.0.1:5678`

常用接口：

- `GET /api/health`
- `GET /api/config`
- `POST /api/config`
- `POST /api/topic/start`
- `POST /api/novel/start`
- `GET /api/session/{id}`
- `GET /api/session-logs/{id}?after=...`
- `GET /api/templates`
- `POST /api/templates`
- `DELETE /api/templates/{name}`

---

## 9. 输出文件

主题模式：

- `output/discussion_*.md`
- `output/prompts_*.json`
- `output/{session}/clip_*.mp4`
- `output/final_*.mp4`

小说模式：

- `output/novel_discussion_*.md`
- `output/novel_prompts_*.json`
- `output/{session}/ref_images/ref_*.png`（接入参考图 API 后）

---

## 10. 二次开发指南

### 10.1 新增工作流模式

1. 将工作流 JSON 放到 `workflows/wan2.2/`
2. 在 `video/generator.py` 的 `_WORKFLOW_PROFILES` 添加映射：
   - `file`
   - `positive_prompt_nodes`
   - `negative_prompt_nodes`
   - `latent_nodes`
   - `seed_nodes`
   - `output_nodes`
3. 在 `main.py` 的 `--quality` 选项、UI 下拉中补充该模式

### 10.2 接入你的 Qwen-Image API

修改 `video/image_generator.py` 的 `QwenImageGenerator.generate()`：

- 请求 URL
- 请求体字段
- 响应解析（二进制 / base64 / image_url）

### 10.3 接入 I2V 自动生成

在 `main.py` 的 `run_novel_pipeline()` 中，Phase 4 已预留接入位置。

---

## 11. 已知说明

- Electron 控制台可能出现 Chromium 缓存警告，不一定影响 UI 功能。
- `icon.png` 缺失只会触发警告，不影响主流程。
- 小说模式目前侧重 Prompt 流程和接口预留，I2V 自动化依赖你提供的工作流接口格式。
