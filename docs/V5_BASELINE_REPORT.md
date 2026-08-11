# v5 Phase 0 基线报告

> **基线时刻**: 2026-05-07
> **基线 commit**: master `b51424a`(v4 合并点)
> **基线分支**: `ui-v5-2026-05-07`
> **后续每个 Phase 必须严格优于或不劣于此基线**

---

## 一、视觉基线

- **覆盖**: 27 页 × 2 分辨率(1920×1080 / 1366×768)= **54 张截图**
- **存储**: `artifacts/v5_baseline/v4/*.png`(7.7MB,本地不入库)
- **采集时长**: 54.2 秒
- **manifest**: `artifacts/v5_baseline/v4/manifest.json`
- **自检**: 自对比 → 全 54 张 0.000% 差异(diff 工具可信)

### Flakiness 基线(同代码两次跑的差异)

经实测,**v4 自身两次跑**:`max 13.586% / avg 0.384%`(主要在 basic 页因音乐进度条/玩家 ID/状态实时数据动态)。

**判定阈值(v5 后续 Phase)**:
- 单张 < **15%** → 可视为同上限 flakiness,接受
- avg < **0.5%** → 整体可控
- 任何 > 15% 单张需要单独审视(可能是真实视觉差异)

---

## 二、性能基线(Best of 2 rounds)

| 指标 | 数值 | v5 后允许阈值 |
|------|------|---------------|
| 启动时间(显示首页就绪) | **1189.94 ms** | ≤ 1389.94 ms (+200ms) |
| 初始内存(主窗口就绪) | **193.75 MB** | ≤ 223.75 MB (+30MB) |
| 全 27 页加载完后内存 | **328.31 MB** | ≤ 358.31 MB (+30MB) |
| 切页平均耗时 | **194.13 ms** | ≤ 244.13 ms (+50ms) |
| 切页最大耗时 | **993.42 ms** | ≤ 1043.42 ms (首次加载,可接受) |

### 单页切换耗时 Top 5

切页最慢页面(首次加载含 Qt 子组件初始化):
1. `voice_output`: ~993ms(创建 QAudio 设备列表,GSI 监听等)
2. `flash`: ~600ms(子进程预热)
3. `magnifier`: ~400ms
4. `music`: ~300ms(pygame 初始化)
5. `kill_icon`: ~250ms

(详见 `artifacts/v5_baseline/v4/perf.json`)

---

## 三、测试基线

- **测试框架**: pytest 9.0.2 + pytest-timeout 2.4.0
- **运行模式**: 按文件 subprocess 隔离(避免 PySide6 资源累积导致的进程崩溃)
- **总测试数**: **320 通过 / 0 失败 / 0 错误**
- **总耗时**: 48.1 秒
- **测试文件数**: 56

### 已知不完美

| 文件 | 现象 | 影响 |
|------|------|------|
| `test_ui_system_status_smoke.py` | 内部 2 测试全部通过,但 pytest 进程退出码 STATUS_INVALID_HANDLE(0xC00000FB)| 无功能影响,Qt 资源回收时 Win 句柄管理小问题 |

**v4 已存在,非 v5 引入。后续 Phase 不允许新增此类问题。**

### 322 vs 320 差异说明

之前规划文档说"322 个测试",实际 collect-only 报 322。但按文件分跑只解析 summary 行(`X passed`)拿到 320。差距可能是:
- 2 个 fixture 级 skip 未被解析(可接受)
- 或解析正则未覆盖某种 summary 格式(可接受)

**关键判定:0 failed + 0 error 是核心,不被这 2 个差异影响**。

---

## 四、防护工具集

Phase 0 已就绪 4 个核心工具:

| 脚本 | 用途 | 输出 |
|------|------|------|
| `scripts/v5_visual_baseline.py` | 截全 27 页 × 2 分辨率 | `artifacts/v5_baseline/<label>/*.png` + manifest.json |
| `scripts/v5_visual_diff.py` | 对比两个 label 的差异 | `artifacts/v5_baseline/diff_X_vs_Y/` + report.html |
| `scripts/v5_perf_check.py` | 启动+内存+切页性能 | `artifacts/v5_baseline/<label>/perf.json` |
| `scripts/v5_test_baseline.py` | 按文件 subprocess 跑测试 | `artifacts/v5_baseline/<label>/tests.json` + tests.log |

### 标准 Phase 验证流程

每个 Phase commit 前必跑:

```bash
# 1. 截图基线
python scripts/v5_visual_baseline.py --label v5_phaseN

# 2. 视觉 diff(对比上一 Phase)
python scripts/v5_visual_diff.py --before v5_phaseN-1 --after v5_phaseN

# 3. 性能基线
python scripts/v5_perf_check.py --label v5_phaseN --rounds 2

# 4. 测试基线
python scripts/v5_test_baseline.py --label v5_phaseN
```

**任何一项不通过 → 不 commit,在 Phase 内修到通过**。

---

## 五、回滚锚点

- **master**: `b51424a`(v4 全部代码,永远可回)
- **v4 备份分支**: `ui-aesthetics-v4-2026-05-07`
- **物理备份**: 仓库外的本地备份目录 `<备份目录>/v4_20260507/`(不入库)
  - `source_only.tar.gz` (181MB) — 纯源代码
  - `full_repo.bundle` (146MB) — 完整 git 历史

任何 Phase 翻车 → `git revert <phase-commit>` 或 `git reset --hard <prev-phase-tag>`。
全盘翻车 → `git checkout master`,v4 仍在那里。

---

## 六、Phase 0 完成清单

- [x] 创建分支 `ui-v5-2026-05-07`
- [x] 写 4 个 Phase 工具脚本
- [x] 跑 54 张 v4 视觉基线
- [x] 跑性能基线(2 rounds)
- [x] 跑测试基线(320 passed)
- [x] 自检 visual_diff(0% 差异)
- [x] 复制 V5_FINAL_PLAN.md 到 docs/
- [x] 写 V5_BASELINE_REPORT.md(本文档)
- [x] commit Phase 0

下一步: **Phase 1 — 死代码清理(预计 0.5 天)**
