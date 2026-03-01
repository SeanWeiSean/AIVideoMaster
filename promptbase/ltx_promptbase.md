# LTX-2 Prompting Guide 最佳实践

> 来源：https://docs.ltx.video/api-documentation/prompting-guide

LTX-2 的核心在于用自然、流畅的语言描绘一个完整的视觉故事——从开头到结尾涵盖模型所需的所有元素。

---

## 一、Prompt 核心六要素

### 1. 建立镜头（Establish the Shot）
- 使用与目标类型匹配的电影术语
- 包含镜头规模（shot scale）或类别特征来细化视觉风格

### 2. 设定场景（Set the Scene）
- 描述光照条件、色彩搭配、表面纹理和氛围
- 用以建立画面的情绪和基调

### 3. 描述动作（Describe the Action）
- 将核心动作写成自然的叙事序列
- 从开始到结束清晰流畅

### 4. 定义角色（Define the Character(s)）
- 包含年龄、发型、服装和显著特征
- 通过**身体线索（physical cues）**表达情感，而非抽象标签（不要写 "sad"，要写出表现悲伤的动作/表情）

### 5. 指定镜头运动（Identify Camera Movement(s)）
- 明确说明镜头如何、何时移动
- 描述运动完成后主体的状态有助于模型准确完成运镜

### 6. 描述音频（Describe the Audio）
- 清晰描述环境音、音乐、对话或歌唱
- 对话内容使用引号标注
- 需要时指定语言和口音

---

## 二、最佳实践

- ✅ 将 prompt 写成**单一流畅段落**
- ✅ 使用**现在时态动词**描述动作和运动
- ✅ 细节程度匹配镜头规模（特写需要更多细节，远景可以少一些）
- ✅ 相对于主体描述镜头运动
- ✅ 目标长度：**4–8 个描述性句子**
- ✅ 大胆迭代——LTX-2 专为快速实验设计

---

## 三、辅助术语词典

### 视觉类别（Categories）

| 类别 | 关键词 |
|------|--------|
| **动画** | Stop-motion, 2D / 3D animation, Claymation, Hand-drawn |
| **风格化** | Comic book, Cyberpunk, 8-bit pixel, Surreal, Minimalist, Painterly, Illustrated |
| **电影** | Period drama, Film noir, Fantasy, Epic space opera, Thriller, Modern romance, Experimental film, Arthouse, Documentary |

### 视觉细节（Visual Details）

| 维度 | 关键词 |
|------|--------|
| **光照** | Flickering candles, Neon glow, Natural sunlight, Dramatic shadows |
| **纹理** | Rough stone, Smooth metal, Worn fabric, Glossy surfaces |
| **色彩** | Vibrant, Muted, Monochromatic, High contrast |
| **氛围** | Fog, Rain, Dust, Smoke, Particles |

### 声音与语音（Sound and Voice）

| 维度 | 关键词 |
|------|--------|
| **环境音** | Coffeeshop noise, Wind and rain, Forest ambience with birds |
| **对话风格** | Energetic announcer, Resonant voice with gravitas, Distorted radio-style, Robotic monotone, Childlike curiosity |
| **音量** | Whisper, Mutter, Shout, Scream |

### 技术风格标记（Technical Style Markers）

| 维度 | 关键词 |
|------|--------|
| **镜头语言** | Follows, Tracks, Pans across, Circles around, Tilts upward, Pushes in / pulls back, Overhead view, Handheld movement, Over-the-shoulder, Wide establishing shot, Static frame |
| **胶片特征** | Film grain, Lens flares, Pixelated edges, Jittery stop-motion |
| **规模感** | Expansive, Epic, Intimate, Claustrophobic |
| **节奏与时间** | Slow motion, Time-lapse, Rapid cuts, Lingering shot, Continuous shot, Freeze-frame, Fade-in / fade-out, Seamless transition, Sudden stop |
| **视觉特效** | Particle systems, Motion blur, Depth of field |

---

## 四、LTX-2 擅长的内容

| 类型 | 说明 |
|------|------|
| **电影级构图** | 远景、中景、特写配合讲究的布光、浅景深和自然运动 |
| **人物情感表达** | 单人情感特写、细腻手势、面部微表情 |
| **氛围与场景** | 雾气、薄雾、黄金时段光线、雨、倒影、环境纹理 |
| **清晰的镜头语言** | 明确指令如 "slow dolly in"、"handheld tracking" |
| **风格化美学** | 绘画风、黑色电影、胶片感、时尚编辑、像素动画 |
| **灯光与情绪控制** | 背光、色彩方案、轮廓光、闪烁灯具 |

### 语音能力
- 角色可以**说话和唱歌**
- 支持**多语言**

---

## 五、LTX-2 应避免的内容

| 避免事项 | 替代方案 |
|----------|----------|
| **内心情感状态** | 用视觉线索代替 "sad"、"confused" 等抽象标签 |
| **文字和 Logo** | 可读文本目前不可靠 |
| **复杂物理** | 混乱运动可能产生伪影（舞蹈 OK） |
| **过载场景** | 过多角色或动作会降低清晰度 |
| **矛盾光源** | 混合光逻辑会混淆场景解读 |
| **过于复杂的提示** | 从简单开始，逐步叠加复杂度 |

---

## 六、示例 Prompt

### 示例 1：新闻直播场景

```
EXT. SMALL TOWN STREET – MORNING – LIVE NEWS BROADCAST The shot opens on a news
reporter standing in front of a row of cordoned-off cars, yellow caution tape
fluttering behind him. The light is warm, early sun reflecting off the camera
lens. The faint hum of chatter and distant drilling fills the air. The reporter,
composed but visibly excited, looks directly into the camera, microphone in hand.
Reporter (live): "Thank you, Sylvia. And yes — this is a sentence I never thought
I'd say on live television — but this morning, here in the quiet town of New
Castle, Vermont… black gold has been found!" He gestures slightly toward the field
behind him. Reporter (grinning): "If my cameraman can pan over, you'll see what
all the excitement's about." The camera pans right, slowly revealing a
construction site surrounded by workers in hard hats. A beat of silence — then,
with a sudden roar, a geyser of oil erupts from the ground, blasting upward in a
violent plume. Workers cheer and scramble, the black stream glistening in the
morning light. The camera shakes slightly, trying to stay focused through the chaos.
Reporter (off-screen, shouting over the noise): "There it is, folks — the moment
New Castle will never forget!" The camera catches the sunlight gleaming off the oil
mist before pulling back, revealing the entire scene — the small-town skyline
silhouetted against the wild fountain of oil.
```

### 示例 2：动画场景

```
The camera opens in a calm, sunlit frog yoga studio. Warm morning light washes
over the wooden floor as incense smoke drifts lazily in the air. The senior frog
instructor sits cross-legged at the center, eyes closed, voice deep and calm.
"We are one with the pond." All the frogs answer softly: "Ommm…" "We are one with
the mud." "Ommm…" He smiles faintly. "We are one with the flies." A pause. The
camera pans to the side towards one frog who twitches, eyes darting. Suddenly its
tongue snaps out, catching a fly mid-air and pulling it into its mouth. The
master exhales slowly, still serene. "But we do not chase the flies…" Beat. "not
during class." The guilty frog lowers its head in shame, folding its hands back
into a meditative pose. The other frogs resume their chant: "Ommm…" Camera holds
for a moment on the embarrassed frog, eyes closed too tightly, pretending nothing
happened.
```

---

## 七、图生视频（Image-to-Video）专用指南

> ⚠️ **核心原则**：图片已经确定了角色外观、场景和风格，prompt 中**不要重复描述角色外貌特征**，否则会与图片冲突导致人物变样。

### I2V Prompt 公式
**提示词 = 动作/运动 + 镜头运动（+ 可选：氛围/音频）**

### I2V 要点
1. **不描述角色外观**：不写发色、服装、五官等——这些由图片决定
2. **聚焦动态过程**：描述角色正在做什么、将要做什么，如何运动
3. **运动要具体**：用副词控制幅度和速度，如 "gently flips"、"slowly pours"
4. **镜头运动要明确**：如 "the camera slowly pushes in"、"static frame"
5. **如需固定镜头**：明确写 "static camera" 或 "the camera holds steady"
6. **可补充环境音/氛围**：如光线变化、蒸汽、声音等不改变角色外观的元素
7. **避免与图片矛盾**：不写图中没有的物件或与画面冲突的描述

### I2V 示例
```
The character gently pours batter onto the sizzling pan, tilting the bowl 
steadily as steam rises from the hot surface. She carefully sets the bowl 
down and picks up a spatula, watching the edges of the pancake begin to 
crisp and bubble. The camera holds in a medium close-up, static frame. 
The soft sizzle of oil and faint crackling fill the air.
```

---

## 八、Prompt 撰写要点总结

1. **单段落叙事**：像写微型剧本一样，用一段自然流畅的文字覆盖所有要素
2. **现在时态**：所有动作使用现在时，增强画面即时感
3. **由外而内**：先确定镜头/场景，再深入角色/动作细节
4. **情感外化**：通过肢体语言、面部动作表达情绪，不用抽象形容词
5. **镜头运动要具体**：说清起点、过程和终点（如 "The camera pans right, slowly revealing..."）
6. **音频独立描述**：环境音、对话、音乐分别明确描述
7. **对话用引号**：角色台词放在引号内，可附加语气/口音说明
8. **适度复杂度**：4-8 句为宜，避免一次塞入太多元素
9. **I2V 模式**：图生视频只写动作+运镜，**绝不重复描述图中已有的角色外观**
