# CS2 Customizer 后台静默自查覆盖矩阵 v1

## 1. 文档定位

本文档用于回答一个很实际的问题：

- 本次改了某个页面或某一类模块，我后台静默自查时到底要重点看什么？

这份矩阵不是总规范，也不是执行模板，而是“覆盖地图”。

配套文档：

- [CS2Customizer_后台静默自查索引_v1.md](./CS2Customizer_后台静默自查索引_v1.md)
- [CS2Customizer_后台静默自查规范_v1.md](./CS2Customizer_后台静默自查规范_v1.md)
- [CS2Customizer_后台静默自查执行模板_v1.md](./CS2Customizer_后台静默自查执行模板_v1.md)

---

## 2. 使用方式

每次开始检查前，先做两件事：

1. 找到本次直接改动页
2. 再找共享组件可能波及的关联页

然后按本矩阵执行：

- 看“重点检查”
- 跑“优先测试”
- 抓“推荐截图”

---

## 3. 覆盖等级说明

### A 级

- 高频页面
- 视觉和交互要求高
- 改动后建议必做交互检查和离屏截图

### B 级

- 中频页面
- 主要依赖专项测试和必要截图

### C 级

- 低频工具页
- 重点防止空白、错字、按钮失效、状态不同步

---

## 4. 全局与公共区域

| 模块 | 等级 | 重点检查 | 优先测试 | 推荐截图 |
|---|---|---|---|---|
| 主框架 `gui_widget.py` / 基础首页 | A | 导航、主题切换、系统状态、功能总开关、首页状态块 | 相关首页 / 状态测试 | 首页默认、首页窄宽度 |
| 帮助面板 `ui_help_panel.py` | A | 问号按钮、面板展开、文案滚动、关闭按钮、路径说明正确性 | `test_ui_help_panel_texts.py`、`test_ui_form_and_help_interactions.py` | 任意 2 个页面的帮助展开图 |
| 状态徽章 `audio_status_badge.py` | A | badge 数量、文案、颜色层级、tooltip | `test_audio_status_badge.py`、页面总套件 | 关键页状态卡 |
| action bar | A | 主次按钮可见性、文案、状态同步 | `test_tool_pages_ui_polish.py` | 关键页底部操作栏 |

---

## 5. 账户与系统信息类

| 页面 | 等级 | 重点检查 | 优先测试 | 推荐截图 |
|---|---|---|---|---|
| `advanced_page.py` | A | CS2 目录、调试密码输入、主题下拉、备份 / 重置按钮、帮助说明 | `test_advanced_page_ui_polish.py`、`test_ui_form_and_help_interactions.py` | 默认页、帮助展开页 |
| `about_page.py` | B | 软件信息、链接、版本文案、说明排版 | 相关 about 测试 | 默认页 |
| `audio_health_page.py` | B | 状态 badge、诊断摘要、报告文本、修复按钮状态 | 页面总套件 | 默认页 |
| `config_snapshot_page.py` | B | 快照列表、选中态、状态条、操作按钮 | 页面总套件 | 默认页 |
| `preset_center_page.py` | B | 预设卡、脏状态、按钮可用性 | 页面总套件 | 默认页、窄宽度 |
| `audio_replay_page.py` | C | 筛选区、列表、状态摘要、空态 | 页面总套件 | 默认页 |
| `audio_import_wizard_page.py` | C | 导入识别、状态条、步骤切换 | 页面总套件 | 默认页 |
| `audio_task_panel_page.py` | C | 任务状态、列表空态、运行态摘要 | 页面总套件 | 默认页 |

---

## 6. 视觉与覆盖类

| 页面 | 等级 | 重点检查 | 优先测试 | 推荐截图 |
|---|---|---|---|---|
| `crosshair_page.py` | A | 样式单选、颜色单选、动画下拉、击杀联动下拉、自定义准心导入导出说明 | `test_crosshair_page_ui_polish.py`、`test_ui_form_and_help_interactions.py`、页面总套件 | 默认页、帮助展开页、窄宽度 |
| `magnifier_page.py` | A | 灵敏度输入、倍率下拉、热键下拉、偏移输入、武器列表、帮助说明；静默前必须断开真实 CFG 写出 | `test_magnifier_page.py`、`test_ui_form_and_help_interactions.py`、页面总套件 | 默认页、帮助展开页、窄宽度 |
| `hud_color_page.py` | A | 规则分区、保存逻辑、静态 / 动态规则说明、状态条、帮助说明；静默前必须断开真实 CFG 写出 | 页面总套件、相关 HUD 测试 | 默认页、帮助展开页 |
| `screen_effects_page.py` | B | 预设切换、模式切换、状态块、紧凑布局 | 页面总套件 | 默认页、窄宽度 |
| `flash_page.py` | A | 基础设置双卡、样式 / 图片 / 音频 / 预览切页、背景颜色、透明度、帮助说明 | 页面总套件、`test_ui_form_and_help_interactions.py` | `1440`、`980`、帮助展开页 |
| `utility_page.py` | A | 快捷键、显示模式、位置输入、时长输入、空态、管理页、帮助说明 | 页面总套件、`test_ui_form_and_help_interactions.py` | 默认页、帮助展开页、空态页 |
| `viewmodel_page.py` | A | CFG 保存说明、预设切换、快捷键、准心回正、状态条；静默前必须断开真实 CFG 写出 | 页面总套件、CFG 相关测试 | 默认页、帮助展开页 |
| `fun_page.py` | B | 平台下拉（抖音 / 自定义）、自定义时网址与手机模式的显隐联动、模式白名单勾选、贴边与高度、状态文案；静默前必须断开真实浏览器启动 | `test_fun_page.py`、页面总套件 | 默认页、选中自定义网址、窄宽度 |

---

## 7. 音频与游戏事件类

| 页面 | 等级 | 重点检查 | 优先测试 | 推荐截图 |
|---|---|---|---|---|
| `kill_sound_page.py` | A | 分类切换、风格下拉、测试按钮、资源路径说明、刷新列表保持选择 | 页面总套件、相关 UI smoke | 默认页、分类切换页 |
| `kill_voice_page.py` | A | 分类切换、风格下拉、测试按钮、通用 / 武器专属语音说明 | 页面总套件、相关 UI smoke | 默认页、帮助展开页 |
| `gun_sound_page.py` | A | 风格下拉、duck 比例、静音时长、武器分组、帮助说明 | 页面总套件、音频策略测试 | 默认页、窄宽度 |
| `death_sound_page.py` | B | 风格列表、扁平文件名说明、刷新后保留选择 | 页面总套件 | 默认页、帮助展开页 |
| `reload_sound_page.py` | B | 武器页切换、风格目录说明、测试按钮 | 页面总套件 | 默认页 |
| `switch_weapon_page.py` | B | 武器页切换、风格目录说明、测试按钮 | 页面总套件 | 默认页 |
| `special_sound_page.py` | A | 投掷物 / C4 / 低血量 / 回合四组结构、阈值、音量、帮助路径说明 | 页面总套件 | 默认页、阈值页、帮助展开页 |
| `kill_icon_page.py` | A | 风格选择、预览、FPS、位置偏移、响应式双列布局、帮助说明 | 页面总套件 | `1500`、`980`、帮助展开页 |

---

## 8. 媒体与输出类

| 页面 | 等级 | 重点检查 | 优先测试 | 推荐截图 |
|---|---|---|---|---|
| `music_page.py` | A | 联动策略、播放模式、播放列表、按钮栏、帮助说明、窄宽度不裁切 | `test_about_music_ui_polish.py`、`test_music_page_toolbar_state.py`、`test_ui_form_and_help_interactions.py`、页面总套件 | 默认页、帮助展开页、窄宽度 |
| `voice_output_page.py` | A | 驱动状态、模式下拉、麦克风下拉、PTT、音板槽位、音效转发、帮助说明 | `test_ui_form_and_help_interactions.py`、页面总套件 | 默认页、帮助展开页、音板页 |

---

## 9. 页面修改时的最小覆盖建议

## 9.1 A 级页面

至少执行：

- 相关静态检查
- 交互测试
- 页面总套件相关专项
- `1440 / 980` 两档截图
- 帮助展开截图

## 9.2 B 级页面

至少执行：

- 相关静态检查
- 至少 1 组交互
- 页面总套件相关专项
- 默认页截图

## 9.3 C 级页面

至少执行：

- 静态检查
- 关键按钮 / 列表 / 空态检查
- 默认页截图

---

## 10. 共享组件改动时的加严规则

如果本次改的是共享组件，而不是单页：

### 10.1 改帮助面板

至少抽查：

- `advanced`
- `flash`
- `music`
- `voice_output`
- `utility`

### 10.2 改状态条 / badge

至少抽查：

- `audio_health`
- `kill_sound`
- `special_sound`
- `music`
- `voice_output`

### 10.3 改 action bar

至少抽查：

- `advanced`
- `crosshair`
- `flash`
- `music`
- `voice_output`

### 10.4 改公共布局 / 主题

至少抽查：

- 1 个表单密集页
- 1 个双列卡片页
- 1 个音频配置页
- 1 个说明文案较长页
- 1 个窄宽度高风险页

---

## 11. 现有自动化覆盖备注

截至当前版本，仓库里已经明确覆盖到的关键静默检查资产包括：

- [tests/test_ui_help_panel_texts.py](../tests/test_ui_help_panel_texts.py)
- [tests/test_ui_form_and_help_interactions.py](../tests/test_ui_form_and_help_interactions.py)
- [tests/test_tool_pages_ui_polish.py](../tests/test_tool_pages_ui_polish.py)
- [tests/test_advanced_page_ui_polish.py](../tests/test_advanced_page_ui_polish.py)
- [tests/test_crosshair_page_ui_polish.py](../tests/test_crosshair_page_ui_polish.py)
- [tests/test_magnifier_page.py](../tests/test_magnifier_page.py)
- [tests/test_about_music_ui_polish.py](../tests/test_about_music_ui_polish.py)
- [tests/test_music_page_toolbar_state.py](../tests/test_music_page_toolbar_state.py)

这意味着：

- 这套静默自查已经不只是文档要求
- 它已经有一部分真实仓库资产作为支撑
- 后续我执行检查时，应该优先复用这些现成能力，而不是每次临时想办法

---

## 12. 最终定义

以后我做后台静默自查时，会先用这份覆盖矩阵确定：

- 这次必须查哪些页
- 每页重点看什么
- 哪些测试优先跑
- 哪些截图必须抓

如果没有按这份矩阵覆盖到足够的页面和风险点，就不应向你汇报“这轮已经完整检查过了”。
