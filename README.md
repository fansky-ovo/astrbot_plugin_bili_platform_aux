# 380nm 平台管理助手 · AstrBot 插件

通过 AstrBot 群聊、私聊或 LLM 工具管理已有的 [380nm B站动态发布平台](https://github.com/umeabc/380nm)。

账号、模板、图片、发布任务和日志由平台统一保存。插件提供聊天入口、草稿预览与结果通知，不维护独立发布队列，Web 后台与机器人共享平台任务状态。本项目是独立的集成插件。

## 功能

- 查询平台账号、模板、图库、任务和日志。
- 上传图片、调用平台链接导入，设置正文、标题、话题与署名。
- 草稿预览、确认创建任务、定时发布、任务编辑与状态操作。
- 发布成功或失败通知，支持群内写操作权限与共享账号会话白名单。
- AstrBot WebUI 配置卡片及 LLM 工具；不提供登录类 LLM 工具。

## 快速开始

需要已有的 380nm 平台账号、可访问的 API，以及支持本插件所用 API 的 AstrBot 4.x 环境。开发测试使用 Python 3.11/3.12；尚未建立覆盖各 AstrBot/380nm 版本的兼容矩阵。

1. 将本仓库目录放到 AstrBot 的 `data/plugins/bili_platform_aux`，保留根目录下的 `main.py`、`metadata.yaml` 等文件。
2. 在 AstrBot 使用的 Python 环境安装 `requirements.txt`，通过 WebUI 重载插件。
3. 配置平台地址与主机白名单，再选择登录方式：
   - **个人账号**：在服务器用 `admin_cli.py set-session --owner <用户ID>` 绑定个人平台会话，建议使用隐藏输入；详见手册。
   - **共享账号**：配置 `sid`，同时填写 `shared_session_whitelist`。默认空白名单禁止共享账号访问。
4. 先运行 `/bd status`、`/bd accounts` 验证连接，再使用发布功能。

会话白名单填写 AstrBot 的完整 `unified_msg_origin`，多个条目以逗号或换行分隔。群聊授权不会延伸到成员私聊；白名单外需要个人账号。群内写操作默认仍只允许管理员执行。详情见 [权限边界](docs/PERMISSIONS.md)。

WebUI 中的 `sid` 会明文保存在 AstrBot 的配置文件中；本插件保存的用户会话使用 Fernet 加密。不要把运行配置、Cookie、密钥或状态文件提交到仓库。`.env.example` 仅是变量示例，插件不会自动加载 `.env`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `/bdhelp` | 查看全部命令 |
| `/bd status`、`/bd accounts` | 查询会话与账号 |
| `/bd upload` | 上传当前消息图片 |
| `/bd preview <正文>` | 预览发布内容 |
| `/bd confirm` | 确认草稿并创建平台任务 |
| `/bd schedule <时间> || <正文>` | 创建定时任务 |
| `/bd queue`、`/bd job <任务ID>` | 查询平台任务 |
| `/bd notify on|off` | 开关结果通知 |

部分命令会直接创建或修改平台任务，使用前请阅读 [完整手册](USAGE.md)。密码登录默认关闭。

## 文档与开发

- [使用手册](USAGE.md)：安装、配置、命令、排障与部署。
- [权限边界](docs/PERMISSIONS.md)：共享账号、个人账号、群写权限及当前限制。
- [开发指南](CONTRIBUTING.md)：依赖、离线测试与提交约定。
- [安全报告](SECURITY.md)、[变更记录](CHANGELOG.md)、[第三方说明](THIRD_PARTY_NOTICES.md)。

```bash
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t .
python scripts/package.py --out dist
```

单元测试使用 AstrBot stub、假客户端或 HTTP MockTransport，不代表真实平台发布已验证。打包脚本只收录显式允许的运行文件，不包含运行数据、配置、开发依赖或本地示例图。

## 许可证

本插件采用 [MIT](LICENSE)。380nm 上游同样采用 MIT，版权归其原作者所有，见 [第三方说明](THIRD_PARTY_NOTICES.md)。
