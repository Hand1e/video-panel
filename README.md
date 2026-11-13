# 家庭视频工作台 · Family Video Studio

一个人（+ 爱人 + 4 个月宝宝）也能做生活区视频的个人工作台，运行时由 **DeepSeek V4.1 Flash** 驱动，可接入 **DeepSeek Harness** 作为 agent 工具。

```
选题（今日热门 / 单个选题分析）→ 脚本·台词大纲 → 简笔画分镜 → 拍摄清单 → 素材理解 → 剪辑方案 → 剪辑 + 审片 → 复盘校准
                                                                     ↑ 只有素材时：一键直剪 ┘
```

每个创作环节都是 **生成 → 评审 → 修改** 的循环（`studio/loop.py`）：

- 固定评分表（`studio/rubrics.py`），每个维度 0–10；有一票否决维度（如：可行性、宝宝安全/隐私、可拍性）。
- 停止条件：全部维度 ≥ 7 且否决项通过 / 最多 3 轮 / 分数提升 < 0.3（停滞）。永远采用分数最高的一版，不会越改越差。
- 每条问题带 `stage_owner`：如果是上游的问题（例如剪辑审片发现“脚本没有钩子”），会建议回退，而不是在下游硬修。
- 剪辑环节的评审会看渲染出的预览帧（视觉），满意后再出高清成片。
- 发布后填写真实数据，进入校准记忆，之后的选题判断会参考。

## 功能

| 模块 | 说明 |
|---|---|
| 选题 | 每天 5 个：**热点改编**（B站生活区排行 + 全站热门，按“爆款系数 = 播放 ÷ UP 粉丝”排序，优先借小 UP 也能爆的选题）+ **月龄日历**（按宝宝出生月份算月龄，给出本月/下月常见里程碑和安全提示，不依赖热点、一定拍得出来）；单个链接/关键词/截图分析，给出结论 + 依据 + 证伪条件，证据不足会自动补搜（DeepSeek Search/Fetch） |
| 脚本 | 结构化 beats + 台词；宝宝镜头是“捕捉式”（希望拍到 / 怎么诱导 / 拍不到怎么办） |
| 分镜 | 确定性 SVG 简笔画（模型只选参数）：POV / 三脚架 / 爱人手持，全景~特写，16:9 / 9:16 |
| 拍摄清单 | 按“宝宝清醒时段 / 午睡只拍大人 / 需要爱人掌镜”分组，少挪机位；每条有拍手+口播场记 |
| 素材 | ffmpeg 抽帧 + 模糊/晃动指标、静音、拍手场记、腾讯云语音识别、双机位音频互相关对齐、多段并行分析 |
| 剪辑 | 技巧库：钩子前置、跳剪、机位交替、J/L-cut、推镜、变速、卡点、换收音；时间线自动吸附到句子边界/鼓点；ASS 字幕关键词高亮 |
| 审片 | 预览帧 + 字幕交给评审，循环修改；出成片、SRT/ASS、封面、标题备选 |

## 在个人电脑上安装

需要 Python 3.11+、ffmpeg（`winget install Gyan.FFmpeg`）。

```bash
git clone <repo> video-studio && cd video-studio
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # 然后编辑 .env 填入 Key（.env 已被 .gitignore 忽略，不会上传）
python -m studio                # 打开 http://127.0.0.1:8765
```

`.env` 里需要：

- `DEEPSEEK_API_KEY`：DeepSeek 开放平台。
- `TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY`：腾讯云「语音识别 → 录音文件识别」。建议建一个只授权 ASR 的子账号。

**不填 Key 也能跑**：自动进入演示模式，所有模型输出带【演示数据】标记。B站数据、ffmpeg 分析、渲染都是真实的，方便先把流程走通。

## 接入 DeepSeek Harness

`harness-plugin/studio-tools.ts` 把工作台注册成 dsh 工具：`studio_analyze_topic`、`studio_daily_topics`、`studio_script`、`studio_storyboard`、`studio_footage_cut`、`studio_status`。

```bash
python -m studio                                   # 先启动工作台后端
# 修改 harness-plugin/cordis.yml 里的绝对路径，然后在 dsh 源码目录：
pnpm dsh web --patch /path/to/video-studio/harness-plugin/cordis.yml
```

在 Harness 里可以让 agent 每天 9:00 调用 `studio_daily_topics`，把选题推给你。
（dsh 仍是开发者预览版，接口变化时只需要改这个插件文件。）

## 拍摄约定（让自动剪辑更准）

1. 每条开拍先 **拍一下手**，再念「S03，第 2 条」。工作台据此对齐双机位并匹配分镜。
2. 宝宝镜头 **长录**，不要停机等。
3. 第一人称（POV）和三脚架尽量同时开机。

## 测试

```bash
python -m pytest -q
```

包括：循环停止规则、分镜渲染、拍摄清单、时间线校验与吸附、双机位对齐，以及一个用 ffmpeg 合成素材跑完整“素材直剪”并出片的端到端测试（约 1 分钟）。

## 目录

```
studio/      后端（FastAPI）：loop / rubrics / analysis / writing / storyboard / footage / editing / media / asr / sources
web/         工作台界面（无构建步骤）
harness-plugin/  DeepSeek Harness 插件
tests/
data/        运行数据（项目、素材分析、成片、校准记忆）— 已忽略，不会上传
```

## 隐私

- 素材默认 **原地引用**，不复制，不上传到除 DeepSeek（抽帧图）与腾讯云 ASR（音频）以外的任何地方。
- 剪辑评审有“隐私”否决项（门牌、快递单、窗外地标等），素材理解会标出疑似隐私片段。
- 出镜设置里的 `blur_face` 目前只是偏好记录，**自动打码尚未实现**。
