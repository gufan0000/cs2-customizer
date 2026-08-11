<!--
提 PR 前请先读 CONTRIBUTING.md。
下面的勾选项：**没做的就如实不勾并说明原因**——勾一个没跑过的框，比不勾伤害大得多。
-->

## 这个 PR 做了什么

<!-- 一两句说清改动内容。关联 issue 写 `Closes #123`。 -->

## 为什么这么改

<!--
背景、取舍、以及你考虑过但没采用的方案。
这个仓库的提交历史被当资料库在用，这一段半年后会救你自己。
-->

## 怎么验证的

<!--
写你实际跑过的命令和结果，不是「应该没问题」。
新增/修改判据的，请贴 revert_verify.py 的输出片段。
-->

---

## 自检清单

- [ ] **逐文件测试跑过了**：`python build_tools/run_tests.py`，全绿
      （不要用 `pytest tests/` 一把梭，pygame/Qt 同进程跑满会原生崩溃）
- [ ] **ruff 干净**：`ruff check .` 无输出
- [ ] **新增判据做过回退验证**：往 `scripts/revert_verify.py` 的 `REVERTS` 里加了断点，
      `python scripts/revert_verify.py --only <组>` 确认「把代码改坏它真的会变红」
      <!-- 本 PR 没有新增判据就不勾，并在下面说明为什么这次不需要判据 -->
- [ ] **改布局跑过两档排版审计**（完整 + 紧凑，缺一档等于放生一半用户）：
      - `python scripts/layout_overflow_audit.py --width 1200 --height 800 --themes dark,light --scales 1.0,1.1,1.25 --require-fonts`
      - `python scripts/layout_overflow_audit.py --compact --themes dark,light --scales 1.0,1.1,1.25 --require-fonts`
- [ ] **已 `git commit -s`（DCO）**：每个提交都带 `Signed-off-by:`，且署名与 git 配置一致
- [ ] 改了页面控件文案 / 卡片标题 / 增删设置项的，重跑了 `python scripts/build_search_index.py`
      并提交了生成的索引
- [ ] 注释写的是「为什么」，不是「做了什么」
- [ ] 没有新增第三方依赖（确有必要请先开 issue 讨论）
- [ ] 没有提交第三方版权素材、个人配置、日志、打包产物或临时目录
- [ ] 跑测试/脚本时做了隔离（`CS2C_CONFIG_DIR` / `CS2C_LOG_DIR`），
      仓库外面没有被多写、少写或改动任何文件

## 影响面

<!--
说清楚这次改动的分母：影响哪些页面 / 哪些主题 / 哪些字号 / 完整还是紧凑模式 /
有没有改配置字段（老配置能不能平滑升级）/ 有没有改 cfg 写入内容。
说「全绿」之前先说清楚测了多少个组合——本项目已经三次栽在「全绿其实是漏了一整个维度」上。
-->

## 破坏性变更

- [ ] 无
- [ ] 有（请在下方说明：影响谁、怎么迁移、老配置/老预设怎么办）
