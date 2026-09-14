# AI Live Subtitles · 实时双语字幕

Windows 实时字幕工具，适合观看英文视频、学习编程课程或收听英文音频。采集 Chrome、系统声音或麦克风，通过阿里云百炼识别和翻译，在置顶悬浮窗中显示原文与译文。

<img src="assets/subtitle-avatar.png" alt="字幕助手图标" width="120">

## 功能

- **双语悬浮字幕**：流式显示原文和译文，窗口可拖动、调整宽度和字号，自动记忆位置与字号。
- **三种声源**：Chrome、系统声音、系统麦克风，可从托盘切换。
- **18 种目标语言**：默认中文；当前源语言配置为英语。
- **两种速度模式**：正常、速度优先。
- **热词词库**：内置 Python 教学和 CS2 电竞词库，支持自定义；启动时默认关闭。
- **锁定与点击穿透**：通过托盘或快捷键操作，观看视频时不挡鼠标。
- **自动暂停与恢复**：静音时暂停云端会话，有声后恢复；支持网络重连和耳机、扬声器切换后的采集恢复。

## 安装与启动

### 环境要求

- Windows 11；Chrome 进程采集要求 Windows build 20348 或更高。
- Python 64 位，开发环境使用 Python 3.14。
- 可调用模型的阿里云百炼 API Key 及对应工作空间。
- 使用浏览器声源时需要 Google Chrome；系统声音和麦克风不依赖 Chrome。

### 1. 安装依赖

下载并解压仓库，或使用 Git：

```powershell
git clone https://github.com/liuxingboy/ai-live-subtitles.git
cd ai-live-subtitles
```

在项目目录打开 PowerShell，运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后续命令直接使用虚拟环境中的 Python，无需先激活环境。

### 2. 配置百炼

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

| 配置项 | 填写内容 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 你的百炼 API Key |
| `DASHSCOPE_WORKSPACE_ID` | 与 Key 匹配的北京地域工作空间 ID |
| `DASHSCOPE_WS_HOST` | 通常留空，由工作空间 ID 生成；自定义时只填主机名，不含协议或路径 |

系统环境变量优先于 `.env`。可先检查配置格式：

```powershell
.\.venv\Scripts\python.exe tools\api_debug.py --check-config
```

格式检查不连接云端，不能验证账号权限。

### 3. 启动字幕

打开 Chrome 播放英文视频，然后运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

字幕窗口和系统托盘会同时出现，PowerShell 保留运行日志。默认使用 **Chrome 声源、中文目标、正常速度、关闭热词**。

日常使用可双击 `LiveSubtitles.exe`，不显示终端。它是项目启动器，仍依赖完整项目目录和 `.venv`，不能单独移动使用。需要桌面快捷方式时运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
```

关闭字幕窗口或从托盘选择 **退出**，都会结束程序。

## 使用方法

### 切换声源

在 Windows 右下角找到程序图标；如果未显示，先展开 **「^」隐藏图标**。右键 → **声源选择**：

| 声源 | 采集内容 |
| --- | --- |
| 谷歌浏览器 | Chrome 进程树的声音，可能包含多个标签页 |
| 系统声音 | Windows 默认多媒体播放设备的声音，包含其他应用的播放声音 |
| 系统麦克风 | Windows 默认多媒体录音设备的输入，需要允许桌面应用访问麦克风 |

三个选项只能选择一个。声源、语言和速度等会话设置切换后自动生效，无需重启；重建会话时字幕会短暂中断，中断期间音频不补发。

在 Windows 声音设置中把耳机换成扬声器后，Chrome 和系统声音会自动重建采集，保留当前翻译设置。更换默认麦克风后，需要手动切到其他声源再切回。程序暂不提供具体设备列表，也不会在设备失败时自动改采其他声源。

### 目标语言与速度

右键托盘 → **目标语言**，选择译文语言。当前可选：

| 语言 | 代码 | 语言 | 代码 | 语言 | 代码 |
| --- | --- | --- | --- | --- | --- |
| 中文 | `zh` | 英语 | `en` | 日语 | `ja` |
| 韩语 | `ko` | 法语 | `fr` | 德语 | `de` |
| 西班牙语 | `es` | 葡萄牙语 | `pt` | 俄语 | `ru` |
| 意大利语 | `it` | 阿拉伯语 | `ar` | 印地语 | `hi` |
| 泰语 | `th` | 越南语 | `vi` | 印度尼西亚语 | `id` |
| 马来语 | `ms` | 土耳其语 | `tr` | 荷兰语 | `nl` |

右键托盘 → **速度与准度**：

- **正常**：使用模型默认断句设置。
- **速度优先**：缩短断句等待，尝试更早输出翻译；句子可能更碎，译文修订可能更频繁。

速度优先不能保证所有内容都更快，实际延迟也受网络和云端处理影响。若译文完整性变差，可切回正常。

### 热词词库

右键托盘 → **热词**，选择词库后勾选 **启用热词**。

- **Python 教学**：编程语法、数据结构、函数、面向对象和开发工具等术语。
- **CS2 电竞**：游戏相关术语。

每次启动默认不启用热词，预选 Python 词库。关闭热词时可以先选择词库，不会中断字幕。热词是给模型的翻译提示，不是强制替换；目前仅用于中文目标，切换到其他目标语言时暂停应用。

自定义词库：在 `config/hotwords/` 下新建 UTF-8 编码的 `.json` 文件，例如 `my_terms.json`：

```json
{
  "variable": "变量",
  "list comprehension": "列表推导式"
}
```

重启程序后，文件名会出现在词库菜单中。修改已有词库后，关闭再开启热词即可重新加载。文件无法读取或格式错误时，程序保留原设置。

### 窗口与快捷键

拖动字幕背景移动窗口，拖动右下角调整宽度。右键窗口可调整字号。位置、宽度和字号自动保存；启动时默认解锁。

| 操作 | 默认快捷键 |
| --- | --- |
| 锁定/解锁并切换点击穿透 | `Ctrl+Alt+L` |
| 放大字号 | `Ctrl+Alt+=` |
| 缩小字号 | `Ctrl+Alt+-` |
| 退出 | `Ctrl+Alt+Q` |

锁定功能也可通过托盘 **锁定并点击穿透** 操作。快捷键冲突时会尝试加入 `Shift`，以菜单显示为准；无法注册快捷键时禁用锁定，避免无法解锁。

### 静音与连接恢复

默认连续静音 30 秒后关闭云端会话，本地继续检测声音，有声后自动恢复。静音判断基于音量，音乐也可能保持会话，特别轻的语音可能被当作静音。

网络中断、写入超时和已识别的临时云端错误会自动重连，等待间隔逐步增加到 15 秒。账号权限、配置或未知错误可能停止翻译。设备持续变化或缺失时，采集恢复最多连续重试 5 次。连接恢复会保留当前设置，但无法补回中断期间的内容。

## 命令行

命令行参数用于指定本次启动设置，窗口模式下仍可从托盘修改。

```powershell
# 系统声音 + 速度优先 + 日语译文
.\.venv\Scripts\python.exe main.py --source system --speed fast --target-language ja

# 启用 Python 教学词库
.\.venv\Scripts\python.exe main.py --hotwords config\hotwords\python.json

# 离线预览窗口，不采集音频、不连接云端
.\.venv\Scripts\python.exe main.py --demo
```

| 参数 | 作用 |
| --- | --- |
| `--source chrome/system/microphone` | 初始声源，默认 `chrome` |
| `--target-language 语言代码` | 目标语言，默认 `zh` |
| `--speed normal/fast` | 速度模式，默认 `normal` |
| `--hotwords 文件路径` | 启用指定词库 |
| `--no-hotwords` | 关闭词库，优先于 `--hotwords` |
| `--silence-seconds 秒数` | 静音暂停阈值，默认 30；0 表示关闭自动暂停 |
| `--silence-db 数值` | 静音音量阈值，默认 -55；更低的值可检测更轻的声音 |
| `--final-only` | 窗口只显示最终字幕，减少文本变化 |
| `--partial` | 终端也输出流式中间结果 |
| `--seconds 秒数` | 限时采集，时长包含重连等待 |
| `--pid 进程号` | 指定 Chrome 进程，仅适用于 Chrome 声源 |
| `--console` | 纯终端模式，**没有字幕窗口和系统托盘** |
| `--demo` | 离线预览窗口 |

排查问题时使用普通窗口命令 `main.py` 即可同时查看托盘和终端日志。只有不需要窗口时才使用 `--console`。

## 常见问题

**没有托盘图标？** 先检查 Windows 隐藏图标区域。如果使用了 `--console`，停止程序后去掉该参数重新启动。

**一直显示“等待原文/翻译”？** 检查所选声源是否正确、是否正在播放清晰语音。启动时无声不会连接云端。设备或云端出现错误时，查看 PowerShell 中完整的 `[ERROR]` 行，窗口上的错误可能被截断。

**出现 `UNEXPECTED_ASR_ERROR`？** 这是错误类别，具体原因在后面的 `message`。已知的 ASR 超时、线程池容量不足会自动重连；没有详细原因的 ASR 错误最多自动恢复两次。其他情况需要根据完整消息排查。

**切换耳机后没恢复？** 确认 Windows 默认输出设备可正常播放。若程序已经停止，可从托盘再次选择当前声源重试。

**多个 Chrome 主进程无法自动选择？** 用以下命令查看进程，再通过 `--pid` 指定：

```powershell
.\.venv\Scripts\python.exe tools\audio_debug.py --list
```

**如何提供故障信息？** 记录启动命令、所选声源、出错前的操作和完整终端错误。退出后可查看 `logs/phase2_last_run.json`，其中保存最近一次运行统计，每次退出覆盖。不要提供 `.env` 或 API Key。

## 隐私与费用

字幕功能需要联网，会把选中声源的音频发送给阿里云百炼，费用取决于账号和服务计费。正常字幕模式不保存录音或字幕文件；终端会显示字幕，运行统计保存在本地 `logs/` 中。

仓库排除了密钥、录音、运行日志、个人窗口设置和虚拟环境。单独运行音频诊断工具 `tools/audio_debug.py` 会生成本地 WAV 录音；仅使用 `--list` 不录音。

## 开发

| 目录 | 内容 |
| --- | --- |
| `audio/` | Chrome、系统回环和麦克风采集，默认输出设备检测 |
| `app/` | 设置、词库加载与会话切换控制 |
| `ui/` | 字幕窗口、托盘菜单和快捷键 |
| `subtitle/` | 原文与译文配对、字幕显示状态 |
| `tools/` | 云端会话、重连、诊断工具和启动器构建脚本 |
| `config/hotwords/` | 内置和自定义词库 |
| `tests/` | 回归测试 |

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

测试不连接百炼；部分测试会调用 Windows 音频设备接口，不保存录音。真实字幕质量和网络恢复效果需要实际播放音频验证。

新增声源从 `audio/sources.py` 的 `SOURCE_REGISTRY` 接入；目标语言与速度选项集中在 `app/preferences.py`。启动器源码为 `tools/windows_launcher.cpp`，构建脚本 `tools/build_launcher.cmd` 使用 Visual Studio Build Tools，使用前需核对本机安装路径。

当前代码使用 `qwen3.5-livetranslate-flash-realtime`，音频为 16 kHz、单声道 PCM16。接口文档：[模型说明](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime)、[客户端事件](https://help.aliyun.com/zh/model-studio/live-translator-client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/live-translator-server-events)。

## 致谢

本项目由 OpenAI Codex 辅助开发，程序头像由 AI 生成。语音识别与翻译服务由阿里云百炼提供。
