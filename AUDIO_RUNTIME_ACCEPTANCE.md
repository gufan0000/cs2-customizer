# 音频实战验收模板

本文用于本地对局实测时，快速确认音频链路是否完整打通。

## 1. 目标

验证以下链路在真实对局中满足“触发 -> 选样式 -> 懒加载/播放 -> 日志可追踪”。

- 击杀音效
- 击杀语音
- 枪声替换
- 死亡音效
- 切枪音效
- 换弹音效
- 投掷物音效
- C4 音效
- 低血量警告
- 回合音效

## 2. 开始前准备

1. 确认软件“基础设置”中已开启对应音频开关。
2. 对应页面样式不要是 `0 / 不启用`。
3. 先执行一次体检，避免资源或配置本身异常。

```powershell
python audio_health_check.py
```

## 3. 实战执行步骤

1. 启动软件并进入本地练习或任意可稳定触发事件的对局。
2. 在 5~15 分钟内至少触发一次以下动作：
- 击杀（最好含普通击杀与爆头）
- 开枪（至少一种已配置枪）
- 切枪
- 换弹
- 死亡
- 扔一次手雷
- 下包一次
- 血量从高于阈值降到阈值以下
- 至少经历一次回合开始/结束
3. 对局后执行日志审计脚本：

```powershell
python audio_event_audit.py --minutes 30 --show-lines 8
```

## 4. 快速通过标准

执行日志审计后，建议至少满足：

- `kill_events >= 1`
- `voice_events >= 1`（若开启击杀语音）
- `gun_events >= 1`
- `switch_events >= 1`（若开启切枪）
- `reload_events >= 1`（若开启换弹）
- `death_events >= 1`（若开启死亡音效）
- `grenade_events >= 1`（若开启投掷物）
- `c4_events >= 1`（若开启 C4）
- `health_events >= 1`（若开启低血量警告）
- `round_events >= 1`（若开启回合音效）
- `errors == 0`

可用命令一次性卡验收门槛：

```powershell
python audio_event_audit.py `
  --minutes 30 `
  --require kill_events `
  --require gun_events `
  --require switch_events `
  --require reload_events `
  --require death_events `
  --require grenade_events `
  --require c4_events `
  --require health_events `
  --require round_events `
  --fail-on-errors
```

## 5. 失败时排查顺序

1. 先看 `errors` 分类中最近几条日志。
2. 再看对应事件分类是否有触发线索（比如 `switch-`、`reload-`、`voice-`）。
3. 若无触发日志，优先检查：
- 对应功能开关是否开启
- 样式是否仍为 `0`
- 资源目录是否存在有效音频文件（mp3/wav/ogg）
4. 再执行体检确认是否有失效引用：

```powershell
python audio_health_check.py
```

## 6. 脚本说明

`audio_event_audit.py` 默认行为：

- 自动读取 `%LOCALAPPDATA%\FanTool\logs` 下最新 `fanpai_*.log`
- 默认只统计最近 20 分钟
- 默认输出每类最后 6 条命中日志

常用参数：

- `--minutes N`：统计最近 N 分钟，`0` 表示不过滤时间
- `--show-lines N`：每个分类显示 N 条日志
- `--require <category>`：要求某分类至少有 1 条日志，可重复传参
- `--fail-on-errors`：若发现错误日志则返回非 0
- `--log-file <path>`：手动指定日志文件
