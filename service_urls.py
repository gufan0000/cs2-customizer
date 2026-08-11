"""对外服务端点。

开源版说明
----------
本项目**默认不连接任何服务器**。

上游闭源版在这里配置了官网、社区站、账号服务、在线更新与遥测端点。开源版全部去掉了，
原因不只是"少一个功能"：

- 账号 / 云同步 / 在线更新链路已整体移除，相关端点没有消费者；
- 遥测端点若保留默认值，**每一个 fork 出去的客户端都会继续向原作者的服务器打点**——
  带宽是原作者的，收到的崩溃堆栈里的用户数据责任也是原作者的，
  而那些用户已经不是他的用户。这对双方都不合理。

因此 TELEMETRY_BASE_URL 默认为空字符串，core/usage_reporter.py 与
core/crash_reporter.py 在基址为空时直接不发送。自行部署服务端的人填上即可启用。

隐私说明见仓库根目录的 PRIVACY.md。
"""

# 项目主页。用于「关于」页与错误提示中引导用户反馈问题。
PROJECT_HOMEPAGE = "https://github.com/OWNER/cs2-customizer"
PROJECT_ISSUES_URL = f"{PROJECT_HOMEPAGE}/issues"

# 遥测基址。**默认为空 = 不发送任何数据。**
# 填成自建服务的根地址（如 "https://example.com"）即可启用，
# 上报器会在其后拼 /api/usage_report.php 与 /api/crash_report.php。
TELEMETRY_BASE_URL = ""
