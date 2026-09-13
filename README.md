# AI Live Subtitles · AI 实时双语字幕

面向 Windows 的 AI 实时双语字幕工具：可采集 Chrome 进程音频、默认系统播放声音或默认麦克风，通过阿里云百炼的实时语音识别与翻译服务，在置顶悬浮窗中显示原文和所选目标语言的译文（默认中文）。

**这是一个由用户提出需求并实际验收、由 OpenAI Codex 辅助开发的 AI 项目。** 代码实现、调试和文档编写使用了 AI 辅助；应用的二次元头像图标由 AI 生成。语音识别与翻译调用云端 AI 服务，不是本地离线模型。字幕可能出现误识别、误译和流式修订。

<img src="assets/subtitle-avatar.png" alt="AI 生成的字幕助手头像" width="160">

## 从 GitHub 下载后启动

需要支持进程音频回环捕获的 Windows（本项目在 Windows 11 上验证）、Chrome 和 Python。开发环境使用 Python 3.14。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在本机 `.env` 中填写自己的百炼 API Key 和工作空间配置，然后播放 Chrome 视频并双击 `LiveSubtitles.exe`，或运行 `.\.venv\Scripts\python.exe main.py`。服务需要联网，费用与可用性由云服务提供方决定；活动会话会向百炼发送当前选中声源的音频。

仓库仅提供空白配置模板，不包含开发者的 API Key、录音、日志、窗口偏好或虚拟环境。不要提交自己的 `.env`。离线查看外观可运行 `.\.venv\Scripts\python.exe main.py --demo`，该模式不采集音频、不连接云服务。

主要功能：流式双语字幕、半透明紧凑窗口、位置和字号记忆、锁定与点击穿透、静音自动暂停云端会话、断线重连、可编辑的 Python / CS2 术语提示库。

测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -q`。以下内容保留实现阶段说明与使用细节。

## 双击启动

双击项目目录的 `LiveSubtitles.exe` 或桌面的“实时双语字幕”快捷方式即可启动，不弹出终端。请保留完整项目目录及 `.venv`，这个 EXE 是本机启动器，不是独立安装包；不要单独移动 EXE。关闭字幕窗即可结束程序。

移动整个项目目录后，运行 `powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1` 重建桌面快捷方式。快捷方式也可以在 Windows 中固定到开始菜单。终端排错仍使用 `.\.venv\Scripts\python.exe main.py`。

启动器支持原有参数，例如 `LiveSubtitles.exe --demo` 离线预览。修改启动器源码后可用 `tools\build_launcher.cmd` 重新编译（需本机 Visual Studio Build Tools）。

## 系统托盘与声源选择

启动后，Windows 系统托盘（可能在任务栏的隐藏图标区域）会显示与程序相同的头像图标。右键图标 → **声源选择**：

| 选项 | 采集范围 |
| --- | --- |
| 谷歌浏览器 | Chrome 进程树的声音，每次启动默认选择 |
| 系统声音 | Windows 默认多媒体播放设备的声音，包含其他应用；不包含麦克风输入，除非已由系统或其他软件播放出来 |
| 系统麦克风 | Windows 默认多媒体录音设备的输入；请允许桌面应用访问麦克风 |

三个选项互斥。选择后无需重启：程序会先停止旧采集并结束旧云端会话，然后建立新声源会话；字幕窗口保留，旧字幕清空。切换和建连期间会短暂中断字幕，期间音频不补发。快速连续选择时，以最后选择为准；旧采集未退出前不会开启新采集。若旧采集无法安全结束，会要求重启程序。

设备不可用时显示错误，不自动改采其他声源。选择同一声源可以在会话已失败后重试。默认设备在每次开始采集时重新读取；运行中更改 Windows 默认设备后，可先切换到其他声源再切回。当前版本不提供具体设备列表或默认设备变更的自动跟随。

右键托盘的 **锁定并点击穿透** 可勾选或取消：勾选后固定字幕窗口、让鼠标点击穿过字幕，取消后恢复拖动和操作。与原有快捷键使用相同切换逻辑，菜单显示实际快捷键（通常 `Ctrl+Alt+L`，冲突时为 `Ctrl+Alt+Shift+L`）。通过快捷键或窗口菜单切换后，打开托盘菜单会显示当前状态。沿用原有保护：快捷键不可用或正在退出时不允许启用锁定。

右键托盘的 **退出** 与字幕窗口的关闭按钮作用相同，均结束采集和会话后退出。托盘菜单不改变原有关闭窗口即退出的行为。已有热词、静音暂停、重连和字幕设置对三个声源共用；音频不保存为录音文件。

也可以通过命令行指定初始声源：

```powershell
.\LiveSubtitles.exe --source chrome
.\LiveSubtitles.exe --source system
.\LiveSubtitles.exe --source microphone
```

`--pid` 仅用于 Chrome。选择系统声音或麦克风无需运行 Chrome。`--demo` 为离线外观预览，托盘声源菜单禁用，不采集音频。

扩展入口为 `audio/sources.py` 的 `SOURCE_REGISTRY`：新增声源提供显示名称、解析函数及 `create(seconds, audio_queue)` / `alive()` 接口，返回兼容音频队列、停止事件和完成事件的采集对象。托盘选项和 CLI 可选项从注册表生成，翻译会话无需按声源增加分支。`app/translation_controller.py` 负责串行交接，`ui/tray.py` 负责菜单。

验证记录：49 项离线测试通过；本机 Windows 验证默认麦克风采集、系统回环捕获测试播放音频、原生托盘菜单显示，以及通过托盘进行“系统声音 → 系统麦克风 → 系统声音”切换并退出，无重叠或残留采集。上述切换验证使用本地会话桩，未上传音频；三种声源的实际云端字幕效果仍需使用验收。

## 目标语言

右键托盘 → **目标语言**，单选翻译输出语言。每次启动默认中文；支持以下 18 种常用语言，列表集中维护在 `app/preferences.py` 的 `TARGET_LANGUAGES`，托盘与命令行使用同一份列表。

| 语言 | 代码 |
| --- | --- |
| 中文 | `zh` |
| 英语 | `en` |
| 日语 | `ja` |
| 韩语 | `ko` |
| 法语 | `fr` |
| 德语 | `de` |
| 西班牙语 | `es` |
| 葡萄牙语 | `pt` |
| 俄语 | `ru` |
| 意大利语 | `it` |
| 阿拉伯语 | `ar` |
| 印地语 | `hi` |
| 泰语 | `th` |
| 越南语 | `vi` |
| 印度尼西亚语 | `id` |
| 马来语 | `ms` |
| 土耳其语 | `tr` |
| 荷兰语 | `nl` |

切换语言后无需重启程序：旧会话结束后使用新语言建立会话，保留声源、速度模式和其他启动选项，清空旧字幕。切换期间字幕会短暂中断；切换声源、切换速度、断线重连和静音恢复均沿用当前目标语言。源语识别仍沿用现有 `en`（英语）配置，本功能选择的是输出语言。

现有词库是英文到中文的映射，因此非中文目标不读取或发送这份中译词库；切回中文后重新应用，词库文件不改动。控制台译文标签随目标语言变化，例如 `[JA]`、`[FR]`；统计界面使用“原文/译文”。为兼容既有统计文件，`english_finals`、`chinese_finals` 字段名保留，分别表示原文和译文计数，并新增 `target_language` 标明目标语言。

```powershell
.\LiveSubtitles.exe --target-language ja
.\LiveSubtitles.exe --source system --speed fast --target-language en
```

语言依据：[当前模型官方语言列表](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime)。官方列出 60 种语言互译；本菜单先提供上述 18 种常用语言，程序只请求文本输出。验证：64 项离线测试通过，覆盖所有菜单语言的配置及互斥、终端标记、切换后保留配置、重连和静音恢复；无音频云端会话抽查英语、日语、阿拉伯语均返回正确目标参数，兼容速度优先并正常结束。尚未逐语种进行真实语音翻译质量验收。

## 速度与准度

右键托盘 → **速度与准度**，选择互斥的 **正常** 或 **速度优先**。每次启动默认正常，也可通过 `--speed fast` 指定初始模式。

- **正常**：保持原有会话配置，使用云端默认断句等待（当前服务返回 1000 毫秒）。
- **速度优先**：把 `turn_detection.silence_duration_ms` 设为 300 毫秒，让较短的语音停顿更早触发断句和翻译；译文可能更碎、上下文不足或修订更频繁。

切换模式无需重启程序，但会先结束旧采集和云端会话，再用所选模式新建会话，清空旧字幕，因此有短暂中断。当前声源、热词和其他启动选项保留。切换声源、断线重连和静音恢复都会沿用本次选择的模式。正常和速度优先使用同一模型、音频分包、字幕刷新频率和静音暂停策略；模式切换不改变这些设置。

```powershell
.\LiveSubtitles.exe --speed fast
.\LiveSubtitles.exe --speed normal
```

这是缩短断句等待的实验性优化，不保证连续说话时更快，也不代表端到端延迟一定减少 700 毫秒；云端处理和网络延迟仍存在。如果字幕过碎或翻译变差，切回正常即可。建议使用同一视频片段分别试两种模式，观察中文首次出现时间与译文完整性。

依据：[百炼客户端事件参数](https://help.aliyun.com/zh/model-studio/live-translator-client-events)。验证：55 项离线测试通过，覆盖模式互斥、切换时保留声源、正常配置恢复、重连和静音恢复沿用模式；独立无音频云端会话确认速度优先返回 300 毫秒、正常返回 1000 毫秒，并收到会话正常结束。尚未进行真实视频延迟 A/B 测量。

## 日常设置与自动暂停

照常运行 `main.py`，新增功能默认生效：

- 窗口位置、宽度、原文/译文字号自动保存到 `.local/window.json`，下次启动恢复；更换显示器后会把不可见位置移回屏幕。高度仍随字幕行数调整。锁定状态不保存，启动时始终可操作。
- 右键窗口可锁定、调整字号或退出，不增加常驻工具栏。
- 默认快捷键：`Ctrl+Alt+L` 锁定/解锁并切换点击穿透，`Ctrl+Alt+=` 放大字号，`Ctrl+Alt+-` 缩小字号，`Ctrl+Alt+Q` 退出。若有冲突，整组自动改为 `Ctrl+Alt+Shift`；**以启动终端和右键菜单显示为准**。两组均注册失败时禁用锁定，避免无法解锁。
- 默认连续静音 30 秒后发送 `session.finish`，完成收尾后关闭云端会话；本地继续检测 Chrome 音频。启动时没有声音也不会先建立云端连接。检测到约 300 ms 有声信号时自动恢复。
- 恢复包含约 1 秒前置音频，并在建连期间最多缓冲 20 秒，降低漏掉开头的概率；超出缓冲容量会丢弃最旧音频并提示。恢复可能有建连延迟，不能保证任何网络条件下都不丢字。网络故障后的重试仍丢弃旧连接音频。
- 静音判断是音量检测（默认 RMS ≤ -55 dBFS），不是识别人声。音乐、游戏声也会保持会话，音量特别低的语音可能被判为静音。暂停期间没有音频上传，但不承诺具体节省金额。
- 默认加载 `config/hotwords/python.json` 的 Python 教学术语，覆盖基础语法、数据结构、函数、面向对象、异常、异步编程和常用开发工具，适合观看 YouTube 英文 Python 教学。每次新会话都会应用。这是翻译提示，不是强制替换或准确率保证。

```powershell
# 60 秒静音才暂停；也可设为 0 关闭自动暂停
.\.venv\Scripts\python.exe main.py --silence-seconds 60
# 对很轻的声音更敏感
.\.venv\Scripts\python.exe main.py --silence-db -65
# 普通视频关闭术语词库
.\.venv\Scripts\python.exe main.py --no-hotwords
# 临时切换回 CS2 电竞词库
.\.venv\Scripts\python.exe main.py --hotwords config\hotwords\cs2.json
```

词库格式为 `{"variable": "变量", "list comprehension": "列表推导式"}`。双击 `LiveSubtitles.exe` 或正常运行 `main.py` 默认启用 Python 词库；已打开的字幕程序需关闭后重新启动。也可用 `--hotwords config\hotwords\python.json` 显式指定。修改文件后重新启动程序生效；不要填入密钥。运行统计新增 `silence_pauses` 和 `buffer_dropped_seconds`。

验证记录：37 项测试通过；模拟音频验证纯静音不建连、有声后建连、静音结束会话、再次有声恢复并保留开头；Windows 原生测试验证快捷键消息分发、点击穿透样式切换、字体和位置恢复；百炼无音频会话验证词库参数接受及正常收尾。真实视频的暂停恢复和术语效果仍需试听验收。

当前进度：Phase 0、Phase 1 已通过用户实际验证；Phase 2 已验证双语输出、连接重试、暂停约 10 分钟后恢复字幕和正常退出。30 分钟稳定性验收尚未完成。Phase 3 双语悬浮窗已实现，待播放视频验收。

## Phase 3：双语悬浮字幕窗

Chrome 播放视频后运行（默认使用悬浮窗）：

```powershell
.\.venv\Scripts\python.exe main.py
```

窗口位于屏幕下方，置顶、无边框、半透明白底黑字（背景约 78% 不透明）；上方为原文，下方为中文。正常连接时只显示原文和译文，隐藏标题、状态和操作说明；高度随字幕行数自动收紧。拖动背景移动窗口，拖动右下角调整宽度，点击右上角“×”后等待会话收尾。悬浮窗默认显示流式中间结果，每 100 ms 刷新一次，收到最终结果后替换，不再等待整段结束。临时文本可能随着识别和翻译修订；实际响应速度仍取决于服务端和网络。

```powershell
# 离线外观预览，不连接云端、不采集音频
.\.venv\Scripts\python.exe main.py --demo
# 让终端也打印流式中间结果（窗口默认已显示）
.\.venv\Scripts\python.exe main.py --partial
# 仅显示最终结果，适合偏好稳定文本的场景
.\.venv\Scripts\python.exe main.py --final-only
```

显示按服务端 item 关联配对，不按英中到达顺序拼接。关联尚未到达时显示单侧等待状态；每种语言显示最近三行，过长段落省略前文。重连时清空旧字幕，状态栏提示连接、重连或错误。默认源语言配置仍为 `en`，窗口统一标注“原文”，不把日语等识别结果误标为英语。

终端默认仍仅打印最终结果，因此 `[STATUS]` 的结果段数只统计最终文本；即使计数为 0，悬浮窗也可能已经在更新流式字幕。此前长时间无字幕的一个直接原因是窗口过滤了中间结果，本次已修正默认显示策略。

关闭时窗口会显示“正在结束会话”，收到会话收尾结果后退出；后台错误时窗口保留错误提示，点击退出可关闭。定时运行结束后保留最后字幕供查看，此时不会继续采集音频。点击穿透、全局快捷键和字号调节已实现（见上方日常设置）；透明度调节尚未添加。

请验证：播放有语音的视频后窗口出现原文与中文；切换到 Chrome 后字幕仍置顶；可拖动和调整窗口；点击退出正常收到 `session.finished`。若未出现字幕，请提供终端输出，以及窗口是否显示等待翻译或错误。

本机已验证窗口外观和真实网络退出流程。后台联调上传约 10 秒音频、收到 `session.finished`，未获得文本；模拟事件测试验证实际窗口收到正确的双语配对。因此真实视频上的字幕显示仍待用户验收。

Phase 1 用户验收：录满 10 秒，峰值 0.3062，RMS -33.2 dBFS，无不连续和时间戳异常，用户确认只有 Chrome 的声音。

## Phase 2：实时 Chrome 双语字幕

打开 Chrome 播放英文视频，在项目目录运行：

```powershell
.\.venv\Scripts\python.exe main.py --console
```

复用 `.env` 中已配置的百炼账号。运行后会将 Chrome 进程树的音频发送给百炼，并使用模型调用额度。默认显示最终 `[EN]` 和 `[ZH]`，空结果不打印；字幕只显示在终端，不保存。

```powershell
# 查看临时流式结果（输出会比较多）
.\.venv\Scripts\python.exe main.py --console --partial
# 30 分钟稳定性测试，完成后自动收尾
.\.venv\Scripts\python.exe main.py --console --seconds 1800
# 多个浏览器主进程时指定 PID
.\.venv\Scripts\python.exe main.py --console --pid 12345
```

每 30 秒输出 `[STATUS]`，含已发送音频时长、双语最终结果数和待发送队列时长。Ctrl+C 先停止捕获，发送队列中剩余音频，再发 `session.finish` 并等待 `session.finished`。

音频捕获与网络分属不同线程；每包 100 ms，队列最多 2 秒，运行期间不累计完整录音。网络断开、会话提前关闭或心跳超时会进入 `[RECONNECTING]`，按 1、2、4、8、15 秒（上限）重试；连接稳定超过 30 秒后重置重试间隔。每次重连重新发送会话配置，重新开始 Chrome 捕获，旧队列和断线期间的音频不补发，断点附近的字幕可能丢失。

已加入 WebSocket ping/pong：每隔 15 秒检查，未在 15 秒内收到 pong 则重连。心跳不是延长服务端会话时限的保证。鉴权、工作空间、参数错误以及 Chrome 退出等本地错误会停止，避免无效重试。网络速度不足导致队列溢出仍会停止并提示。

对于 `type=transcription_error`、`code=UNEXPECTED_ASR_ERROR` 且没有详细消息的云端错误，每次启动或手动切换后的翻译任务最多自动重建会话两次；保留声源、速度模式和热词。第三次仍出现该错误则停止并提示，避免持续重试。明确的鉴权错误及其他未知错误仍不自动重试。这是有限恢复策略，不能据此确定错误由速度模式或声源引起。

已针对云端 `COMMON_ERROR: model repeat output happened` 增加自动重连：出现模型重复输出错误时重新建立会话，沿用当前词库，并清空旧字幕。重连期间的音频不会补发。此修复恢复会话，不保证云端不再出现重复输出；其他未知 `COMMON_ERROR` 仍停止并提示。更新后需重启字幕程序。

已修复暂停视频后的 ASR 超时分类：用户实际收到 `UNEXPECTED_ASR_ERROR`，消息为 `statusCode=504, Response stream timeout (timeout_seconds=300)`。这类错误现在会重建会话并继续捕获，不再直接退出；WebSocket 心跳无法阻止 ASR 后端自身的超时。其他未知 ASR 错误仍保留停止行为。24 项测试已覆盖该实际错误经过接收、分类后触发重连，以及鉴权错误不重试；长时间暂停后恢复播放仍需真实验收。

`--seconds 1800` 的限时包含重连等待；建立连接、停止捕获与最终会话收尾可能稍微超过该时长。重试等待期间 Ctrl+C 可取消；正在进行的连接操作最多等待其连接超时。若退出时已断线，会明确提示最后一句可能不完整，不伪报 `session.finished`。

可选的恢复验收：运行时短暂断开网络再恢复，预期先出现 `[RECONNECTING]`，随后 `[CONNECTED]`，恢复播放英文后继续出现字幕。长时间暂停视频后恢复播放，也应继续工作；若服务端主动关闭连接，程序会重连。终端会显示关闭状态码和原因（若服务端提供），运行统计记录断线和重连次数。

退出后生成 `logs/phase2_last_run.json`（覆盖上一次统计），仅保存运行时长、音频秒数、结果计数、队列峰值、丢帧统计、连接/重连次数和退出状态，不含密钥、字幕或录音。出现问题时可发送终端错误和此统计文件。

Phase 2 验收：播放英文内容时同时获得英中最终字幕；正常退出收到 `session.finished`；连续运行至少 30 分钟没有异常，发送队列未持续堆积，无音频不连续。短时测试不能代替 30 分钟验收。

当前验证记录：15 项离线测试通过；真实百炼会话发送 15 秒 Chrome 音频并收到 `session.finished`，退出码 0。本次未返回英中最终文本，仍需用户播放清晰英文完成字幕验证及 30 分钟稳定性测试。

重连更新验证：22 项测试通过；30 秒真实百炼联调中主动关闭测试 WebSocket 一次，1 秒后重连成功，累计发送 28.04 秒新音频，最后收到 `session.finished`，退出码 0。测试期间未返回字幕，因此这次验证证明连接恢复与音频继续发送，字幕恢复仍需播放英文验证。此前用户已验证 Chrome 双语输出 107 段，长时间静音断线的具体原因尚未确定。

## Phase 1：只录制 Chrome

```powershell
cd D:\project\pytnon\real_time_translation
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\audio_debug.py --list
.\.venv\Scripts\python.exe tools\audio_debug.py
```

默认录制 10 秒，生成项目目录下的 `debug_capture.wav`，格式是 PCM16 / 16000 Hz / 单声道。已有文件时自动添加时间后缀，以终端输出路径为准。本阶段只保存本地录音，不读取 Key、不连接百炼。

验收步骤：

1. Chrome 播放一段有清晰人声的视频。
2. 另一个程序（如播放器）同时播放容易区分的音乐。
3. 运行 `audio_debug.py`，保持两边播放直到录制结束。
4. 暂停两边播放，打开生成的 WAV 试听：应只有 Chrome 的声音。
5. 再暂停 Chrome，只让另一个程序播放，重新录制：应得到静音 WAV。

可指定时长、文件或 Chrome PID：

```powershell
.\.venv\Scripts\python.exe tools\audio_debug.py --seconds 10 --output chrome_test.wav
.\.venv\Scripts\python.exe tools\audio_debug.py --pid 12345
```

`--pid` 必须是 `--list` 中当前存在的 Chrome PID；默认选择无 `--type` 参数的浏览器主进程。若有多个主进程，工具会要求指定 PID。多个标签页共享进程树时都会被录入。手动指定子进程仅用于排查，可能漏掉其他 Chrome 音频。

技术实现：纯 Python `ctypes` → `ActivateAudioInterfaceAsync` → `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`。初始化时请求 16 kHz / 单声道 / PCM16，使用 WASAPI 的 `AUTOCONVERTPCM` 和 `SRC_DEFAULT_QUALITY` 标志完成格式转换与重采样；转换状态由 Windows 音频引擎维护。`audio_converter.py` 校验输出格式并计算音量，避免把不匹配的数据写成目标格式。无需 NumPy/SciPy，没有系统回环或麦克风回退。

Windows 最低 build 为 20348（本机 26200），依据 [Microsoft 接口说明](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params)。实现参考 [Microsoft ApplicationLoopback 示例](https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/ApplicationLoopback)。

遇到问题请提供：终端 `[INFO]` / `[WARN]` / `[ERROR]`、Chrome PID 列表、WAV 是否有声音，以及其他程序声音是否混入。HRESULT 保留在错误信息中方便定位。不连续计数非零意味着可能丢帧，应重新验证。静音文件只说明没捕获到信号，不能单独证明隔离成功。Ctrl+C 会保存已捕获部分；Chrome 退出则报告失败。

---

## Phase 0：麦克风双语测试（已通过）

本阶段：麦克风 → 百炼 WebSocket → 终端英文原文与中文翻译。
正式运行脚本会向百炼发送麦克风音频，并使用账号的模型调用额度。

麦克风使用 `sounddevice`。本机 Python 3.14 安装 PyAudio 时因缺少 `portaudio.h` 失败，因此采用带 Windows PortAudio 二进制依赖的替代库，音频格式不变。

## 1. 准备环境

在 PowerShell 中进入项目目录。建议 Python 3.11 x64；也可使用本机已安装的 Python，是否兼容以依赖安装和设备测试为准。

```powershell
cd D:\project\pytnon\real_time_translation
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果虚拟环境已经创建且依赖安装成功，跳过以上两条安装命令。
这里直接调用虚拟环境解释器，无需激活，也无需修改 PowerShell 执行策略。

## 2. 配置百炼

首次运行时复制配置（已有 `.env` 时不要覆盖）：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

在本机填入：

- `DASHSCOPE_API_KEY`：API Key。
- `DASHSCOPE_WORKSPACE_ID`：北京地域 Workspace ID。
- `DASHSCOPE_WS_HOST`：可留空，自动使用 Workspace ID 构造北京域名；若填写，优先使用此主机名，不包含 `wss://` 或路径。

API Key 与工作空间需匹配，且账号需具备模型调用权限。环境变量优先于 `.env`。
不要将密钥发到聊天或提交到 Git。`.env` 已配置为忽略。

```powershell
.\.venv\Scripts\python.exe tools\api_debug.py --check-config
```

预期看到 `[OK] 配置格式正确`。这只是离线格式检查，不代表云端鉴权通过。

## 3. 选择麦克风并测试

```powershell
.\.venv\Scripts\python.exe tools\api_debug.py --list-devices
.\.venv\Scripts\python.exe tools\api_debug.py
```

默认使用系统默认麦克风。如果需要指定设备，把 `3` 换成列表中的输入设备编号：

```powershell
.\.venv\Scripts\python.exe tools\api_debug.py --device 3
```

出现“已开始上传麦克风音频”后，说：

> We played well today, but the second map was difficult.

等待几秒，应看到以下形式的结果（译文和顺序可能不同）：

```text
[EN partial] We played well today
[ZH partial] 我们今天打得很好
[EN] We played well today, but the second map was difficult.
[ZH] 我们今天打得很好，但第二张地图很难打。
```

`partial` 每行是一次服务端事件的确认片段与预测文本，仅用于查看流式输出；不可把所有 partial 行拼成完整句子。最终以 `[EN]` 和 `[ZH]` 为准，本阶段不做字幕配对。

按一次 `Ctrl+C`，等待最后一句输出及 `[INFO] session.finished` 后退出。网络断开或等待超过 20 秒时会报告失败并释放资源，此时最后一句可能丢失。

## 4. 验收与故障反馈

Phase 0 通过条件：同一句英文有原文和中文最终结果，Ctrl+C 能正常收到 `session.finished`。完成实际验证后再开展 Chrome 音频捕获。

若失败，请提供下面的信息：

- 执行的命令、Python 版本、从 `[INFO]` 到 `[ERROR]` 的终端输出。
- 若为设备错误，提供 `--list-devices` 的输出及所选编号。
- 是否出现 `session.finished`，是否只有英文或只有中文。

不要提供 `.env` 或 API Key。程序不保存录音、字幕或日志文件；诊断信息显示在终端，异常文本会遮盖当前 Key。
麦克风打开失败时，检查 Windows 麦克风权限和设备是否支持 16 kHz 单声道；脚本不会自动改用系统回环设备。

## 离线测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

这些测试不连接百炼，不录制音频，不能替代真实云端验收。

## 接口依据

2026-09-07 核对的官方文档：

- [模型与连接地址](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime)
- [客户端事件](https://help.aliyun.com/zh/model-studio/live-translator-client-events)
- [服务端事件](https://help.aliyun.com/zh/model-studio/live-translator-server-events)

固定模型 `qwen3.5-livetranslate-flash-realtime`，英文 ASR 为 `qwen3-asr-flash-realtime`，只输出文本，使用服务端 VAD；音频为 16 kHz / mono / PCM16，每包 100 ms。
