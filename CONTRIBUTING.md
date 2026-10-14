# 开发与贡献

## 本地环境

使用 Python 3.11 或 3.12，从仓库根目录执行：

```bash
python -m venv .venv
# 激活虚拟环境后执行
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t .
python scripts/check_public_files.py
```

测试使用最小 AstrBot stub、假客户端与 httpx.MockTransport，不启动 AstrBot，不访问真实平台。请勿为单元测试配置生产 sid。真实宿主兼容性和平台接口需要另行验证，离线通过不代表发布流程已联调。

## 修改约定

- 平台拥有任务状态；不新增独立发布任务系统。
- 保留会话白名单、群管理员限制、任务范围检查及敏感值脱敏。
- 新增命令或 LLM 工具时，同时更新手册和权限测试；LLM 工具 docstring 保留 Args 描述。
- 修复和功能分别提交，说明行为变化、验证方式和兼容性影响。
- 不提交 Cookie、密码、私钥、运行数据、开发环境、真实群号或未经授权的图片。

## 打包

```bash
python scripts/package.py --out dist
```

默认模块目录为 `bili_platform_aux`。打包只收录显式允许的运行文件；新运行模块需同步更新打包清单。提交前运行单元测试并检查压缩包内容。没有提交历史时版本标记为 `nogn`，正式发行请在提交后生成包。

部署脚本面向已有 Docker 宿主，会备份插件并重启指定容器；先阅读脚本与 USAGE.md，不要在本地开发或 CI 中调用真实部署。提交 PR 不等于授权生产部署。

贡献内容按本仓库 MIT 许可证提供；引用第三方代码或资源时保留其许可和来源。
