# 第三方依赖与归属声明（THIRD-PARTY NOTICES）

本文件列出 CS2 Customizer 运行、构建、测试所依赖的第三方软件及其授权信息，
以满足 GPL-3.0-or-later 与各依赖自身许可证的归属（attribution）要求。

本项目自身的代码以 **GPL-3.0-or-later** 授权，见仓库根目录 `LICENSE`。
下列第三方组件**不受**本项目许可证约束，各自适用其原始许可证。

版本约束取自仓库内的 `requirements_qt.txt` / `requirements-ci.txt` / `requirements-build.txt`。
这些文件只锁下限（`>=`），因此**某次具体发布实际装了哪些精确版本**，以该次发布随附的
`requirements.lock.txt`（由 `build_tools/freeze_release_deps.py` 生成的 `pip freeze` 快照）为准。
本文件描述的是依赖**集合与授权性质**，不是精确版本清单。

---

## 一、本仓库不含任何第三方素材

这一条单独列出，因为它是本仓库与闭源版本最大的分发差异：

- 仓库中**不分发**任何音效、语音、击杀图标、字体、贴图或其他游戏相关素材文件。
- 原闭源版本内置的素材涉及第三方（含 Valve、Riot Games、腾讯等）的版权，
  **已在开源裁剪时物理删除，且不会以任何形式重新加入本仓库。**
- 程序在**没有任何内置素材**的情况下必须能正常启动与运行；素材由用户自行准备并通过
  「资源导入向导」（`core/resource_import_wizard.py`）从本地导入。
- 用户自行导入的素材，其合法性与授权由用户自己负责，与本项目无关。

仓库里的图形文件（程序图标 `icon.ico` / `myicon.ico`、安装向导图、启动闪屏、
社交预览图）**全部由本仓库的代码生成**，不含任何第三方素材：

| 文件 | 生成器 |
| --- | --- |
| `icon.ico` · `myicon.ico` · `build_tools/installer_assets/setup_icon.ico` | `build_tools/make_app_icon.py` |
| `splash.png` · `installer_assets/wizard_*.bmp` | `build_tools/make_installer_assets.py` |
| `docs/images/social-preview.png` | `scripts/make_social_preview.py` |
| `docs/images/*.png`（界面截图） | `scripts/capture_readme_shots.py` |

它们和其余代码一样依 GPL 授权。`tests/test_brand_assets.py` 会验证入库的这几份
与生成器的产物逐字节一致——**位图一旦入库就会和生成器脱钩，而脱钩是静默的**。

不在 GPL 范围内的只有**文字标识**（项目名称），详见 `NOTICE`。

---

## 二、PySide6（Qt for Python）——单独说明

PySide6 是本项目唯一一个需要展开讨论授权的依赖，因为它是 UI 的基础框架，
且采用 **LGPL-3.0 / 商业** 双授权。

| 项目 | 内容 |
| --- | --- |
| 组件 | `PySide6`（含 `shiboken6` 绑定运行时） |
| 版本约束 | `>=6.6.0` |
| 许可证 | LGPL-3.0 或 商业许可（双授权，由使用方选择其一） |
| 上游 | https://wiki.qt.io/Qt_for_Python |
| 授权全文 | https://doc.qt.io/qtforpython/licenses.html |

### 2.1 本项目选择哪一侧

本项目采用 **LGPL-3.0 一侧**，不使用、也不需要 Qt 商业许可。

GPL-3.0 与 LGPL-3.0 是兼容的：LGPL-3.0 在正文中声明它"以 GPL-3.0 的条款为基础，
再附加若干额外许可"（additional permissions）。因此把 LGPL-3.0 的库并入一个
GPL-3.0 的作品是被明确允许的——GPL-3.0 是更强的一侧，整体作品按 GPL-3.0-or-later 分发，
其中 PySide6/Qt 部分仍然保持 LGPL-3.0。

**注意方向性**：兼容是单向的。你可以把 LGPL 库用进 GPL 程序；
反过来不能把本项目的 GPL 代码降级成 LGPL 或私有授权。

### 2.2 LGPL 第 4 条：动态链接与用户的"重新链接"权利

LGPL-3.0 第 4 条（Combined Works）规定：当你分发一个"把 LGPL 库结合进来的作品"时，
必须保证**最终用户有能力用他自己修改过的库版本替换掉你附带的那一份**，并让程序继续工作。
第 4(d) 条给了两条二选一的路：

- **4(d)(0) —— 共享库机制**：程序在运行时使用用户系统上**已存在**的那份库，
  并且能与接口兼容的、经用户修改的库版本正常协作。
- **4(d)(1) —— 提供可重新组合的形式**：随作品提供"最小对应源码"（Minimal Corresponding Source）
  以及应用侧的目标代码/源码，其形式与授权条款要允许用户把应用与**修改过的**库版本
  重新组合或重新链接，产出修改后的合并作品。

此外第 4(a)~(c) 条要求：在作品和随附文档中显著声明用到了本库、声明其受 LGPL 覆盖，
并随作品提供 GPL 与 LGPL 的许可证副本。

**本项目如何满足：**

1. **声明**：即本文件本节，以及 `NOTICE`。
2. **许可证副本**：仓库根 `LICENSE` 为 GPL-3.0 全文；LGPL-3.0 全文见
   https://www.gnu.org/licenses/lgpl-3.0.txt ，同时 PySide6 发行包内自带
   `PySide6/licenses/` 目录，随打包产物一同落盘。
3. **链接方式**：Python 层通过 `import PySide6` 在运行时加载 `.pyd` / `.dll`，
   属于动态链接，从未静态链接 Qt。
4. **重新链接能力**：本项目**全部源码以 GPL-3.0-or-later 公开**，
   任何人都可以拿到完整源码 + 构建脚本（`build_tools/build_release.py`）自行重建，
   因此第 4(d)(1) 的要求被自然满足——用户拿到的不是"仅二进制 + 一堆胶水"，
   而是从头可复现的完整源码。

### 2.3 PyInstaller 打包成单体产物时怎么办

这是实践中最容易出错的一环，单独讲清楚。

`build_tools/build_release.py` 支持两种打包形态（`--mode`）：

- **`onedir`（推荐，安装包形态用的就是这个）**
  Qt 的 DLL、`PySide6/` 目录、各 `.pyd` 以**独立文件**形式平铺在产物目录里。
  用户想换成自己编译的 Qt，直接覆盖同名文件即可，无需任何特殊工具——
  这是对 LGPL 第 4 条最干净的满足方式，也是本项目发布安装包时采用的形态。

- **`onefile`（单文件 exe）**
  PyInstaller 把所有内容打进一个自解压归档，运行时释放到临时目录再加载。
  Qt 依然是**动态**加载的（不是静态链接），所以并不违反 LGPL 的链接前提；
  但"用户能不能替换那份库"就不再显然了——归档是私有格式，普通用户无法就地替换。

  **单文件形态下满足第 4 条的做法（本项目采用第 1 条）：**

  1. **公开完整源码**（本项目已做）。整个作品是 GPL-3.0-or-later，源码、
     `.spec` 生成逻辑、构建脚本全部在仓库里，任何人都能替换 PySide6 版本后重新打包。
     这直接落在第 4(d)(1) 的"提供可重新组合的形式"上，是最省事也最彻底的一条路。
  2. **同时提供 onedir 产物**作为可替换版本，让不想自己构建的用户也有替换途径。
  3. **随产物附上本文件与许可证副本**，说明所用 PySide6/Qt 的版本与获取地址。

  > 如果哪天有人基于本项目做**闭源**分发（那已经违反本项目的 GPL 了，此处仅作提醒），
  > 单文件打包 + 不给源码会**同时**违反 GPL-3.0 和 LGPL-3.0 第 4 条。
  > 开源分发不存在这个问题，因为源码本身就是最强的"可重新链接"形式。

---

## 三、运行时依赖

来自 `requirements_qt.txt` 及 `requirements-ci.txt` 中运行时实际 import 的部分。

| 依赖 | 版本约束 | 许可证 | 项目主页 | 备注 |
| --- | --- | --- | --- | --- |
| PySide6 | `>=6.6.0` | LGPL-3.0 / 商业（本项目取 LGPL-3.0） | https://wiki.qt.io/Qt_for_Python | 见上文第二节 |
| qtawesome | `>=1.4.0` | MIT（Python 代码） | https://github.com/spyder-ide/qtawesome | **捆绑的图标字体另有授权**，见 3.1 |
| pygame | `>=2.6` | LGPL-2.1-or-later | https://www.pygame.org/ | 音频播放与闪光子进程渲染；"or later"使其可升到 LGPL-3.0，与 GPL-3.0 兼容 |
| Flask | `>=3.0` | BSD-3-Clause | https://flask.palletsprojects.com/ | 本地 GSI 接收服务（仅监听 127.0.0.1） |
| Pillow | `>=12.2.0` | MIT-CMU（HPND 系，即"PIL Software License"） | https://python-pillow.github.io/ | 用户导入图片的解码；下限受安全公告约束 |
| numpy | `>=1.26` | BSD-3-Clause | https://numpy.org/ | 音量归一化等音频数值处理 |
| sounddevice | `>=0.4` | MIT | https://github.com/spatialaudio/python-sounddevice | 语音输出；底层 PortAudio 为 MIT |
| SoundFile | `>=0.12` | BSD-3-Clause | https://github.com/bastibe/python-soundfile | **捆绑 libsndfile（LGPL-2.1-or-later）**，见 3.2 |
| keyboard | `>=0.13` | MIT | https://github.com/boppreh/keyboard | 全局热键 |
| pynput | `>=1.7` | LGPL-3.0-or-later | https://github.com/moses-palmer/pynput | 输入监听；LGPL-3.0 与本项目 GPL-3.0 兼容 |
| pywin32 | `>=306` | PSF 系许可证（**待核实**具体版次） | https://github.com/mhammond/pywin32 | Windows API；见"待核实"一节 |
| pypinyin | `>=0.53` | MIT | https://github.com/mozillazg/python-pinyin | 设置搜索的拼音层 |
| pycaw | 无下限（Windows 限定） | MIT | https://github.com/AndreMiras/pycaw | 进程级音量 Ducking，可选 |
| comtypes | 无下限（Windows 限定） | MIT | https://github.com/enthought/comtypes | pycaw 的 COM 依赖 |
| requests | `>=2.33.0` | Apache-2.0 | https://requests.readthedocs.io/ | HTTP 客户端 |
| urllib3 | `>=2.7.0` | MIT | https://urllib3.readthedocs.io/ | requests 的传输层，此处显式锁安全下限 |

### 3.1 qtawesome 捆绑的图标字体

qtawesome 的 **Python 代码**是 MIT，但它随包分发的字体文件各有各的授权，
使用时（尤其是二次分发产物）需要保留各字体自带的授权文件：

- Font Awesome —— 字体 SIL OFL 1.1，图标 CC BY 4.0，代码 MIT（https://fontawesome.com/license）
- Material Design Icons —— Apache-2.0 / SIL OFL 1.1（https://pictogrammers.com/docs/general/license/）
- Elusive Icons —— SIL OFL 1.1（http://elusiveicons.com/）
- Remix Icon —— Apache-2.0（https://remixicon.com/）
- Microsoft Codicons —— CC BY 4.0（https://github.com/microsoft/vscode-codicons）
- Phosphor Icons —— MIT（https://phosphoricons.com/）

具体随附哪几套、各套的确切版本，以所装 qtawesome 版本的 `qtawesome/fonts/` 目录
及其中的授权文件为准（**待核实**：不同 qtawesome 版本收录的字体集合会变）。

### 3.2 SoundFile 捆绑的 libsndfile

`soundfile` 的 Python 封装是 BSD-3-Clause，但其 wheel 里捆绑的原生库
**libsndfile 为 LGPL-2.1-or-later**（https://libsndfile.github.io/libsndfile/）。
"or later" 使其可以按 LGPL-3.0 使用，与本项目的 GPL-3.0-or-later 兼容。
它同样是动态加载的共享库，第 2.2 节关于 LGPL 第 4 条的分析同理适用：
公开完整源码即满足重新链接要求。

---

## 四、构建期与测试期依赖

这些依赖**不进入**最终产物的可执行逻辑（PyInstaller 的引导程序除外），
但列出以保证依赖链可审计。

| 依赖 | 版本约束 | 许可证 | 项目主页 | 备注 |
| --- | --- | --- | --- | --- |
| PyInstaller | `>=6.21,<7` | GPL-2.0-or-later **+ 引导程序例外条款** | https://pyinstaller.org/ | 见下方说明 |
| pytest | `>=8.0` | MIT | https://docs.pytest.org/ | 仅测试期 |

**PyInstaller 的例外条款**：PyInstaller 本体是 GPL-2.0-or-later，但它对
**bootloader（引导程序，会被写进最终 exe）** 附加了一条例外许可，
明确允许用它打包**任意授权**的应用程序，包括专有软件，而不会因此传染 GPL。
因此使用 PyInstaller 不会给本项目的授权带来额外约束；
本项目本来就是 GPL-3.0-or-later，更不存在冲突。
例外条款原文见 PyInstaller 仓库的 `COPYING.txt`。

---

## 五、主要传递依赖

以下由上表依赖自动引入，未在 `requirements*.txt` 中直接声明。
列出常见的几项供审计参考；**完整且精确的清单以该次发布的 `requirements.lock.txt` 为准**。

| 依赖 | 许可证 | 引入者 |
| --- | --- | --- |
| shiboken6 | LGPL-3.0 / 商业 | PySide6 |
| Werkzeug / Jinja2 / click / itsdangerous / blinker / MarkupSafe | BSD-3-Clause | Flask |
| certifi | MPL-2.0 | requests |
| charset-normalizer | MIT | requests |
| idna | BSD-3-Clause | requests |
| cffi / pycparser | MIT | sounddevice、SoundFile |
| PortAudio（原生库） | MIT | sounddevice |
| libsndfile（原生库） | LGPL-2.1-or-later | SoundFile |

---

## 六、待核实

以下条目未做上游取证，**刻意不猜**，标注在此等待核实后再定稿：

1. **pywin32 的许可证版次**。上游历史上使用 PSF（Python Software Foundation）系许可证，
   但具体是哪一版、以及各子包（`win32`、`pythoncom`、`pythonwin`）是否一致，需要
   查阅所装版本 dist-info 里的 `LICENSE.txt` 后确认。
2. **qtawesome 具体收录的字体集合与版本**。随 qtawesome 版本变化，需按实际安装版本
   的 `qtawesome/fonts/` 目录清点。
3. **pycaw / comtypes 在 `requirements_qt.txt` 中没有版本下限**，
   实际装到哪个版本取决于构建机环境；发布时应以 `requirements.lock.txt` 固定。
4. **`requests` / `urllib3` 是否仍属必需**。这两项在闭源版本中主要服务于账号登录与
   更新检查链路，而这两条链路已在开源裁剪中删除。当前仓库内仍有模块 import `requests`
   （崩溃/使用情况上报、HTTP 会话封装）。若这些模块最终也被移除，
   应同步把 `requests` / `urllib3` 从 `requirements_qt.txt` 中删掉，并更新本文件。
5. **Qt 模块级授权差异**。Qt 中个别模块（如 Qt Charts、Qt Data Visualization）
   在开源侧是 GPL-3.0 而非 LGPL-3.0。本项目当前未使用这些模块；
   若将来引入，需要在本节重新评估。

---

## 七、如何反馈授权问题

如果你发现本文件的授权标注有误、遗漏了某个依赖，或某项归属声明不符合上游要求，
请通过仓库 issue 指出。授权信息宁可标"待核实"，也不接受猜测填入。
