# CS2 Customizer

**给 CS2 玩家的本地个性化工具**：自定义准心、击杀音效与图标、HUD 配色、局内视角、道具瞄点——
全部通过 Valve 官方的 GSI 接口读游戏状态、通过 cfg 文件写游戏设置，不碰游戏进程一根手指。

[![CI](https://github.com/gufan0000/cs2-customizer/actions/workflows/ci.yml/badge.svg)](https://github.com/gufan0000/cs2-customizer/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)](#安装与运行)

本项目由同一作者的闭源商业软件「帆派助手 / FanTool」裁出，是它的**功能子集**：
去掉了账号、云同步、更新检查与音乐平台抓流，保留全部本地功能。两者相互独立，
装在同一台机器上互不干扰（各自的安装目录、数据目录与开机自启项都是分开的）。

---

## 它是什么 / 它不是什么 · What it is, what it is not

> 这一段放在最前面，因为它比功能列表更重要。
> This section comes first because it matters more than the feature list.

**中文**

- ✅ 只做两件事：通过 **Valve 官方的 Game State Integration (GSI)** 接口**只读**游戏状态
  （回合阶段、击杀事件、存活/血量、当前武器、地图等），以及**读写 CS2 的 cfg 配置文件**。
  这两条路径都是 Valve 公开提供、面向第三方工具设计的。
- ❌ **不读写游戏内存，不注入进程，不 hook 任何 API，不修改任何游戏文件**
  （只在 `game/csgo/cfg/` 下写入 GSI 配置与本工具生成的 cfg，这是官方约定的配置目录）。
- ❌ **不提供任何竞技优势**。准心是画在游戏窗口之上的**独立叠加层**，音效是本地播放，
  HUD 配色和视角是通过官方 cfg 变量设置的——它们改变的只是**你自己屏幕上的表现**，
  不会给你额外信息、不会替你瞄准、不会改变任何游戏内数值。
  开镜放大基于 Windows 系统自带的 Magnification API 放大**桌面画面**，与游戏无关。
- ⚠️ 本项目与 **Valve Corporation 无任何关联，未获其授权或背书**。
  Counter-Strike、CS2、Valve 是 Valve Corporation 的商标，本项目仅作**描述性使用**
  （nominative fair use），用于说明本工具适用于哪款游戏。

**English**

- ✅ This tool does exactly two things: it **reads** game state through Valve's official
  **Game State Integration (GSI)** endpoint, and it **reads/writes CS2 `.cfg` files**.
  Both are public, documented integration points that Valve provides for third-party tools.
- ❌ It does **not** read or write game memory, does **not** inject into the game process,
  does **not** hook any API, and does **not** modify any game file.
- ❌ It grants **no competitive advantage**. Crosshairs are drawn in a separate overlay window,
  sounds play locally, HUD colors and viewmodel are set via official cfg variables.
  Nothing here reveals information you would not otherwise have, aims for you,
  or alters any in-game value.
- ⚠️ This project is **not affiliated with, authorized by, or endorsed by Valve Corporation**.
  Counter-Strike and CS2 are trademarks of Valve Corporation; they are used here
  descriptively (nominative fair use) only to identify the game this tool works with.

GSI 在完全默认的官方游戏环境下就能工作：**不需要修改任何游戏启动参数**，
也不需要改动游戏本体的任何文件。安装后照常打开游戏即可。

---

## 功能亮点

### 准心

- 自定义样式（十字 / 点 / 圆 / T 形 / 自定义图片）、颜色、粗细、间隙、偏移
- 用 **Qt 独立叠加层**渲染，开关是毫秒级的，不改游戏任何设置
- 击杀时可触发准心动画；静止时降到 1 FPS 重绘，动画时才升到 24 FPS
- 也能把准心参数**同步写进 cfg**，让游戏原生准心跟着走

### 音效与语音

- **击杀音效 / 击杀语音**：按 1–5 连杀分档，可按武器分类使用不同音效
- **被击杀音效**、**回合胜负 / MVP 音效**、**血量警告**、**C4**、**投掷物**音效
- **枪声替换**：AWP、沙鹰等武器的枪声换成你自己的音频（Windows 进程级音量压制实现）
- **切枪 / 换弹音效**
- **语音输出**：5 槽位音板 + 音效转发，让队友也能听见（需 VB-Cable 虚拟声卡）
- 「一步式新建风格」向导：拖入一堆任意命名的音频，自动归档成一套可用的音效风格

### 画面与视角

- **击杀图标**：1–5 连杀各自的动画序列，位置可调
- **自定闪光**：被闪时用你自己的图片/纯色/渐变替代白屏，可配音频与淡入淡出
- **HUD 配色**：按队伍、血量等条件切换 HUD 颜色
- **屏幕特效**
- **局内视角 (viewmodel)**：FOV 与 X/Y/Z 偏移，5 组预设快捷键
- **开镜放大**：基于 Windows Magnification API，主/副武器可设不同倍率

### 音乐播放器（仅本地文件）

- 播放本机音频文件，支持播放列表、进度拖动、全局控制栏
- 与 GSI 联动：进局存活时自动降低音量，阵亡后恢复
- ⚠️ **开源版不含任何在线音乐平台的解析或下载能力**，只播放你自己电脑上的文件

### 道具瞄点

- 按地图/队伍展示投掷点位的图片引导，快捷键快速呼出
- 点位素材需自备（见 [素材说明](#素材说明)）

### 配置管理

- **预设中心**：整套配置打包成预设，支持按地图自动切换
- **配置快照**：改坏了能回滚；自动快照不会挤掉你手动存的那些
- **资源体检**：告诉你「为什么这个音效不响」——缺哪个文件、配置指向了哪个不存在的风格
- **设置搜索**（`Ctrl+F`）：支持拼音（`zx` / `zhunxin`）、错字容错（`dukcing`）、
  口语（`声音太大`、`鼠标速度`）；不只跳到页面，直接高亮到具体那一行开关

### 界面

- 9 套主题、3 档字号缩放（1.0 / 1.1 / 1.25）、完整 / 紧凑两种窗口形态
- 侧栏「常用」分组按你的实际使用频次自动排

---

## 界面预览

> 📷 **截图与录屏尚未补齐**，这一节暂时只有文字说明。
> 不放占位图片是有意的——指向不存在文件的 `![]()` 只会在首页渲染成三个破图标，
> 比没有图更糟。补齐后这段会换成真实画面。

欢迎 PR 补充到 `docs/images/`，建议录这三段（各 5–8 秒，GIF 或 WebM）：

1. **准心跟随** —— 切到准心页改样式/颜色/粗细，叠加层实时跟着变；再切窗口/切分辨率，
   证明它稳稳贴在游戏画面上。
2. **击杀音效触发** —— 用 `scripts/gsi_live_sim.py` 或真实对局打出一次连杀，
   同时展示音效播放 + 击杀图标动画 + 准心动画。
3. **搜索定位高亮** —— 按 `Ctrl+F` 输入 `zx` 或 `声音太大`，展示下拉结果，
   回车后自动切页并高亮到具体那一行开关。

---

## 安装与运行

**环境要求**

- Windows 10 / 11
- Python 3.13
- CS2（首次启动时会引导你指定游戏安装目录）

**从源码运行**

```bash
git clone https://github.com/gufan0000/cs2-customizer.git
cd cs2-customizer
pip install -r requirements_qt.txt
python main_widget.py
```

首次启动会有一个三步引导：选择 CS2 目录 → 写入 GSI 配置 → 开启你想用的功能。

**GSI 是怎么接上的**

程序会在 `CS2/game/csgo/cfg/gamestate_integration_cs2customizer.cfg` 生成 GSI 配置文件，
游戏启动后会主动把状态 POST 到本机的 `http://127.0.0.1:3000`（端口被占用时自动改用 3001–3010）。
如果防火墙弹窗，允许本地回环访问即可。**不需要任何游戏启动参数。**

**权限**

默认以普通权限运行，日常使用不会弹 UAC。只有开镜放大在某些环境下初始化失败时，
才需要在「高级设置 → 运行权限」里一键以管理员身份重启。

**可选依赖**

- `pycaw` / `comtypes`：枪声替换、被击杀音效的运行时音量压制（Windows）
- `sounddevice` / `soundfile`：语音输出（需另行安装 [VB-Cable](https://vb-audio.com/Cable/) 虚拟声卡）

---

## 素材说明

**本仓库不包含任何音效、图标、图片素材。** 原闭源版内置的素材来自第三方（游戏厂商、
影视、社区作品等），版权不属于本项目，因此一律不随仓库分发。

程序在**完全没有素材的情况下也能正常启动和运行**——所有素材目录会在首次启动时自动建好，
只是各个音效/图标列表是空的。你需要自己准备素材，然后用软件内的
**「工具与系统 → 资源导入向导」**导入（支持整个文件夹拖入，会自动识别归档）。

### 目录结构

素材统一放在 `%LOCALAPPDATA%\CS2Customizer\resources\` 下。导入向导识别的是**目录名**，
所以你准备素材时按下面的结构组织，拖进来就能被自动归位：

```
resources/
├── audio/
│   ├── kill_sounds/<风格名>/1.mp3 ... 5.mp3      # 击杀音效，按连杀数分档
│   ├── kill_voices/<风格名>/1.mp3 ... 5.mp3      # 击杀语音
│   ├── weapon_kill_sounds/<武器>/<风格名>/       # 按武器区分的击杀音效
│   ├── weapon_kill_voices/<武器>/<风格名>/
│   ├── death/<风格名>/                           # 被击杀音效
│   ├── switch_weapons/<武器>/<风格名>/           # 切枪音效
│   ├── reload_sounds/<风格名>/                   # 换弹音效
│   ├── grenade_sounds/<风格名>/                  # 投掷物音效
│   ├── c4_sounds/<风格名>/                       # C4 音效
│   ├── health_warning/<风格名>/                  # 血量警告
│   ├── round_sounds/<风格名>/                    # 回合开始 / 胜负 / MVP
│   └── gun_sounds/<武器>/<风格名>/               # 枪声替换
├── kill_icons/<风格名>/                          # 击杀图标（可含 .json 描述动画）
├── flash_images/                                 # 自定闪光图片
├── flash_audio/                                  # 自定闪光音频
├── utility_guides/<地图>/                        # 道具瞄点图
└── crosshair/                                    # 准心文件
```

### 支持格式

| 类别 | 格式 |
| --- | --- |
| 音频 | `.mp3` `.wav` `.ogg` |
| 图片（闪光 / 道具瞄点） | `.png` `.jpg` `.jpeg` `.bmp` `.webp` |
| 击杀图标 | 上述图片格式 + `.json`（动画描述） |
| 准心文件 | `.xchr` `.json` |

导入后可以用**「音频体检」**页检查完整性——它会明确告诉你哪个风格缺了第几连杀的文件，
而不是让你对着一个不响的音效干瞪眼。

> **请只导入你有权使用的素材。** 把第三方版权素材打包再分发，责任在分发者。

---

## 构建发布包

```bash
pip install -r requirements_qt.txt -r requirements-build.txt
python build_tools/build_release.py --mode onedir --no-obfuscate --without-bundled-assets
```

几个开关的含义：

- `--without-bundled-assets`：**开源版构建必须加**。构建链路默认会断言产物里带着素材
  （闭源版的前提），不加这个开关，产物校验会直接把构建拦下来。
- `--no-obfuscate`：跳过 PyArmor 混淆。混淆需要 PyArmor 授权，且对开源版没有意义。
- `--mode onedir`：冷启动明显快于 `onefile`（约 5.9s → 1.9s）。
- `--upx`：默认关闭。UPX 加壳是杀软/SmartScreen 误报的主要来源之一。

Windows 安装包用 [Inno Setup](https://jrsoftware.org/isinfo.php) 编译 `build_tools/installer.iss`。

---

## 项目结构

```
main_widget.py          入口：崩溃钩子 / 单实例 / 分阶段启动
gui_widget.py           主窗口：侧栏导航、页面懒加载、主题与搜索
config.py               配置模型与持久化（%LOCALAPPDATA%\CS2Customizer\config.json）
gsi_server.py           GSI 接收端（Flask），gsi_handler_*.py 为各领域处理器
core/                   领域逻辑：audio / gsi / hud / presets / hotkeys / net / backup ...
pages/                  功能页面，一页一文件（侧栏共 26 项）
widgets/                跨页复用的 UI 组件（SettingsCard、SearchPopup 等）
dialogs/                向导与弹窗
crosshair_overlay.py    准心叠加层（Qt 渲染）
flash_process*.py       自定闪光（独立子进程，避免拖累主窗口）
resource_manager.py     素材目录与迁移
build_tools/            打包、安装包、测试驱动
scripts/                审计与验证脚本（不进发布包）
tests/                  单元与集成测试
```

页面是**懒加载**的：首次进入才构建，启动时只走关键路径。

---

## 开发与测试

**测试必须逐文件跑。** pygame / Qt 等原生库在同一进程里跑完全部测试文件会原生崩溃，
所以测试驱动用子进程逐文件隔离：

```bash
python build_tools/run_tests.py            # 全量（约 45 秒）
python build_tools/run_tests.py config hud # 只跑文件名含关键词的
```

**Lint**

```bash
ruff check .
```

规则见 `ruff.toml`。豁免项都写了理由，加新豁免请一并写清楚为什么。

**判据回退验证台**

```bash
python scripts/revert_verify.py            # 全跑
python scripts/revert_verify.py --only R10
```

它会逐条把产品代码**改坏**，确认对应的测试**真的会变红**，跑完自动还原。
存在的理由是：一条「不该绿却绿了」的判据比没有判据更危险——它让人以为这块有人看着。
里面每个断点都对应一个真实发生过的缺陷，请不要编造断点。

**UI 审计**

改了布局之后，排版审计**完整模式和紧凑模式两档都要跑**（紧凑模式是另一套外壳，
不是「再跑一个尺寸」）：

```bash
python scripts/layout_overflow_audit.py --themes dark,light --scales 1.0,1.1,1.25 --require-fonts
python scripts/layout_overflow_audit.py --compact --themes dark,light --scales 1.0,1.1,1.25 --require-fonts
python scripts/ui_contrast_audit.py
python scripts/tab_order_audit.py --verbose
```

**改了设置项文案要重建搜索索引**

设置搜索靠离线生成的索引工作。改了页面控件文案或卡片标题之后：

```bash
python scripts/build_search_index.py
```

**GSI 相关的改动怎么验**

不用真开游戏：`scripts/gsi_live_sim.py` / `gsi_full_sim.py` 可以回放/构造 GSI 数据包。
注意一个经典陷阱：**观战队友时 GSI 里的 player 是被观战者**，
所有涉及「我」的统计都必须按本人 SteamID 过滤。

CI（GitHub Actions，`windows-latest` + Python 3.13）会跑 ruff、全量测试矩阵和上面这四项 UI 审计。

---

## 贡献

欢迎 issue 和 PR。提 PR 前请读 [CONTRIBUTING.md](CONTRIBUTING.md)。

> ⚠️ **提 PR 需要先接受 [CLA.md](CLA.md)。** 你保留自己贡献的著作权，
> 但要授权维护者可以**以任何许可证再许可**你的贡献——包括用在闭源商业版本里，
> 且你不会因此获得报酬。这一条放在这里是为了让你在动手之前就看见，而不是 PR 写完才发现。
>
> 不接受是完全合理的选择：**开 issue、报缺陷、提文档反馈、fork 自己维护，都不需要 CLA。**

两条最容易踩的线先说在这里：

- **不要提交任何第三方素材**（音频、图标、游戏截图）。仓库有测试专门守这条
  （`tests/test_no_bundled_assets.py`），提交素材会让 CI 直接变红。
- **不要引入任何越过「只读 GSI + 读写 cfg」边界的能力**。内存读写、进程注入、
  API hook、任何形式的自动瞄准或信息优势，一律不接受，无论实现得多干净。

---

## 许可证

本项目采用 **[GNU General Public License v3.0](LICENSE)**。

这意味着你可以自由地使用、修改和分发本软件，**包括商业用途**；
但基于本项目的衍生作品必须同样以 GPL-3.0 开源，并保留原始版权声明。

**商标保留**：「 CS2 Customizer 」以及本项目前身的「帆派」「帆派助手」「FanTool」等名称、
标识与程序图标，是原作者保留的标识，**不在** GPL-3.0 的授权范围内（GPL 授权的是代码，
不是商标）。你可以 fork 本项目、可以商用，但请**用你自己的名字和图标发布**，
不要让使用者误以为你的版本来自原作者或与之有关联。详见 [NOTICE](NOTICE)。

**贡献者许可**：合并进来的外部贡献适用 [CLA.md](CLA.md)——贡献者保留著作权，
并授予维护者可再许可的权利，使同一份代码既能在本项目以 GPL-3.0 发布，
也能用在维护者的闭源商业版本中。这是**双许可**的常见做法，条款在提 PR 前就公开可读。

Counter-Strike、CS2 和 Valve 是 Valve Corporation 的商标。本项目与 Valve 无关。

---

## 致谢与相关项目

- [PySide6 / Qt](https://doc.qt.io/qtforpython/) —— 整个界面与准心渲染的地基
- [pygame](https://www.pygame.org/) —— 音频播放
- [Flask](https://flask.palletsprojects.com/) —— GSI 接收端
- [qtawesome](https://github.com/spyder-ide/qtawesome) —— 矢量图标
- [pypinyin](https://github.com/mozillazg/python-pinyin) —— 设置搜索的拼音层
- [Valve Developer Community — Counter-Strike: Global Offensive Game State Integration](https://developer.valvesoftware.com/wiki/Counter-Strike:_Global_Offensive_Game_State_Integration)
  —— GSI 的官方文档，本项目全部游戏状态都来自这里
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) —— 语音输出功能依赖的虚拟声卡

版本演进见 [CHANGELOG.md](CHANGELOG.md)。
