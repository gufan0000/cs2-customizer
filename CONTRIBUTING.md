# 贡献指南

感谢你愿意为 **CS2 Customizer （CS2 个性化定制）** 出力。本文写的都是这个仓库真实在用的规矩，
不是模板套话——尤其是「判据纪律」那一节，它是这个项目区别于大多数桌面工具的地方，请务必读完。

本项目以 **GPL-3.0** 发布。提交贡献即表示你同意你的代码以同一许可证发布（见文末 DCO）。

---

## 一、先对齐边界：什么会被接受，什么不会

本仓库是闭源商业版的**功能子集**，有几条边界是产品决策，不接受 PR 推翻：

| 不接受 | 原因 |
| --- | --- |
| 账号 / 登录 / 鉴权 | 开源版不做账号体系，相关代码已从仓库物理删除 |
| 云端配置同步 | 同上，且会给 fork 出去的客户端带上服务端依赖 |
| 在线更新检查 | 开源版不做版本封杀，也不该让 fork 继续打原作者的服务器 |
| 音乐平台在线解析 / 抓流下载 | 音乐播放器**只播本地文件**，这是明确的产品决策 |
| 随仓库分发第三方素材 | 游戏音效、图标、皮肤等涉及 Riot / 腾讯 / Valve 版权，**任何 PR 都不要带素材文件** |
| 读写游戏内存、注入进程、任何提供竞技优势的功能 | 本项目只用 Valve 官方 GSI 接口 + 读写 cfg 文件，这条底线不会动 |

素材由用户自行导入（`core/resource_import_wizard.py`）。**程序在没有任何内置素材时必须能正常启动并运行**——
如果你的改动引入了「找不到某个素材就崩」的路径，那是一个 bug，不是环境问题。

欢迎的贡献：缺陷修复、判据/测试补强、性能、无障碍与排版、文档、新的准心/HUD 玩法（不越过上面那条底线）、
i18n 基础设施。功能较大的改动请**先开 issue 讨论**再动手，避免白写。

---

## 二、开发环境

- **Python 3.13**（CI 跑的是 `windows-latest` + 3.13）
- 平台：Windows 10/11。部分功能（放大镜、全局热键、VB-Cable、开机自启）是 Windows 专有的，
  非 Windows 上可以跑大部分单元测试，但跑不了完整程序。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    /  bash: source .venv/Scripts/activate

pip install -r requirements_qt.txt    # 运行程序所需
pip install -r requirements-ci.txt    # 测试所需（已 -r 包含上一行）
pip install ruff                      # lint

python main_widget.py                 # 启动
```

**不要新增第三方依赖。** 确有必要请先开 issue 说明「为什么标准库/现有依赖做不到」，
依赖表变动会连带影响打包体积、CI 缓存和安全审计口径。

---

## 三、测试纪律：必须逐文件跑

```bash
python build_tools/run_tests.py            # 全量（124 个测试文件，典型 ~45 秒）
python build_tools/run_tests.py config hud # 只跑文件名含关键词的
```

**不要用 `pytest tests/` 一把梭。** pygame / Qt 这类原生库在同一个进程里跑满全部测试文件会**原生崩溃**
（历史已知，不是偶发）。`build_tools/run_tests.py` 的全部价值就是逐文件开子进程隔离，
退出码 `0=全绿 / 1=有失败`，可以直接接 CI。

单独调一个文件时用 `python -m pytest tests/test_xxx.py -q` 是可以的（就一个文件，不触发上面的问题）。

### 日志与配置隔离

`tests/conftest.py` 已经把测试进程的配置目录、日志目录、以及配置里的 `csgo_dir`
全部重定向到临时沙箱——**这三个出口都是被真实事故推着补上的**（曾经误删过 45 个用户历史日志、
曾经每跑一次 pytest 就往真机 CS2 目录写一次 `cs2customizer.cfg`）。

但 `scripts/` 下的审计/探针脚本**不走 conftest**，手动跑它们时必须自己设隔离前缀：

```bash
# bash
CS2C_CONFIG_DIR=/tmp/fp_cfg CS2C_LOG_DIR=/tmp/fp_log python scripts/layout_overflow_audit.py ...

# PowerShell
$env:CS2C_CONFIG_DIR="$env:TEMP\fp_cfg"; $env:CS2C_LOG_DIR="$env:TEMP\fp_log"; python scripts\layout_overflow_audit.py ...
```

判断标准很简单：**跑完仓库外面不该多出、少掉或改动任何文件。**
`tests/test_audit_side_effects_r9a.py` 里有判据在看着这件事，别把它绕过去。

---

## 四、判据纪律（本项目的核心规矩）

这里说的「判据」= 测试或审计脚本里**真正在看着某件事**的那条断言。

> **一条假绿的判据比没有判据更糟**，因为它让所有人以为这块有人看着。

历史上真出现过：用 `"函数名" in 源码` 判断「调用了某函数」，而 `import` 行本身就含那个名字——
删掉调用它照样绿。也出现过「某维度全绿」其实是那个维度**根本没有判据**。

### 规矩：新增判据必须做回退验证

`scripts/revert_verify.py` 是回退验证台：它把产品代码**按一个真实缺陷的样子改坏**，
跑对应判据，确认判据**真的会变红**，然后无条件还原文件。

新增判据时，往 `REVERTS` 列表里加一条：

```python
Revert(
    "R12",                                    # 分组（用你这轮工作的代号）
    "T 型竖杆画成完整十字",                     # 这个断点在模拟什么改动
    "crosshair_overlay.py",                   # 相对仓库根的文件路径
    "    sx, sy = rot(0, half)\n    _draw_line(painter, cx, cy, sx, sy)",   # old：原文锚点
    "    sx, sy = rot(0, half)\n    ux, uy = rot(0, -half)\n"
    "    _draw_line(painter, ux, uy, sx, sy)",                              # new：改坏后的样子
    "tests/test_crosshair_style_catalog_r9a.py::test_t_shape_has_no_pixels_above_the_center_line",
    "几何错但不报错：像素照样有，只有肉眼看得出不是 T",                        # 这条断点模拟的真实缺陷
),
```

几条硬要求：

1. **断点必须是真实发生过（或真实会发生）的缺陷，不要编。** 编出来的断点只会验证「判据能逮住它自己」。
2. **`old` 锚点在文件里必须唯一。** 出现 0 次或 ≥2 次时脚本会跳过并整体返回退出码 3，
   那说明产品代码变了、本文件该更新了。
3. 改坏的方式要贴近**真实会写错的样子**（漏一个分支、少一个字段、名表抄第二份），
   不要用 `raise` 之类必然爆炸的写法糊弄。

运行：

```bash
python scripts/revert_verify.py              # 全跑
python scripts/revert_verify.py --only R12   # 只跑某一组
```

退出码：`0` = 每条判据都逮住了它要防的缺陷；`1` = **有假绿判据**（必须修）；
`2` = 基线本来就不绿（那这次验证说明不了任何事，先修基线）；`3` = 有锚点对不上被跳过。

脚本会在开跑前给涉及文件拍字节快照、`finally` 里无条件还原。即便如此，
**请在工作区干净时跑**（强杀进程仍有留下改坏文件的风险，`git status` 一眼能看出来）。

---

## 五、代码风格

- **lint**：`ruff check .` 必须干净。配置在 `ruff.toml`（`line-length = 140`、`select = ["E", "F"]`、
  `E501` 已豁免因为中文文案行天然长）。豁免项都写了理由，新增豁免也请写理由。
- **注释用中文，写「为什么」而不是「做了什么」。** 「这里加了个 try」是废话；
  「这里必须 try：logger 不能 import config，config 第一行就 import 本模块，会循环依赖」才是本项目要的注释。
  仓库里到处是这种注释，照着写就行。
- 不要为了「统一风格」大面积重排无关代码，diff 越小越好审。

### 改了 UI 就要跑的几把尺子

这些在 CI 的 `ui-audit` 作业里是**阻断级**，本地先跑掉能省一轮往返：

```bash
# 排版审计·完整模式
python scripts/layout_overflow_audit.py --width 1200 --height 800 --themes dark,light --scales 1.0,1.1,1.25 --require-fonts

# 排版审计·紧凑模式（860×640，另一套外壳：多一条顶栏、侧边栏改浮层、可视区少 160px）
python scripts/layout_overflow_audit.py --compact --themes dark,light --scales 1.0,1.1,1.25 --require-fonts

# 对比度审计（纯色彩数学，可 offscreen）
QT_QPA_PLATFORM=offscreen python scripts/ui_contrast_audit.py

# 焦点顺序巡检（阻断级）
QT_QPA_PLATFORM=offscreen python scripts/tab_order_audit.py --verbose
```

**改布局必须两档都跑。** 完整模式和紧凑模式不是「同一套界面换个尺寸」——紧凑模式是持久化配置
（用户点一下按钮就进去了），首次纳入审计时立刻抓出三类真缺陷。只跑一档等于把另一半用户放生。

`--require-fonts` 不要去掉：offscreen 平台在无桌面会话下可能一个真实字体都没有，
那样文字度量全失真，「零截断」是**假绿**（这个坑埋了一个多月）。

字号档 `1.0,1.1,1.25` 三档也别删中间那档——有过一类缺陷只在连续走满三档时才显形。

### 改了页面文案就要重跑搜索索引

设置搜索走的是**离线生成、随包发布**的 `core/search_index.json`。
只要你动了页面上的控件文案、卡片标题、或增删了设置项：

```bash
python scripts/build_search_index.py            # 重新生成 core/search_index.json
python scripts/build_search_index.py --check    # 只校验磁盘上的索引与代码是否同步
```

并把生成的索引一起提交，否则用户搜得到旧文案、搜不到新的。

---

## 六、提交信息

中文 Conventional Commits，仓库历史里都是这个格式：

```
<type>(<scope>): <一句话说清这次改了什么、为什么>
```

`type` 用 `feat` / `fix` / `refactor` / `test` / `docs` / `ci` / `chore` / `release`。
摘要写**结论和影响**，不要写「修改了若干文件」。参考历史里的真实例子：

```
fix(ui-perf): R8d 焦点顺序——52 处报告里 50 处是判据自己的假阳性
test(version): 补上版本号四处同步的判据 —— 此前这块是完全没人看着的
docs(quality): 推翻我自己报的"注册表版本号不刷新"，真缺陷在判据通道
```

正文（可选）写背景、取舍、以及**你考虑过但没采用的方案**——这个仓库的历史注释和提交信息
被当成资料库在用，写清楚的部分半年后会救你自己。

---

## 七、DCO：每个提交都要签名

本项目使用 **DCO（Developer Certificate of Origin 1.1）**，不使用 CLA。

```bash
git commit -s -m "fix(crosshair): ..."
```

`-s` 会在提交信息末尾自动追加一行：

```
Signed-off-by: 你的名字 <你的邮箱@example.com>
```

**这一行的含义**（DCO 1.1 全文见 <https://developercertificate.org/>）：你声明这份改动
①是你本人写的、或②基于你有权提交的、与本项目许可证兼容的既有作品、或③由有权提交的人给你且你未作修改；
并且你理解这份贡献连同 `Signed-off-by` 记录会被**公开留存、随项目以 GPL-3.0 分发**。

注意事项：

- 签名用的名字和邮箱取自 `git config user.name` / `user.email`，请设成你能对外署名的真实信息。
- 忘签了：最后一个提交 `git commit --amend -s --no-edit`；一串提交 `git rebase --signoff <base>`，
  然后 `git push --force-with-lease`。
- 不接受代他人签名。

---

## 八、PR 流程与 review 期待

1. Fork → 建分支（`fix/crosshair-t-shape`、`feat/hud-color-preset` 这类）。
2. 一个 PR 只做一件事。重构和功能改动请分开提，混在一起没法审。
3. 提交前本地过一遍：`ruff check .` → `python build_tools/run_tests.py` →
   （改了 UI）两档排版审计 → （新增判据）`python scripts/revert_verify.py`。
4. 按 `.github/PULL_REQUEST_TEMPLATE.md` 逐条确认，**没做的项就如实不勾**并说明原因，
   比勾一个没跑过的框有用得多。
5. CI 必须全绿：`test` 作业（ruff + 逐文件测试矩阵）与 `ui-audit` 作业（对比度 / 两档排版 / 焦点巡检）。

review 时你大概率会被问到的问题，提前想好答案能省几轮：

- **「这条判据，把代码改坏它会变红吗？」** —— 最常见的一问，答案最好是 `revert_verify.py` 的输出。
- **「分母是多少？」** —— 说「全绿」之前先说清楚测了几个页面 × 几个主题 × 几个字号 × 哪几种模式。
  本项目已经三次栽在「全绿其实是漏了一整个维度」上。
- **「这个注释说的是为什么吗？」**
- **「删掉的这条断言是怎么让 CI 变绿的？」** —— 为了让门禁变绿而弱化/删除判据，一律不接受；
  判据本身有问题就说明它错在哪、换成什么，并给出回退验证。

维护者精力有限，PR 首次响应通常在一周内。超过两周没人理，直接在 PR 里 @ 一下就行，不算催。
