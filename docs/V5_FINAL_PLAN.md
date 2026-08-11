# 帆派助手 UI v5 最终方案 — 架构清理 + 视觉重做

> **基线**: v4 master commit `b51424a` (2026-05-07)
> **备份**: 仓库外的本地备份目录 `<备份目录>/v4_20260507/` (181MB tar.gz + 146MB git bundle)
> **目标**: 美学 3.7 → **4.5+**,且**让任何后续 UI 改动一改穿透全 UI**
> **硬约束**: 不引入新 bug、不缺失任何现有功能、不破坏 322 个测试
> **总工时**: 11.5 工作日,分 10 个 Phase 提交

---

## 一、项目实际状况(诊断)

### 1.1 项目规模(数据驱动)

| 维度 | 数值 |
|------|------|
| 根目录 .py 文件 | 59 个 |
| 总代码行(主要文件) | ~28000 行 |
| 页面数 | 27 个(分布在 pages/ 27 个 .py) |
| 单页平均行数 | 707 行(最大 magnifier 1893,最小 audio_status_badge 185) |
| widgets/ 复用组件 | 5 个(490 行) |
| dialogs/ 弹窗 | 2 个 |
| core/ 业务模块 | 30+ 子模块,分 audio/config/gsi/hud/runtime/presets/backup/utils |
| **测试** | **322 个(56 个 test 文件)** |
| 7 套主题 | 深色/浅色 + forest/violet/desert/midnight/cherry/ocean/print |
| Qt 框架 | PySide6 6.10.2(最新) |
| Python | 3.13.12 |
| 已发布 EXE | 2.0.1 / 2.1.0 / 2.1.1 |
| 打包流程 | PyInstaller + 可选 PyArmor 混淆 |
| gui_widget.py | 2716 行(单文件,主窗口 + basic 页 + 部分逻辑) |
| theme_manager.py | 1832 行(7 套主题 + QSS 生成器) |

### 1.2 v4 的真正问题(根因诊断)

**这是这次勘察最关键的发现:**

#### 🔴 发现 1:`_create_section_card` 在 18 个 page 各有一份"私有硬编码副本"

| 文件 | 实现细节 | 是否用 design_system token? | 是否带 v4 阴影? |
|------|----------|--------------------------|---------------|
| `gui_widget._create_card` | `ds.container.card_padding(24)` + spacing 14 + `cardTitle` + shadow blur 28 | ✅ 是 | ✅ 是 |
| `pages/death_sound._create_section_card` | 硬编码 `setContentsMargins(14,12,14,12)` + spacing 8 + `statusLabel` | ❌ 否 | ❌ 无阴影 |
| `pages/advanced._create_section_card` | 同上(几乎逐字相同) | ❌ 否 | ❌ 无阴影 |
| `pages/flash._create_section_card` | 同上 | ❌ 否 | ❌ 无阴影 |
| `pages/crosshair._create_card` | 自有实现 + shadow blur **10** alpha 30 | ❌ 否 | ⚠️ 弱阴影 |
| 其他 14 个 page | 几乎逐字复制粘贴 | ❌ 否 | ❌ 无阴影 |

**这意味着:v4 在 token 层做的所有改动(`card_padding 18→24`, `card_border_radius 12→14`, shadow blur 15→28),在 18 个 page 里全部失效!**

**v4 token 改动实际穿透率:约 20-30%**(只覆盖 gui_widget.py 内嵌的页面 + 极少数用 cardTitle 的 page)。

这就是为什么:
- 阴影看不见 → 大部分卡根本没 shadow
- 排版不一致 → 18 page 各自硬编码
- 调色调不动卡 → token 改了 cardTitle,但 18 page 用的是 statusLabel

#### 🔴 发现 2:三个"组件库尝试"是死代码(0 引用)

| 模块 | 行数 | 引用数 | 状态 |
|------|------|--------|------|
| `ui_components.py` | 357 | **0** | ❌ 死代码(完整组件工厂,但没人用) |
| `ui_components_animated.py` | 180 | **0** | ❌ 死代码 |
| `ui_modern_styles.py` | 未看 | **0** | ❌ 死代码 |

**总死代码:932+ 行,占据根目录,造成认知噪音。**

之前有人尝试做组件库,但因为先做组件、再要求迁移,工程量大没人愿意,最后被遗弃。**新页继续 ad-hoc 写,组件库被晾在那里。**

这给 v5 一个重要警示:**纯"工厂函数级组件库"不会被采纳,要在视觉重做的同时强制使用,要不就别做**。

#### 🔴 发现 3:根目录 15 个 ui_xxx.py,其中 4 个真用,11 个边缘/死

| 模块 | 引用数 | 估计状态 |
|------|--------|---------|
| `ui_help_panel` | 38 | ★★★★★ 核心(每个 page 都用) |
| `ui_toast` | 12 | ★★★ 中等使用 |
| `ui_design_system` | 5 | ★★★ token 层(但 18 page 不依赖) |
| `ui_effects` | 6 | ★★ 一定使用 |
| `ui_animations` | 4 | ★★ 一些动画 |
| `ui_toggle_switch` | 2 | ★★★ 重要(每页 toggle 都用) |
| `ui_focus_underline` | 2 | ★ 边缘 |
| `ui_ripple_effect` | 2 | ★ 边缘 |
| `ui_shimmer` | 2 | ★ 边缘 |
| `ui_slider_bubble` | 2 | ★ 边缘 |
| `ui_transitions` | 2 | ★ 边缘 |
| `ui_style_applier` | 2 | ❌ 半死(自循环引用) |
| `ui_components` | **0** | ❌ 死代码 |
| `ui_components_animated` | **0** | ❌ 死代码 |
| `ui_modern_styles` | **0** | ❌ 死代码 |

#### 🔴 发现 4:objectName 命名碎片化

`pages/*.py` 用的 objectName 出现频次:
- `titleLabel` 25 次
- `card` 24 次(但卡内是各自硬编码的 layout)
- `statusLabel` 18 次(各 page 用它做卡片标题,但 gui_widget 用 `cardTitle`)
- `hintLabel` 19 次
- 同一语义两套命名 → QSS 要写两份选择器

#### 🟢 发现 5:已有的好资产

- `ui_help_panel.HelpButton + HelpCard` — 38 处使用,稳定有效
- `widgets/responsive_grid.ResponsiveGrid` — Sprint 2 沉淀,广泛用
- `theme_manager.ThemeColors + 7 套主题` — 设计良好的颜色契约
- `ui_toggle_switch.ToggleSwitch` — 自定义 iOS 风开关,效果好
- `core/` 业务分层清晰
- **322 个测试** — 极其重要的质量保障网

### 1.3 这次诊断的总结

> **v4 看上去是大改,实际是表层补丁**。token 改动只穿透 ~25% 的 UI,80% 的 page 内部用的是"v2/v3 时代的硬编码副本"。
>
> **如果 v5 还是按 v4 的思路改 token + 调色板,效果只会比 v4 高 5-10%,因为穿透率没解决**。
>
> **真正能让 UI 大幅提升的是:先把架构改通,让 token 改动能穿透 100%,再做视觉升级**。

---

## 二、v5 战略转向(关键决策)

### 2.1 战略思想

**之前的 V5_PLAN(7 phase 表层升级)是错的。** 在不修架构的情况下做表层升级,最后又会发现"改了东西没穿透"。

**正确的 v5 应该是:架构革命 + 视觉重做,先架构后视觉,改完架构再调色一改穿透 100%。**

### 2.2 v5 战略目标(三层)

| 层 | 目标 | 价值 |
|----|------|------|
| **架构层** | 18 page 的 card 实现统一为 `SettingsCard` 组件;清死代码;widgets/ 真正成为复用层 | 让以后任何 UI 改动都"一改穿透" |
| **视觉层** | 配色升级 / icon 系统 / 阴影系统 / 卡头组件 | 美学 3.7 → 4.5+ |
| **细节层** | 微动画 / focus ring / 字体 | 4.5 → 4.7+ |

### 2.3 三件事的执行顺序

**架构 → 视觉表层 → 细节** 必须按这个顺序,不能乱。

```
   [Phase 0]                           准备 + 基线
       ↓
   [Phase 1] 清死代码                  减法,降低噪音
       ↓
   [Phase 2] 建 widgets/ 组件层        基础设施
       ↓
   [Phase 3] 18 page 迁移到组件        关键节点 — 改完后 token 才能 100% 穿透
       ↓
   [Phase 4] 配色 token 大改           ★ 此时 token 改动会一改穿透 100%
       ↓
   [Phase 5] Icon 系统集成
       ↓
   [Phase 6] CardHeader 应用 + 状态徽章重做
       ↓
   [Phase 7] 4 特殊页重布局
       ↓
   [Phase 8] basic dashboard 化
       ↓
   [Phase 9] 微动画 / focus / 字体
       ↓
   [Phase 10] 总验收 + 修复 + 报告
```

---

## 三、Phase 详细规划(11.5 天 / 10 个 Phase)

### Phase 0:基线锁定 + 防护网搭建(0.5 天)

**目标**:建立完整的视觉/功能/性能基线,确保后续任何 phase 出问题都能秒级回滚。

**任务**:
1. 创建分支 `ui-v5-2026-05-07`,从 master 拉
2. 写 `scripts/v5_visual_baseline.py` — 一键截全 27 页 × 2 分辨率(1920/1366) = **54 张** v4 基线图
3. 写 `scripts/v5_visual_diff.py` — 用 PIL 跑像素 diff,自动标红框,生成 HTML 报告
4. 跑全 322 测试,记录通过率 + 每个 test 时长(基线)
5. 启动 smoke + 27 页切换 smoke,记录启动时间 + 内存占用基线
6. 把 v4 截图 / 测试报告 / 性能基线打包到 `artifacts/v5_baseline/`

**Phase 0 完成标准**:
- ✅ 54 张 v4 基线截图归档
- ✅ 322 测试 0 fail 报告归档
- ✅ 启动时间 / 内存基线归档
- ✅ visual_diff 工具可用(自测)
- ✅ 创建分支 commit `Phase 0: baseline`

---

### Phase 1:死代码清理(0.5 天)

**目标**:消除 932+ 行死代码,让代码库认知更清晰。**纯减法,无视觉变化,但有功能验证压力**。

**任务**:
1. 删除 `ui_components.py` (357 行,0 引用,确认后删)
2. 删除 `ui_components_animated.py` (180 行,0 引用)
3. 删除 `ui_modern_styles.py` (检查后,0 引用就删)
4. 评估 `ui_style_applier.py` (2 引用,自循环 + ui_components_animated → 删除后看是否破坏什么)
5. 整理根目录:把剩下的 `ui_xxx.py` 移到 `widgets/legacy/` 或 `widgets/effects/` 子目录(可选,谨慎)
6. 跑全 322 测试 + 视觉对比 54 张

**Phase 1 完成标准**:
- ✅ 322 测试 0 fail
- ✅ 54 张视觉 diff 0 像素差异
- ✅ 启动时间不退化
- ✅ commit `Phase 1: clean dead UI modules (-932 lines)`

**风险**:0 引用 ≠ 真无用(可能 PyInstaller 隐式引入)
**缓解**:删完后跑一次 PyInstaller 打包测试,确保 EXE 仍能启动

---

### Phase 2:widgets/ 组件层建设(1.5 天)

**目标**:抽出 6-8 个核心组件,让 Phase 3 可以"批量替换"。

#### 抽取的组件清单

| # | 组件名 | 文件 | 替换的旧实现 | 估计调用次数 |
|---|--------|------|-------------|------------|
| 1 | **SettingsCard** | `widgets/settings_card.py` | 18 page 的 `_create_section_card` + gui_widget `_create_card` | ~50 处 |
| 2 | **CardHeader** | `widgets/card_header.py` | 卡内 title_label + description_label 组合 | ~50 处 |
| 3 | **PageHeader** | `widgets/page_header.py` | 27 page 各自的 title + page_lead_label 组合 | 27 处 |
| 4 | **SettingsRow** | `widgets/settings_row.py` | label + 控件 + hint 的 HBoxLayout 模式 | ~200 处 |
| 5 | **AppButton** | `widgets/app_button.py` | QPushButton + setObjectName 模式(primary/secondary/ghost/icon/danger) | ~80 处 |
| 6 | **StatusChip** | `widgets/status_chip.py` | audio_status_chip / badgeLabel 等 | ~30 处 |
| 7 | **IconLabel** | `widgets/icon_label.py` | icon + 文字 复合(为 Phase 5 做铺垫) | 新加 ~135 处 |
| 8 | **DividerWithText**(可选) | `widgets/divider.py` | 横线 + 中文字 分组 | ~10 处 |

#### SettingsCard 设计示意

```python
# widgets/settings_card.py
class SettingsCard(QFrame):
    """设置卡片 — 统一替代散在 18 个 page 的 _create_section_card

    用法:
        card = SettingsCard(title="基础配置", description="..." , semantic="config")
        card.add_row(SettingsRow(...))
        card.add_widget(my_widget)
        layout.addWidget(card)
    """
    SEMANTIC_COLORS = {
        "config":  "accent_primary",   # 紫色色条
        "info":    "accent_secondary", # 青色色条
        "status":  "success",          # 绿色
        "warning": "accent_warm",      # 橙色
        "danger":  "error",            # 红色
    }

    def __init__(self, title=None, description=None, semantic="config", icon=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")  # 注意:新名,旧 "card" 保留兼容
        self._build(title, description, semantic, icon)

    def _build(self, title, description, semantic, icon):
        layout = QVBoxLayout(self)
        ds = get_design_system()
        layout.setContentsMargins(*[ds.container.card_padding] * 4)
        layout.setSpacing(ds.container.card_title_to_content)

        # 阴影统一在这里
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(ds.container.card_shadow_blur)  # 新加 token
        shadow.setColor(QColor(0, 0, 0, ds.container.card_shadow_alpha))
        shadow.setOffset(0, ds.container.card_shadow_offset_y)
        self.setGraphicsEffect(shadow)

        if title:
            self._header = CardHeader(title, description=description, semantic=semantic, icon=icon)
            layout.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(ds.spacing.md)
        layout.addWidget(self._body)

    def add_row(self, row):
        self._body_layout.addWidget(row)

    def add_widget(self, widget):
        self._body_layout.addWidget(widget)

    def add_layout(self, layout):
        self._body_layout.addLayout(layout)
```

#### Phase 2 任务

1. 创建 `widgets/` 子目录结构(已存在,但要扩充)
2. 实现 7 个组件(SettingsCard / CardHeader / PageHeader / SettingsRow / AppButton / StatusChip / IconLabel)
3. 写 `scripts/widget_showcase.py` — 一个独立小窗口展示这 7 个组件的所有 variant(40 行左右)
4. 写**单元测试**:`tests/test_widget_components.py`(每组件 2-3 个测试,共 ~15 个)
5. 跑全 322 测试 + 新加 15 = 337 测试,**0 fail**

**Phase 2 完成标准**:
- ✅ 7 个组件文件 + showcase + 15 单测
- ✅ 全测试 337 个 0 fail
- ✅ showcase 启动正常显示所有 variant
- ✅ commit `Phase 2: extract 7 core UI components`

---

### Phase 3:18 page 迁移到 SettingsCard(2 天)

**目标**:把 18 个 page 的 `_create_section_card` 全部替换为 `SettingsCard`,gui_widget 的 `_create_card` 也迁移。**这一步完成后,任何 token 改动可以一改穿透 100%。**

#### 迁移策略

**逐 page 迁移,每个 page 独立验证**:

```
Day 1 (8 pages):
  death_sound, advanced, audio_health, audio_import_wizard,
  audio_replay, audio_task_panel, config_snapshot, preset_center

Day 2 (10 pages + gui_widget):
  flash, hud_color, kill_icon, magnifier, screen_effects,
  special_sound, viewmodel, about, crosshair (有自己的 _create_card),
  gui_widget._create_card (basic page 内)
```

**每个 page 的迁移流程**:
1. grep 出所有 `_create_section_card` 调用点
2. 替换为 `SettingsCard(...)` 实例
3. 删除该 page 私有的 `_create_section_card` 方法
4. 跑该 page 相关的测试
5. 截图对比该 page(1920 + 1366)
6. 视觉差异在预期内(应该几乎一致,因为 SettingsCard 的初始默认参数对齐 v4 token)

#### Phase 3 完成标准

- ✅ 18 个 page + gui_widget 全部用 SettingsCard
- ✅ 18 份私有 `_create_section_card` 全部删除(预计减 ~250 行重复代码)
- ✅ 全测试 337 个 0 fail
- ✅ 54 张视觉 diff:**预期内的微差异**(描述于 commit message)
- ✅ commit `Phase 3: migrate 18 pages to SettingsCard component (-250 LOC duplication)`

**风险**:
- R3.1: 某 page 的 _create_section_card 有特殊变种(如 audio_health 多一个 status row),迁移时漏处理
  - 缓解:每 page 单独 commit,出问题立即 revert 该 page
- R3.2: SettingsCard 默认参数和 page 老的硬编码不完全一致,造成视觉跳动
  - 缓解:Phase 2 设计 SettingsCard 时,默认参数严格对齐"v4 后大多数 page 的样子"

---

### Phase 4:配色 token 大改(1 天)

**这是 v5 视觉跃迁的核心。** 因为 Phase 3 完成后,token 改动会穿透 100% UI。

#### 配色重设(对照 Linear / Vercel / Raycast)

##### bg 系统(注入 5° 蓝调,Linear 风)

| Token | v4 | v5 | 变化 |
|-------|-----|-----|------|
| bg_primary | `#0d0e11` | **`#0a0c12`** | 微深 + 蓝调 |
| bg_secondary | `#161821` | **`#14171f`** | 微提亮 + 蓝调 |
| bg_tertiary | `#1d1f2a` | **`#1c1f2c`** | 微调 |
| bg_elevated | `#25283a` | **`#262a3a`** | 微调 |
| **bg_card**(新) | — | **`#1a1d27`** | 卡片专用,在 secondary 上提一档 |
| **bg_card_hover**(新) | — | **`#20242f`** | hover 态 |

##### accent 系统(单 → dual + warm)

| Token | v4 | v5 | 用途 |
|-------|-----|-----|------|
| accent_primary | `#6166f1`(indigo) | **`#7c3aed`**(violet — 更华丽) | 主 CTA / toggle ON / focus / 激活 |
| accent_secondary(新) | — | **`#06b6d4`**(青) | 次要操作 / 链接 / 装饰 |
| accent_warm(新) | — | **`#f59e0b`**(琥珀) | 警告 / 重要提示 / 倒计时 |

**纪律**:
- accent_primary 总面积 ≤ 8% 屏幕
- accent_secondary 总面积 ≤ 3%
- accent_warm 总面积 ≤ 2%
- 三色合计 ≤ 13%

##### 状态色降饱和(去圣诞树)

| 状态 | v4 满色块 | v5 灰底+点 |
|------|---------|----------|
| success | 绿底+绿字+绿边 | 灰底+8px 绿点+主文字色字 |
| warning | 橙底+橙字+橙边 | 灰底+8px 橙点+主文字色字 |
| info | 蓝底+蓝字+蓝边 | 灰底+8px 蓝点+主文字色字 |
| error | 红底+红字+红边 | 仅这个保持满色(异常态需要醒目) |

#### 阴影系统升级(新 token + inset 模拟)

```python
@dataclass
class Elevation:  # 新加到 ui_design_system.py
    sm_blur: int = 8
    sm_alpha: int = 80
    sm_offset_y: int = 2

    md_blur: int = 24       # v4 是 28,改 24 配合更亮的卡片背景
    md_alpha: int = 120     # v4 是 60,加大
    md_offset_y: int = 6

    lg_blur: int = 40
    lg_alpha: int = 160
    lg_offset_y: int = 12
```

加上 `inset 1px rgba(255,255,255,0.04)` 顶光 + `0 0 0 1px rgba(255,255,255,0.04)` 微边框 — 这两个用 QSS border 模拟(Qt 不直接支持 inset shadow,但可以用 QFrame 的 border-top 模拟 inset)。

#### 7 套主题适配

每套主题(深/浅 + 5 套设计师主题)按同样规则调整。**预计 token 改动 × 7 套主题 = 14 处颜色调整**。

#### Phase 4 任务

1. 修改 `ui_design_system.py`:加 `Elevation` dataclass,扩展 `ThemeColors` 加 `bg_card / bg_card_hover / accent_secondary / accent_warm`
2. 修改 `theme_manager.py` 7 套主题颜色定义
3. 修改 `theme_manager.generate_stylesheet()`:用新 token,状态徽章规则改"灰底+点"
4. 修改 `widgets/settings_card.py`:用新阴影 token
5. 跑全测试 + 54 张截图 diff(**预期会全屏视觉变化** — 这次是真大改)
6. 7 套主题逐套截图对比

#### Phase 4 完成标准

- ✅ 全测试 337 个 0 fail
- ✅ 54 张截图全部呈现新配色(穿透率 100%,因为 Phase 3 已完成)
- ✅ 7 套主题切换都正常
- ✅ commit `Phase 4: color system v5 — dual accent, blue-tinted bg, elevation upgrade`

---

### Phase 5:Icon 系统集成(1.5 天)

#### 选型决策(已敲定)

**选 qtawesome 1.3+ + Material Design Icons 7.x**

理由:
- ✅ pip 一键安装,与 PySide6 6.x 无缝集成
- ✅ Material Design Icons 7000+ 个,风格统一现代
- ✅ 支持颜色注入(随主题切换)
- ✅ 增加包体 ~5MB(可接受,EXE 已 100MB+ 量级)
- ⚠️ 备选:Lucide-PyQt(更现代但封装少)

#### Icon 应用清单

| 区域 | icon 位 | 数量 |
|------|---------|------|
| 侧栏导航(27 页) | 每页 1 个 16×16 | 27 |
| 卡片标题(SettingsCard 内 CardHeader) | 每张卡 1 个 18×18 | ~50 |
| 主按钮(AppButton primary) | 主操作按钮带 icon | ~30 |
| 状态徽章(StatusChip) | success/warning/info/error 各 1 | ~30 |
| 设置项 toggle 描述前 | 重要 toggle 加描述 icon | ~10 |
| **合计** | | **~145** |

#### 27 页侧栏 icon 映射

```python
ICON_MAP = {
    "basic":          "mdi.cog-outline",
    "kill_sound":     "mdi.target",
    "kill_voice":     "mdi.account-voice",
    "death_sound":    "mdi.skull-outline",
    "gun_sound":      "mdi.pistol",
    "switch_weapon":  "mdi.swap-horizontal",
    "reload_sound":   "mdi.reload",
    "special_sound":  "mdi.music-circle",
    "crosshair":      "mdi.crosshairs",
    "kill_icon":      "mdi.image-multiple-outline",
    "viewmodel":      "mdi.eye-outline",
    "magnifier":      "mdi.magnify",
    "flash":          "mdi.flash",
    "hud_color":      "mdi.palette-outline",
    "screen_effects": "mdi.monitor-screenshot",
    "music":          "mdi.music",
    "voice_output":   "mdi.microphone",
    "utility":        "mdi.tools",
    "advanced":       "mdi.cog-transfer-outline",
    "audio_health":   "mdi.heart-pulse",
    "audio_import_wizard": "mdi.import",
    "audio_task_panel": "mdi.format-list-checks",
    "audio_replay":   "mdi.replay",
    "preset_center":  "mdi.bookmark-multiple-outline",
    "config_snapshot":"mdi.content-save-outline",
    "account":        "mdi.account-circle-outline",
    "about":          "mdi.information-outline",
}
```

#### Phase 5 任务

1. `pip install qtawesome` + 加入 `requirements_qt.txt`
2. 写 `widgets/icon_provider.py`:封装 qtawesome,做主题颜色注入,fallback 机制(qtawesome 不可用时用 emoji)
3. 修改 `widgets/icon_label.py` 用新 provider
4. 修改 `widgets/card_header.py` 支持 icon 参数
5. 修改 `widgets/app_button.py` 支持 icon 参数
6. 修改 `gui_widget.py` 侧栏导航代码,每项加 icon
7. 修改 `widgets/status_chip.py` 加 icon 支持
8. 修改 `build_tools/build_release.py` 把 qtawesome 加进 hidden imports
9. 验证 PyInstaller 打包后 icon 正常显示
10. 跑全测试 + 54 截图

#### Phase 5 完成标准

- ✅ 全测试 0 fail
- ✅ 54 截图:侧栏 27 个 icon 显示正确
- ✅ EXE 打包测试通过(7z 包大小 ≤ 110MB)
- ✅ commit `Phase 5: integrate qtawesome icon system (~145 icon positions)`

**风险**:
- R5.1: qtawesome 字体注册在某些 Win 环境失败
  - 缓解:icon_provider 做 fallback 到 emoji
- R5.2: 增加启动时间
  - 缓解:延迟加载,启动后台预热

---

### Phase 6:CardHeader 全应用 + 状态徽章重做(1 天)

**目标**:把 Phase 2 抽的 CardHeader 真正"穿"上去,让每张卡有"色条 + icon + 标题"的视觉骨架。

#### CardHeader 视觉

```
┌────────────────────────────────────────────┐
│ [3px 紫色色条] [⚡ icon 18px] 闪光效果         │
│                              [4 项已配置]    │
│                                            │
│  (卡片内容)                                  │
└────────────────────────────────────────────┘
```

#### Phase 6 任务

1. 完善 `widgets/card_header.py` 实现(Phase 2 已建骨架,这里完善视觉)
2. 给每张卡分配 semantic("config" / "info" / "status" / "warning" / "danger")
   - 默认全部 "config"(紫色)
   - "运行状态/系统状态" → "status"(绿)
   - "需要注意/警告" → "warning"(橙)
   - "异常/错误" → "danger"(红)
3. 重做 `audioStatusChip` → 用 StatusChip 组件
4. 重做 `badgeLabel` → 用 StatusChip 组件
5. 跑全测试 + 54 截图

#### Phase 6 完成标准

- ✅ 全测试 0 fail
- ✅ 50 张卡都有色条 + icon
- ✅ 状态徽章不再"满色块",改"灰底+小点"
- ✅ commit `Phase 6: apply CardHeader to all cards, refactor status chips`

---

### Phase 7:4 特殊页重布局(2 天)

#### crosshair 页(右重 → 中央对称)

```
v4: [瘦预览][密集控制]
    [动画][击杀]
    [自定义准心宽行]

v5: [─── 准心预览(带场景模拟,大,左 50%)─── | ─── 控制(右 50%)───]
    [─── 自定义准心(全宽)──────]
```

#### flash 页(蓝色板 → 实质内容)

- 升级 `widgets/flash_preview_widget.py` 为"模拟游戏场景 + 闪光叠加 + 衰减曲线"
- 右侧加"参数实时反馈"小卡

#### account 页(填满下半屏)

- 已登录态 + 未登录态分别设计
- 未登录态:登录卡 + 4 个 benefits 卡(用 ResponsiveGrid)+ FAQ 折叠组

#### advanced 页(密度均衡)

- 当前左右两小卡密度悬殊
- 改垂直堆叠:CFG 路径 → 内部测试 → 界面主题 → 配置文件管理

#### Phase 7 完成标准

- ✅ 4 页视觉显著改善
- ✅ 全测试 0 fail
- ✅ 1366/1920 两个分辨率都正常
- ✅ commit `Phase 7: redesign crosshair / flash / account / advanced layouts`

---

### Phase 8:basic 运行面板 dashboard 化(0.5 天)

```
v4: 6 个胶囊横排
    [主题・深色] [界面・普通] [账号・未登录] [GSI・未运行] [音频・需检查] [配置・已保存]

v5: 6 个 status card 双行(用 StatusChip + ResponsiveGrid)
    [🎨 主题深色 ●] [🖥 界面普通 ●] [👤 账号未登录 ○]
    [📡 GSI 未运行 ○] [🔊 音频需检查 ●] [💾 配置已保存 ●]
```

色点用语义色(绿正常 / 灰未配 / 橙警告 / 红错误),icon 用 Phase 5 的 qtawesome。

#### Phase 8 完成标准

- ✅ basic 页运行面板视觉显著改善
- ✅ 全测试 0 fail
- ✅ commit `Phase 8: basic page status dashboard redesign`

---

### Phase 9:微动画 + focus ring + 字体(1 天)

#### hover lift

- SettingsCard hover:垂直平移 -2px(用 QPropertyAnimation 模拟 transform)
- 阴影从 elevation_md 升到 elevation_lg
- transition 150ms ease-out

#### focus ring

- AppButton focus 时显示 2px accent_primary ring + 2px 外发光
- 输入框 focus 时同样

#### 字体升级(可选)

- 选项 A:保留 `Microsoft YaHei UI` (零成本,效果普通)
- 选项 B:**HarmonyOS Sans CN** (免费商用,效果上乘,~6MB 字体文件)
- 选项 C:**OPPO Sans 4.0** (免费商用,~3MB)
- 推荐 **B**,通过 `QFontDatabase.addApplicationFont` 加载

#### Phase 9 完成标准

- ✅ hover lift 平滑无抖动
- ✅ focus ring 键盘导航可见
- ✅ 字体加载成功(如选 B/C)
- ✅ 全测试 0 fail
- ✅ commit `Phase 9: micro-animations, focus ring, HarmonyOS font`

---

### Phase 10:总验收 + 修复 + 报告(0.5 天)

**任务**:
1. 跑全 337 测试 ≥ 3 次,确认稳定 0 fail
2. 跑 27 页手测清单(附录 A)
3. 跑 5 个响应式断点(1366 / 1500 / 1700 / 1920 / 2560)
4. 跑 7 套主题循环切换 smoke
5. PyInstaller 打包,EXE 启动验证
6. v4 vs v5 视觉对比报告(54 张前后对比)
7. 性能对比报告(启动时间 / 内存 / 切页时间)
8. 美学评分自评 + 撰写 v5 验收文档
9. 合并 `ui-v5-2026-05-07` → `master`,打 tag `v5.0.0`

---

## 四、关键设计决策(已敲定 / 需确认)

| # | 决策 | 我的建议 | 替代方案 |
|---|------|----------|----------|
| 1 | 死代码删除范围 | 删 ui_components / ui_components_animated / ui_modern_styles 三个 0 引用模块 | 保留(占 ~932 行) |
| 2 | 组件抽取数量 | 7 个核心组件(够用不冗余) | 15 个(过度) |
| 3 | Icon 库 | **qtawesome + Material Design Icons** | Lucide-PyQt(更现代但封装少) |
| 4 | 字体 | **HarmonyOS Sans CN**(~6MB) | 保留 Microsoft YaHei UI(零成本) |
| 5 | accent 主色 | 从 indigo `#6166f1` → **violet `#7c3aed`** | 保留 indigo |
| 6 | dual-accent | **加青 + 琥珀** 限定用途 | 保持单 accent |
| 7 | bg 蓝调注入 | **bg 全部 +5° 蓝调** | 保持纯灰 |
| 8 | Phase 1 死代码删除独立提交 | 是 | 合并进 Phase 2 |
| 9 | 是否做 Phase 7 + 8 | **做**(账号/闪光/准心/高级/basic 是用户高频页,值得投入) | 跳过(节省 2.5 天) |
| 10 | 完成后 v5 是否打 tag | 是,tag `v5.0.0` | 不打 tag |

---

## 五、风险登记册(完整版)

| ID | 风险 | 概率 | 影响 | 缓解 |
|----|------|------|------|------|
| R1 | qtawesome 在某 Win 环境字体注册失败 | 低 | 中 | icon_provider fallback 到 emoji |
| R2 | bg 色调改动让 7 套主题中某套不和谐 | 中 | 低 | 每套主题单独审,允许微调 |
| R3 | Phase 3 迁移某 page 漏处理特殊变种 | 中 | 中 | 每 page 单独 commit,出错单独 revert |
| R4 | SettingsCard 默认参数和老 page 的硬编码不完全一致 | 中 | 中 | Phase 2 时严格对齐 v4 默认 |
| R5 | inset shadow 在 Qt 6.10 不完美支持 | 低 | 中 | 用 QFrame border-top 模拟 |
| R6 | CardHeader 高度变化破坏 ResponsiveGrid 列高 | 中 | 中 | Phase 6 后专项验证响应式 |
| R7 | 字体切换导致首次渲染卡顿 | 中 | 低 | QFontDatabase 异步加载 |
| R8 | 视觉 diff 误报(反走样浮动) | 高 | 低 | 设 5px 容差,人工复核 |
| R9 | 工时超出 11.5 天 | 中 | 中 | Phase 7 / 9 可裁剪 |
| R10 | PyInstaller 打包死代码删除后失败 | 低 | 高 | Phase 1 完后立即跑打包测试 |
| R11 | 删 ui_components 后某测试静默 import 失败 | 低 | 中 | 删前跑 grep 找所有引用 |
| R12 | 某 page 用 statusLabel 做卡片标题(18 处),改 cardTitle 后 QSS 不兼容 | 高 | 中 | 在 SettingsCard 内同时设 statusLabel + cardTitle 兼容 |

---

## 六、防护网(每个 Phase 必做的"四件套")

每个 Phase commit 前必须做:

| 检查 | 内容 | 通过标准 | 工具 |
|------|------|----------|------|
| 视觉对比 | 跑 54 截图,生成 v4-vs-vN diff HTML | 没有意料外像素差异 | `scripts/v5_visual_diff.py` |
| 功能回归 | pytest 全 322+ | **0 fail** | `pytest tests/ -v` |
| 性能基线 | 启动时间 / 内存 | 不超过基线 + 阈值 | `scripts/v5_perf_check.py` |
| 手测清单 | 该 Phase 影响的页面快测 | 0 关键问题 | 手动(参考附录 A) |

**任何一项 fail → 不 commit,在 Phase 内修到通过**。

---

## 七、回滚策略

### 7.1 单 Phase 回滚

每个 Phase 独立 commit + tag(`ui-v5-phase-N`)。任何 Phase 翻车:
```bash
git revert <phase-commit>
# 或
git reset --hard ui-v5-phase-(N-1)
```

### 7.2 全盘回滚

如果 v5 全盘失败:
```bash
git checkout master  # v4 仍在 master
# v4 分支 ui-aesthetics-v4-2026-05-07 永久保留作"安全网"
```

### 7.3 备份恢复

如果连 git 都崩了(极端):
```bash
cd <备份目录>/v4_20260507
tar -xzf source_only.tar.gz
# 或
git clone full_repo.bundle restored
```

---

## 八、总验收清单(v5 完成时打勾)

### 功能完整性
- [ ] 322 测试 0 fail(连续跑 3 次稳定)
- [ ] 27 页手测清单(附录 A) 0 关键问题
- [ ] 7 套主题切换正常
- [ ] 5 个响应式断点正常(1366 / 1500 / 1700 / 1920 / 2560)
- [ ] PyInstaller 打包 EXE 启动正常
- [ ] EXE 大小 ≤ 110MB

### 性能基线
- [ ] 启动时间增加 ≤ 200ms
- [ ] 切页时间增加 ≤ 50ms
- [ ] 内存占用增加 ≤ 30MB

### 视觉/美学
- [ ] v4 vs v5 视觉 diff 报告归档
- [ ] 美学评估文档,自评分 ≥ 4.5
- [ ] 用户视觉验收(用户启动看)

### 代码质量
- [ ] 死代码 0 行(已删 ~932 行)
- [ ] 18 page 私有 _create_section_card 0 个(已统一)
- [ ] widgets/ 7 个核心组件 + showcase + 单测
- [ ] 关键代码 LOC 不增反减(预计净减 ~150 行)

### 发布准备
- [ ] master 合并
- [ ] tag `v5.0.0` 打上
- [ ] v4 分支 `ui-aesthetics-v4-2026-05-07` 保留
- [ ] 备份 `<备份目录>/v4_20260507` 保留
- [ ] 文档:V5_PLAN / V5_FINAL_PLAN / v5_acceptance 全部归档

---

## 附录 A:27 页手测清单

每个 Phase 结束时,用 5-10 分钟过该 Phase 影响的页面:

| 页面 | 关键操作 |
|------|----------|
| basic | toggle 切换 / 主题切换 / 状态刷新 / 音量滑块 |
| kill_sound | 武器分类 tab 切换 / combobox 选择 / 测试按钮 |
| kill_voice | 同上 + 录音上传 |
| death_sound | toggle / combobox |
| gun_sound | 同上 |
| switch_weapon | 响应式列数变化 |
| reload_sound | 同上 |
| special_sound | toggle |
| crosshair | 滑块拖动 / 颜色切换 / 预览实时更新 / 自定义准心代码 |
| kill_icon | 上传图标 / 切换 |
| viewmodel | 滑块 |
| magnifier | toggle / 数值 |
| flash | toggle / 滑块 / 预览 / 颜色选择 |
| hud_color | 颜色面板 |
| screen_effects | toggle / 强度 |
| music | 播放/暂停 / 切歌 / 进度拖动 / 音量 |
| voice_output | 设备列表 / 音量 / 槽位添加删除 |
| utility | toggle |
| advanced | CFG 路径选择 / 内部测试输入 / 配置文件保存导出 |
| audio_health | 检查按钮 / 列表展开 |
| audio_import_wizard | 完整向导流程 |
| audio_replay | 播放重放 |
| audio_task_panel | 任务面板 |
| preset_center | 预设增删改 |
| config_snapshot | 快照 |
| account | 未登录:登录表单 / 已登录:个人信息 |
| about | 链接显示 |

---

## 附录 B:Phase 工时估算依据

| Phase | 任务 | 行数估计 | 工时依据 |
|-------|------|---------|---------|
| 0 | 基线 | 工具 200 LOC + 跑测试 | 0.5 天 |
| 1 | 删死代码 | 删除 932 LOC,验证 | 0.5 天 |
| 2 | 7 个组件 | 新增 ~600 LOC + 单测 ~250 LOC | 1.5 天 |
| 3 | 18 page 迁移 | 修改 ~500 LOC,删除 ~250 LOC | 2 天(平均 1 page 1 小时) |
| 4 | 配色 token | 修改 theme_manager ~300 LOC | 1 天 |
| 5 | Icon 集成 | 新加 ~200 LOC + 全 page 应用 | 1.5 天 |
| 6 | CardHeader 应用 | 微调 ~100 LOC | 1 天 |
| 7 | 4 特殊页 | 修改 ~600 LOC | 2 天 |
| 8 | basic dashboard | 修改 ~150 LOC | 0.5 天 |
| 9 | 动画/字体 | 修改 ~200 LOC | 1 天 |
| 10 | 总验收 | 验证 + 文档 | 0.5 天 |
| **合计** | | **~3000 LOC 净改动** | **11.5 天** |

---

## 附录 C:与之前 V5_PLAN 的关键差异

| 维度 | V5_PLAN(旧) | V5_FINAL_PLAN(新) |
|------|---------------|-------------------|
| 核心思想 | 表层升级(配色 + icon + 局部重布局) | 架构革命 + 视觉重做 |
| 是否清死代码 | ❌ 不动 | ✅ Phase 1 清 932 LOC |
| 是否抽组件 | ⚠️ 仅 CardHeader | ✅ Phase 2 抽 7 个核心组件 |
| 是否迁移老 page | ❌ 留着旧 _create_section_card | ✅ Phase 3 全迁移 |
| 配色穿透率 | ~25%(只覆盖 gui_widget) | **100%**(改完架构后) |
| Phase 数 | 7 | 10 |
| 工时 | 8.5 天 | 11.5 天 |
| 预期美学评分 | 4.0-4.2 | **4.5+** |
| 长期收益 | 一次性 | 持续(后续 UI 改动一改穿透) |

---

> 写于 2026-05-07,基于真实代码勘察 + 18 个 page 的 _create_section_card 实现对比 + 322 测试现状 + 7 套主题契约。
>
> 这次不是从"我觉得 UI 应该这样"出发,而是从"项目实际是什么"出发。
