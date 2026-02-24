# Video Pipeline — 多 Agent 协作视频生成管线

## 项目概述

本项目是一个**端到端的 AI 视频生成管线**，通过 3 个 AI Agent（文案师、镜头师、裁判）多轮协作讨论，自动生成高质量的视频创作方案，然后调用本地 ComfyUI + Wan2.2 工作流逐段生成 5 秒视频片段，最终用 ffmpeg 合成完整视频。

**核心流程：用户给一个主题 → Agent 讨论出分镜方案 → 自动生成视频 → 用户审核 → 合成成片。**

---

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM 通信 | OpenAI SDK（兼容任意 OpenAI API 格式的 LLM） |
| 视频生成 | ComfyUI + Wan2.2 14B（本地部署） |
| 视频合成 | ffmpeg |
| 语言 | Python 3.10+ |
| 依赖 | `openai>=1.0.0`（唯一 pip 依赖） |

---

## 目录结构

```
videopipeline/
├── main.py                  # 主入口，串联完整 5 阶段流程
├── config.py                # 全局配置（LLM、视频参数、管线参数）
├── requirements.txt         # pip 依赖（仅 openai）
├── agents/                  # AI Agent 模块
│   ├── base.py              # BaseAgent 基类（封装 LLM 调用）
│   ├── copywriter.py        # 文案师 Agent
│   ├── cinematographer.py   # 镜头师 Agent
│   ├── judge.py             # 裁判 Agent（评审 + enriched prompt 生成）
│   └── discussion.py        # DiscussionOrchestrator 多轮讨论协调器
├── video/                   # 视频生成与合成模块
│   ├── generator.py         # VideoGenerator（ComfyUI 客户端 + 工作流注入）
│   └── composer.py          # VideoComposer（ffmpeg 合成 + 交互审核）
├── workflows/               # ComfyUI 工作流 JSON 文件
│   ├── wan22_lora4.json     # 快速模式工作流（Lora 4步，~60s/片段）
│   └── wan22_full.json      # 高质量模式工作流（标准 20步，~10min/片段）
└── output/                  # 输出目录（讨论记录、prompt JSON、视频片段、成片）
```

---

## 架构

```
┌─────────────────────────────────────────────────┐
│              Discussion Orchestrator             │
│                                                  │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  │
│  │ 📝 文案师 │→│ 🎬 镜头师    │→│ ⚖️ 裁判   │  │
│  │Copywriter│  │Cinematograph.│  │  Judge    │  │
│  └──────────┘  └──────────────┘  └──────────┘  │
│       ↑              ↑                │         │
│       └──────────────┴────────────────┘         │
│                  (最多 3 轮)                      │
└─────────────────┬───────────────────────────────┘
                  │ 最终 Enriched Prompts (positive + negative)
                  ▼
         ┌────────────────┐
         │ Video Generator │ → ComfyUI + Wan2.2
         └────────┬───────┘
                  │ 5秒视频片段 (.mp4)
                  ▼
         ┌────────────────┐
         │  用户审核选择    │ → y/n/r (使用/跳过/重新生成)
         └────────┬───────┘
                  │ 选定片段
                  ▼
         ┌────────────────┐
         │ Video Composer  │ → ffmpeg 合成
         └────────────────┘
```

---

## 完整流程（5 个 Phase）

### Phase 1：多 Agent 讨论（自动）

三个 Agent 按固定顺序发言，最多进行 3 轮，直到裁判通过：

```
文案师 → 镜头师 → 裁判 → (若未通过) → 文案师 → 镜头师 → 裁判 → ...
```

- **文案师 (`CopywriterAgent`)**：根据主题撰写分段文案（每段 5 秒），输出"总体构思 + 分段文案（文案内容 + 画面描述）"
- **镜头师 (`CinematographerAgent`)**：为每段设计镜头语言，输出"视觉风格定义 + 分镜设计（镜头类型、构图、运动方式、英文 video prompt）"
- **裁判 (`JudgeAgent`)**：评审方案质量，**最高优先级是风格一致性**，输出"评分 + 评审意见 + 一致性检查表"，判定通过或返修

裁判通过后，还会额外调用一次 LLM，综合全部讨论生成 **enriched prompts**——为每个片段输出最终的 `positive_prompt`（英文，详细到可直接生成）和 `negative_prompt`（英文，按片段定制）。

### Phase 2：用户确认

展示所有片段的 enriched prompt，用户输入 `y` 确认后开始生成。

### Phase 3：视频生成

`VideoGenerator` 依次将每个片段的 prompt 注入 ComfyUI 工作流并提交：
1. 加载工作流模板 JSON
2. 动态注入：正向 prompt、反向 prompt、分辨率、帧数、种子
3. 提交到 ComfyUI API (`POST /prompt`)
4. 轮询 `/queue` 和 `/history/{prompt_id}` 等待完成
5. 从 ComfyUI 下载生成的 MP4 文件

### Phase 4：用户审核

逐个展示生成的视频片段，用户可选择：
- `y` — 使用该片段
- `n` — 跳过
- `r` — 标记重新生成

### Phase 5：视频合成

使用 ffmpeg 将选定的片段按序号拼接成最终视频。优先用 `concat` 协议（快速无损），失败则回退到 `filter_complex` 重编码模式。

---

## 配置详解

### `config.py` 数据结构

```python
@dataclass
class LLMConfig:
    api_key: str        # LLM API Key（环境变量 LLM_API_KEY）
    base_url: str       # LLM API 地址（环境变量 LLM_BASE_URL，默认 http://localhost:23333/api/openai/v1）
    model: str          # 模型名称（环境变量 LLM_MODEL，默认 claude-opus-4.6）
    temperature: float  # 0.7
    max_tokens: int     # 8192

@dataclass
class VideoConfig:
    comfyui_url: str       # ComfyUI API 地址（默认 http://localhost:8189）
    workflow_path: str     # 自定义工作流路径（留空用内置）
    quality_mode: str      # "fast"（Lora 4步 ~60s）或 "quality"（标准 20步 ~10min）
    width: int             # 640
    height: int            # 640
    length: int            # 81（帧数，81帧 ≈ 5秒 @16fps）
    fps: int               # 16
    negative_prompt: str   # 全局默认反向提示词
    poll_interval: int     # 轮询间隔 15s
    generation_timeout: int # 单片段超时 1800s（30min）
    output_dir: str        # 输出目录 ./output

@dataclass
class PipelineConfig:
    llm: LLMConfig
    video: VideoConfig
    max_discussion_rounds: int  # 最多讨论轮数（默认 3）
    language: str               # "zh"
```

### 环境变量

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | `no-key` |
| `LLM_BASE_URL` | LLM API 端点 | `http://localhost:23333/api/openai/v1` |
| `LLM_MODEL` | 模型名称 | `claude-opus-4.6` |
| `COMFYUI_URL` | ComfyUI 服务地址 | `http://localhost:8189` |
| `COMFYUI_WORKFLOW` | 自定义工作流 JSON 路径 | （空，用内置） |
| `VIDEO_QUALITY` | 视频质量模式 | `fast` |
| `VIDEO_OUTPUT_DIR` | 输出目录 | `./output` |

---

## 使用方法

### 安装

```bash
pip install -r requirements.txt
```

额外需要：
- **ComfyUI**（本地运行，加载 Wan2.2 14B 模型）
- **ffmpeg**（用于视频合成，需加入 PATH）

### 命令行参数

```bash
python main.py [选项]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--topic TEXT` | 视频主题（不指定则交互输入） | — |
| `--discuss-only` | 只讨论不生成视频 | `false` |
| `--api-key TEXT` | LLM API Key | 环境变量 |
| `--base-url TEXT` | LLM API 地址 | 环境变量 |
| `--model TEXT` | LLM 模型名称 | 环境变量 |
| `--comfyui-url TEXT` | ComfyUI 地址 | `http://localhost:8189` |
| `--workflow PATH` | 自定义工作流 JSON | 内置默认 |
| `--quality fast\|quality` | 视频质量模式 | `fast` |
| `--width INT` | 视频宽度 | `640` |
| `--height INT` | 视频高度 | `640` |
| `--length INT` | 视频帧数 | `81` |
| `--fps INT` | 帧率 | `16` |
| `--output-dir PATH` | 输出目录 | `./output` |
| `--max-rounds INT` | 最大讨论轮数 | `3` |

### 示例

```bash
# 快速模式，指定主题
python main.py --topic "4个星座的末日庇护所" --quality fast

# 高质量模式
python main.py --topic "深海水母的舞蹈" --quality quality

# 只讨论不生成视频（调试 prompt 用）
python main.py --topic "赛博朋克城市夜景" --discuss-only

# 交互模式（运行后手动输入主题）
python main.py

# 使用自定义 LLM
python main.py --base-url http://localhost:11434/v1 --model llama3 --api-key dummy --topic "秋天的城市"
```

---

## 关键数据结构

### `VideoSegmentPrompt`（讨论输出 → 视频生成输入）

```python
@dataclass
class VideoSegmentPrompt:
    index: int              # 片段序号（从 1 开始）
    time_range: str         # 时间范围，如 "0-5s"
    copywriting: str        # 中文文案内容
    scene_description: str  # 中文画面描述
    camera_type: str        # 镜头类型
    video_prompt: str       # 英文正向 prompt（用于 AI 视频生成）
    negative_prompt: str    # 英文反向 prompt
```

### `GeneratedClip`（视频生成输出）

```python
@dataclass
class GeneratedClip:
    index: int        # 片段序号
    prompt: str       # 使用的 prompt
    file_path: str    # 视频文件路径
    status: str       # "success" | "failed" | "pending"
    error: str        # 错误信息
```

---

## 工作流机制（ComfyUI）

`VideoGenerator` 通过节点 ID 映射来注入参数到 ComfyUI 工作流 JSON：

```python
# workflows/ 目录下的 JSON 是 ComfyUI 导出的工作流
# 每种模式有一套节点映射：

"fast": {                                    # wan22_lora4.json
    "positive_prompt_nodes": ("9",),         # 正向 prompt 注入到节点 9
    "negative_prompt_nodes": ("13",),        # 反向 prompt 注入到节点 13
    "latent_nodes": ("14",),                 # 分辨率/帧数注入到节点 14
    "seed_nodes": ("10",),                   # 随机种子注入到节点 10
    "output_nodes": ("16",),                 # 输出文件名前缀在节点 16
}

"quality": {                                 # wan22_full.json
    "positive_prompt_nodes": ("11",),        # 节点映射不同
    "negative_prompt_nodes": ("12",),
    "latent_nodes": ("4",),
    "seed_nodes": ("6",),
    "output_nodes": ("14",),
}
```

注入逻辑（在 `_build_workflow` 方法中）：
- 正向/反向 prompt → 修改对应节点的 `inputs.text`
- 分辨率/帧数 → 修改 latent 节点的 `inputs.width`/`height`/`length`
- 种子 → 修改 seed 节点的 `inputs.noise_seed`
- 输出前缀 → 修改 output 节点的 `inputs.filename_prefix`

如需添加新工作流，在 `workflows/` 放入 JSON 文件，并在 `generator.py` 的 `_WORKFLOW_PROFILES` 字典中添加对应的节点映射。

---

## 输出文件

每次运行会在 `output/` 下生成：

| 文件 | 说明 |
|------|------|
| `discussion_YYYYMMDD_HHMMSS.md` | 完整讨论记录（Markdown 格式） |
| `prompts_YYYYMMDD_HHMMSS.json` | 最终 enriched prompts（JSON） |
| `{session_name}/clip_001.mp4` ... | 各片段视频文件 |
| `final_{session_name}.mp4` | 最终合成视频 |

### prompts JSON 格式

```json
{
  "topic": "主题",
  "visual_style": "镜头师定义的视觉风格",
  "segments": [
    {
      "index": 1,
      "time_range": "0-5s",
      "copywriting": "中文文案",
      "scene_description": "中文画面描述",
      "camera_type": "镜头类型",
      "positive_prompt": "English detailed positive prompt...",
      "negative_prompt": "English negative prompt..."
    }
  ]
}
```

---

## Agent 设计要点

### 文案师 (`copywriter.py`)
- System prompt 要求输出固定格式：`## 总体构思` + `## 分段文案`（每段含"文案内容"和"画面描述"）
- 第 1 轮直接根据主题创作；后续轮次根据裁判反馈修改

### 镜头师 (`cinematographer.py`)
- System prompt 要求输出：`## 视觉风格定义` + `## 分镜设计`（每段含"镜头类型""构图""运动方式"和**英文 video 生成 prompt**）
- **关键**：prompt 必须英文，且所有片段必须保持视觉风格一致

### 裁判 (`judge.py`)
- 评审维度：文案质量、镜头设计、**风格一致性（最高优先级）**、Prompt 质量、整体协调
- 通过判定标记：输出中包含 `✅ 通过` 字样
- 通过后额外执行 `enrich_prompts()`：用独立的低温度 (0.3) LLM 调用，将讨论综合为每段的 `positive_prompt` + `negative_prompt`，输出纯 JSON 数组

### 讨论协调器 (`discussion.py`)
- `DiscussionOrchestrator.run(topic)` 是讨论入口
- 维护全局 `history: list[Message]`，每个 Agent 发言都能看到完整历史
- 到达最大轮数强制通过
- 返回 `DiscussionResult`，包含 `final_prompts: list[VideoSegmentPrompt]`

---

## BaseAgent 机制

所有 Agent 继承自 `BaseAgent`：

```python
class BaseAgent(ABC):
    def __init__(self, name: str, llm_config: LLMConfig)  # 初始化 OpenAI client
    def system_prompt(self) -> str                          # 抽象：角色系统提示词
    def build_user_prompt(self, topic, history, round_num) -> str  # 抽象：构建 user prompt
    def respond(self, topic, history, round_num) -> Message # 调用 LLM 生成回复
    def format_history(history) -> str                      # 静态：格式化历史消息
```

LLM 调用使用 OpenAI SDK `chat.completions.create()`，超时 300 秒，兼容任何 OpenAI API 格式的端点。

---

## 依赖 / 前置条件

1. **Python 3.10+**
2. **pip install openai**（唯一 Python 依赖）
3. **ComfyUI 本地运行**，加载 Wan2.2 14B 模型和对应 LoRA（快速模式需要 LightX2V LoRA）
4. **ffmpeg** 在 PATH 中可用（用于视频合成）
5. **OpenAI 兼容的 LLM API**（本地代理、OpenAI、Claude 等均可，只要兼容 OpenAI SDK 格式）

---

## 扩展指南

- **添加新工作流**：将 ComfyUI 导出的 JSON 放入 `workflows/`，在 `generator.py` 的 `_WORKFLOW_PROFILES` 中注册节点映射
- **添加新 Agent**：继承 `BaseAgent`，实现 `system_prompt()` 和 `build_user_prompt()`，在 `DiscussionOrchestrator` 中集成
- **修改讨论流程**：编辑 `DiscussionOrchestrator.run()` 方法中的 Agent 调用顺序
- **调整 prompt 格式**：修改各 Agent 的 `system_prompt()` 中的格式要求
- **修改视频参数**：通过命令行参数或 `config.py` 调整分辨率、帧数、超时时间等
