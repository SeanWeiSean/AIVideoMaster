# AI Video Master

多 Agent 协作的 AI 视频生成管线，基于 ComfyUI 后端，支持从文本主题或小说文本自动生成视频。核心亮点是**多智能体讨论机制**——文案师、镜头师、裁判最多进行 3 轮迭代，确保生成 Prompt 的视觉一致性与质量，再交由 ComfyUI 执行视频生成。

## 主要特性

- **主题创作（T2V）**：输入主题 → 多 Agent 讨论 → ComfyUI 文生视频 → ffmpeg 合成
- **小说改编（I2V）**：输入小说文本 → 场景拆分 → 生成参考图 + 视频动作 Prompt → 图生视频
- **Prompt 优化器**：独立的 Prompt 优化工具，支持 T2V / I2V / LTX-I2V 三种模式
- **AI 图片工具**：图片构思 → 视觉蓝图 → Qwen 图片生成/编辑
- **模板系统**：保存、搜索、复用优秀 Prompt 模板
- **多模型支持**：Wan2.2（T2V/I2V）、LTX-2.0（I2V）、6 关键帧 I2V、Qwen 图片生成
- **双入口**：CLI（`main.py`）+ 桌面 UI（Electron + Python HTTP Server）

---

## 架构总览

```
用户输入（主题 / 小说文本）
        ↓
┌─────────────────────────────────────┐
│  Phase 1：多 Agent 讨论（最多 3 轮）  │
│  ┌─────────┐ ┌──────────┐ ┌──────┐ │
│  │ 文案师 / │ │  镜头师   │ │ 裁判 │ │
│  │ 场景分析 │ │          │ │      │ │
│  └─────────┘ └──────────┘ └──────┘ │
└─────────────────────────────────────┘
        ↓ Enriched Prompts
┌─────────────────────────────────────┐
│  Phase 2：ComfyUI 视频 / 图片生成    │
│  Wan2.2 T2V · Wan2.2 I2V · LTX-2.0 │
│  6 关键帧 I2V · Qwen 图片生成        │
└─────────────────────────────────────┘
        ↓ 视频片段
┌─────────────────────────────────────┐
│  Phase 3：审核 & 合成                │
│  片段选择 → ffmpeg 拼接 → 最终视频    │
└─────────────────────────────────────┘
```

---

## 目录结构

```text
AIVideoMaster/
├─ main.py                            # CLI 主入口
├─ server.py                          # Python HTTP API Server（端口 5678）
├─ config.py                          # 配置 dataclass（LLM / Video / Image / Pipeline）
├─ templates.py                       # 模板存储管理
├─ templates.json                     # 模板数据
├─ requirements.txt                   # Python 依赖
├─ goal.md                            # 项目愿景
│
├─ agents/                            # 多智能体系统
│  ├─ base.py                         # Agent 基类（LLM 调用封装）
│  ├─ copywriter.py                   # 文案师：主题拆段 + 文案撰写
│  ├─ cinematographer.py              # 镜头师：镜头设计 + Wan2.2 Prompt 生成
│  ├─ judge.py                        # 裁判：质量评审 + Enriched Prompt 输出
│  ├─ discussion.py                   # T2V 讨论编排器
│  ├─ scene_analyzer.py               # 场景分析师：小说文本 → 场景拆分
│  ├─ novel_cinematographer.py        # 小说镜头师：双 Prompt（image + video）
│  ├─ novel_discussion.py             # I2V 讨论编排器 + NovelJudge
│  ├─ prompt_optimizer.py             # 独立 Prompt 优化 Agent
│  ├─ prompt_bestpractice.py          # Wan2.2 Prompt 最佳实践知识库
│  └─ image_creator.py               # 图片构思师 + 图片描述师
│
├─ video/                             # 视频 / 图片生成引擎
│  ├─ generator.py                    # ComfyUI T2V 生成（Wan2.2 多模式）
│  ├─ i2v_generator.py                # Wan2.2 I2V 图生视频
│  ├─ ltx_i2v_generator.py            # LTX-2.0 I2V（双阶段采样 + 空间上采样）
│  ├─ keyframe_i2v_generator.py       # 6 关键帧 I2V（分段生成 + 自动拼接）
│  ├─ comfyui_image.py                # Qwen 图片生成 / 编辑（ComfyUI 工作流）
│  ├─ image_generator.py              # 参考图生成抽象层
│  └─ composer.py                     # ffmpeg 视频合成
│
├─ workflows/                         # ComfyUI 工作流 JSON
│  ├─ wan2.2/
│  │  ├─ wan22_full.json              # T2V 标准 20 步（高质量）
│  │  ├─ wan22_lora4.json             # T2V LoRA 4 步（快速）
│  │  ├─ wan22_cocktail_lora.json     # T2V 鸡尾酒 LoRA 10 步（均衡）
│  │  ├─ wan22_14B_t2v.json           # T2V 14B 模型
│  │  ├─ wan22_14B_i2v.json           # I2V 14B 模型
│  │  └─ wan22_6keyframe_i2v.json     # 6 关键帧 I2V
│  ├─ ltx2/
│  │  └─ ltx2_i2v.json               # LTX-2.0 I2V
│  ├─ qwen_image_create.json          # Qwen 文生图 v2
│  ├─ qwen_image_createV1.json        # Qwen 文生图 v1（含参考图）
│  └─ qwen_image_edit.json            # Qwen 图片编辑
│
├─ promptbase/                        # Prompt 工程知识库
│  ├─ wan22_bestpractice.md           # Wan2.2 最佳实践
│  └─ ltx_promptbase.md              # LTX-2.0 Prompt 指南
│
├─ samplefolder/                      # 示例脚本
│  ├─ storyboard_generate.py          # 分镜板生成示例（6 帧 → 关键帧 I2V）
│  ├─ storyboard_video_only.py        # 仅视频生成测试
│  └─ run_wan22.py                    # Wan2.2 直接调用测试
│
├─ ui/                                # Electron 桌面 UI
│  ├─ main.js                         # Electron 主进程（自动启动 server.py）
│  ├─ preload.js                      # 预加载脚本
│  ├─ package.json                    # Electron v28.3.3
│  └─ renderer/
│     ├─ index.html                   # 界面布局（暗色主题、侧边栏导航）
│     ├─ app.js                       # 前端逻辑（原生 JS，SSE 日志流）
│     └─ styles.css                   # 样式
│
└─ output/                            # 输出目录
   ├─ {YYYYMMDD_HHMMSS}/             # 每次任务的独立文件夹
   │  ├─ job.json                     # 任务元数据 + 结果
   │  ├─ clip_*.mp4                   # 生成的视频片段
   │  └─ final.mp4                    # 合成后的最终视频
   └─ images/                         # 生成的图片
```

---

## 多智能体系统

### T2V 主题创作流程

| 轮次 | 文案师 (Copywriter) | 镜头师 (Cinematographer) | 裁判 (Judge) |
|------|---------------------|--------------------------|-------------|
| 第 1 轮 | 将主题拆分为 5 秒段落，撰写文案 + 场景描述 | 设计统一视觉风格、镜头语言，生成英文 Prompt | 评审文案质量 & 视觉一致性，给出反馈或 PASS |
| 第 2-3 轮 | 根据反馈修改 | 根据反馈优化 | 重新评审，直到 PASS |
| 最终输出 | — | — | 生成 Enriched Prompts（正面 + 负面） |

### I2V 小说改编流程

| 轮次 | 场景分析师 | 小说镜头师 | 裁判 |
|------|-----------|-----------|------|
| 第 1 轮 | 按场景变化拆分小说文本，提取视觉元素与旁白 | 为每段生成 `image_prompt`（参考图）+ `video_prompt`（动作描述） | 评审场景拆分 & Prompt 质量 |
| 第 2-3 轮 | 根据反馈修改 | 根据反馈优化 | 重新评审，直到 PASS |
| 最终输出 | — | — | Enriched Prompts：image_prompt + video_prompt + negative_prompt + narration |

---

## 视频生成引擎

### T2V 工作流模式

| 模式 | 工作流文件 | 步数 | 速度 | 说明 |
|------|-----------|------|------|------|
| `fast` | `wan22_lora4.json` | 4 步 | ~60s/段 | LoRA 加速，适合快速预览 |
| `quality` | `wan22_full.json` | 20 步 | ~10min/段 | 标准高质量 |
| `cocktail_lora` | `wan22_cocktail_lora.json` | 10 步 | ~3min/段 | 鸡尾酒 LoRA，质量与速度均衡 |

### I2V 生成器

| 生成器 | 模型 | 输入 | 特点 |
|--------|------|------|------|
| `I2VGenerator` | Wan2.2 | 1 张参考图 + 动作 Prompt | 基础图生视频 |
| `LtxI2VGenerator` | LTX-2.0 | 1 张参考图 + 自然语言 Prompt | 双阶段采样 + 空间上采样 + 音频生成 |
| `KeyframeI2VGenerator` | Wan2.2 | 6 张关键帧图片 | 逐帧过渡生成 5 段视频并自动拼接 |

### 图片生成

| 模式 | 工作流 | 说明 |
|------|--------|------|
| `create` | `qwen_image_create.json` | 纯文生图（v2） |
| `create-v1` | `qwen_image_createV1.json` | 带参考图的文生图 |
| `edit` | `qwen_image_edit.json` | 图片编辑 |

---

## 配置说明

### 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API Key | `no-key` |
| `LLM_BASE_URL` | LLM API 地址 | `http://localhost:23333/api/openai/v1` |
| `LLM_MODEL` | 模型名称 | `claude-opus-4.6` |
| `LLM_MIN_MAX_TOKENS` | 最大 Token 数 | `16384` |
| `COMFYUI_URL` | ComfyUI 服务地址 | `http://localhost:8188` |
| `COMFYUI_API_KEY` | ComfyUI API Key（可选） | 空 |
| `COMFYUI_WORKFLOW` | 自定义工作流路径 | 空 |
| `VIDEO_QUALITY` | T2V 工作流模式 | `fast` |
| `VIDEO_OUTPUT_DIR` | 输出目录 | `./output` |
| `IMAGE_GEN_URL` | 参考图 API URL | 空 |
| `IMAGE_GEN_KEY` | 参考图 API Key | 空 |

### 配置 Dataclass

- `LLMConfig`：LLM 连接参数（API Key、Base URL、模型、温度、Token 限制）
- `VideoConfig`：视频生成参数（ComfyUI 地址、画质模式、分辨率、帧数、超时）
- `ImageGenConfig`：参考图 API 参数
- `PipelineConfig`：管线总配置（聚合以上三者 + 讨论轮数 + 语言）

---

## 安装

### Python 依赖

```bash
pip install -r requirements.txt
```

### Electron UI 依赖

```bash
cd ui
npm install
```

### 外部前置条件

- **ComfyUI**：已安装且可访问（默认 `http://localhost:8188`）
- **视频模型**：至少安装以下之一：
  - Wan2.2 模型 + 对应 LoRA（T2V / I2V）
  - LTX-2.0 模型（I2V）
- **ffmpeg**：系统 PATH 中可用（用于视频合成）
- **LLM API**：兼容 OpenAI 格式的 LLM 服务

---

## 使用方式

### CLI：主题创作（T2V）

```bash
# 完整流程：讨论 + 生成 + 合成
python main.py --mode topic --topic "4个星座的末日庇护所" --quality cocktail_lora

# 仅讨论（不生成视频）
python main.py --mode topic --topic "末日避难所" --discuss-only
```

### CLI：小说改编（I2V）

```bash
# 直接传文本
python main.py --mode novel --novel "你的小说段落..." --discuss-only

# 从文件读取
python main.py --mode novel --novel-file story.txt --discuss-only

# 带参考图 API
python main.py --mode novel --novel-file story.txt --image-api http://your-image-api
```

### 桌面 UI（Electron）

```bash
cd ui
npm start
```

UI 启动时会自动拉起 `server.py`（端口 5678）。

Windows 缓存目录权限问题可使用：

```bash
cd ui
npx electron . --user-data-dir="D:\AIVideoMaster\ui\.electron-data"
```

UI 提供以下功能面板：

| 面板 | 功能 |
|------|------|
| 主题创作 | 输入主题，选择画质模式，实时查看 Agent 讨论日志 |
| 小说改编 | 输入小说文本，I2V 流程 |
| Prompt 优化 | 独立优化 Prompt（T2V / I2V / LTX-I2V） |
| 图片工具 | AI 图片构思 + Qwen 图片生成/编辑 |
| 视频生成 | 直接传入 Prompt 列表生成视频 |
| 模板库 | 浏览、搜索、管理 Prompt 模板 |
| 任务库 | 查看历史任务，按状态筛选 |
| 设置 | 配置 LLM / ComfyUI / 图片 API 参数 |

---

## HTTP API（server.py）

默认地址：`http://127.0.0.1:5678`

### 健康检查 & 配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（含 ComfyUI 连接状态） |
| GET | `/api/config` | 获取当前配置 |
| POST | `/api/config` | 更新配置 |

### 主题创作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/topic/start` | 启动 T2V 任务 `{topic, discuss_only}` |

### 小说改编

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/novel/start` | 启动 I2V 任务 `{novel_text, discuss_only, image_api}` |

### Prompt 优化

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/prompt/optimize` | 优化 Prompt `{text, mode}` → `{positive_prompt, negative_prompt, analysis}` |

### 图片生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/image/create` | 生成图片 `{prompt, negative_prompt, width, height, mode}` |
| GET | `/api/image/{image_id}` | 下载生成的图片 |

### 视频生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/video/generate` | T2V 批量生成 `{prompts_list, quality_mode}` |
| POST | `/api/video/i2v` | Wan2.2 I2V `{reference_image(base64), video_prompt, ...}` |
| POST | `/api/video/ltx-i2v` | LTX-2.0 I2V 生成 |
| POST | `/api/video/keyframe-i2v` | 6 关键帧 I2V 生成 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 列出所有任务（分页、筛选） |
| GET | `/api/job/{job_id}/result` | 获取任务结果 |
| GET | `/api/job/{job_id}/logs` | SSE 实时日志流 |
| POST | `/api/job/{job_id}/cancel` | 取消运行中的任务 |

### 模板管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/templates` | 列出所有模板 |
| POST | `/api/templates` | 保存新模板 |
| GET | `/api/templates/{name}` | 获取指定模板 |
| DELETE | `/api/templates/{name}` | 删除模板 |

---

## 输出结构

每次任务产出独立文件夹 `output/{YYYYMMDD_HHMMSS}/`：

```text
output/20260304_002516/
├─ job.json              # 任务元数据（状态、配置、结果、讨论记录）
├─ clip_0.mp4            # 第 1 段视频片段
├─ clip_1.mp4            # 第 2 段视频片段
├─ ...
└─ final.mp4             # 合成后的最终视频

output/images/           # 图片生成输出
```

---

## 二次开发指南

### 新增 T2V 工作流模式

1. 将工作流 JSON 放到 `workflows/wan2.2/`
2. 在 `video/generator.py` 的 `_WORKFLOW_PROFILES` 中添加映射（file、prompt nodes、seed nodes 等）
3. 在 `main.py` 的 `--quality` 选项和 UI 下拉中补充该模式

### 接入自定义图片 API

修改 `video/image_generator.py` 中 `QwenImageGenerator.generate()` 的请求格式与响应解析。

### 新增 I2V 工作流

参照 `video/i2v_generator.py` 或 `video/ltx_i2v_generator.py` 的模式，加载对应工作流 JSON 并注入参数。

### Prompt 工程

- 编辑 `promptbase/wan22_bestpractice.md` 和 `promptbase/ltx_promptbase.md` 更新最佳实践
- `agents/prompt_bestpractice.py` 中内嵌了 Wan2.2 Prompt 公式供 Agent 引用

---

## 已知说明

- Electron 控制台可能出现 Chromium 缓存警告，不影响功能
- `icon.png` 缺失仅触发警告，不影响主流程
- 单段视频生成默认超时 30 分钟，可通过 `VideoConfig.generation_timeout` 调整
- ComfyUI API Key 为可选配置，仅在远程部署时需要
