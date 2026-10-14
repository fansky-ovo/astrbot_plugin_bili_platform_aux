# 开发约定

本目录为独立的 380nm 平台管理插件。平台拥有账号、模板、图片、任务与日志；插件通过 REST API 操作平台，不新增独立发布队列。不要混入 astrbot_plugin_bili_dynamic 或彩翻业务。

修改前阅读 README.md、USAGE.md、CHANGELOG.md 和相关模块。保持用户/会话隔离、群写操作管理员校验、预览确认流程及敏感字段脱敏。不记录真实凭据。测试使用 stub / MockTransport，不调用真实发布 API。

本地验证：`python -m unittest discover -s tests -t .`。运行环境为 AstrBot；本目录不是独立平台服务。部署、推送和生产写操作需用户明确授权。

公开提交前运行 `python scripts/check_public_files.py`。打包使用 scripts/package.py 的显式运行文件清单，新模块需同步清单。MIGRATION.md、真实账号示例图和开发依赖仅在本地保留，不提交或打包。权限规则见 docs/PERMISSIONS.md。
