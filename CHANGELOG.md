# 变更记录

## Unreleased

- 共享账号增加完整会话白名单，默认拒绝；命令、LLM 工具、缓存读取与通知检查授权。
- 已保存共享会话记录来源；与当前共享 sid 相同的旧会话也按共享处理。
- 整理公开仓库文档、MIT 许可、权限说明与贡献指南；排除本地迁移记录和未获公开授权的示例图片。
- 发布包改为显式运行文件清单，排除凭据、状态、缓存与开发依赖。

## 0.8.0

- 支持**引用消息里的图片**：通过 OneBot `get_msg`（必要时再 `get_image`）取回被引用消息中的图片，
  和当前消息的附件一起用于上传/预览；读不到时给出明确提示而不是“没有检测到图片附件”。
- 平台请求抗抖动：连接超时 20s → 8s、总超时 60s → 30s，**GET 自动重试 3 次**并带退避；
  POST/PUT/DELETE 不重试（避免重复建任务）；超时/不可达统一转成可读错误。
- 平台查询加短 TTL 缓存（账号/模板 60s、任务列表 15s）：一次预览从 4 次 API 调用降到 1–2 次，
  减少踩到平台抖动（日志里出现过 33 秒的连接超时）的概率。
- LLM 工具统一包一层错误处理：工具失败返回可读文本（如“平台连接超时或不可达（已重试），
  请稍后再试”），不再像日志里那样只留下空的 `error:`。
- 测试 99 → 103。

## 0.7.3

- 头像取值链补全：平台账号 `avatar`（B站 face）→ 平台没存时按 `uid` 向 B站 查一次 face →
  本地兜底图 → 首字占位。B站 接口需要浏览器 UA，取图统一加上 UA/Referer。
- 验证：容器内实测能从 hdslb 拉到真实 face 并渲染成圆形头像；平台 `maskAccount` 只打码
  `sessdata`/`bili_jct`，`avatar` 会原样返回。

## 0.7.2

- 左上角头像明确为**待发布账号的 B站头像**（按账号缓存）；`preview_avatar` /
  `resources/avatar.png` 改为**兜底**，只在平台账号没有头像时使用，不再覆盖 B站头像。
- 新增测试：平台头像存在时必须优先于兜底图；账号无头像时回退到兜底图。

## 0.7.1

- 按反馈调整：组头像就放**左上角**（默认取平台账号头像），**去掉右上角的组徽标**。
  `preview_logo` 配置项与渲染逻辑移除，改为 `preview_avatar`：填 URL/本地路径覆盖左上角头像，
  或把 `avatar.png` 放进数据目录 `resources/` 自动生效（`scripts/fetch_assets.py --avatar`）。
- 卡片项仍是 22 个（`preview_logo` → `preview_avatar`）。

## 0.7.0

- 预览卡片支持**彩色 emoji**：自动查找 `NotoColorEmoji.ttf`（数据目录/插件目录/系统路径），
  CBDT 字体只能以 109px 渲染，按行内尺寸缩放后逐字贴图并与正文基线对齐；找不到字体时自动去掉
  emoji（不再出现豆腐块）。新增 `scripts/fetch_assets.py` 一键获取字体（apt 优先，回退 HTTP）。
- 组徽标自动识别：`data/bili_platform_aux/resources/logo.png` 存在就显示在卡片右上角，
  仍可用卡片 `preview_logo` 覆盖为 URL 或本地路径。
- **修复正文/图片右侧溢出**：可用宽度误算成 700px（卡片右边界只到 690px），现在按
  `760 - 2*(20+30) = 660` 计算；新增回归测试逐像素检查卡片外不应有任何内容。
- 测试 94 → 96。

## 0.6.1

- 按反馈调整预览卡片：**去掉右上角编号徽章**（那是 B站个性装扮粉丝编号，不需要）——
  连带移除 `/bd badge` 命令、`bili_platform_set_badge` 工具与 `preview_badge` 配置项
  （卡片项 23 → 22，工具 27 → 26）。右上角只保留可选的组徽标（`preview_logo`）。
- 标题与头像/账号名之间的间距从 6px 加大到 22px。
- 更新本地预览样张（未随公开仓库分发）。

## 0.6.0

- 新增预览卡片渲染（`render.py`，PIL）：`/bd preview` 与 `bili_platform_preview` 会额外发一张图片，
  含标题、账号头像+名称、计划时间、编号徽章、组徽标、话题标签、正文、作品图片（1~9 张，1 张整宽 /
  多张两列，超高自动缩放）、底部一行文字；本地样张未随公开仓库分发。
- 新增命令 `/bd badge <文本>` 与 LLM 工具 `bili_platform_set_badge`（23 → 27 个工具）。
- 配置卡片新增 `preview_card`、`preview_footer`、`preview_badge`、`preview_logo`（19 → 23 项）。
- 图片取自平台 `/uploads/...`（公开可读）或消息附件本地文件，单张上限 12MB，失败跳过；
  头像按账号缓存；临时 PNG 放 `temp/` 并 30 分钟清理；渲染/发送失败只降级为文字预览，不影响发布。
- 有必填缺项时不渲染卡片（避免半成品误导）。
- 容器内无彩色 emoji 字体，emoji 会先被去掉，避免渲染成豆腐块。
- 测试 85 → 95（新增 `tests/test_render_card.py` 与卡片发送/降级用例）。

## 0.5.0

- 新增"缺项反问"：创建/确认前先算缺项，缺必填信息时**不创建任务**，返回"还差什么 + 怎么补"的结构化清单，
  LLM 拿到这段文字就会反问用户，而不是自己编标题/话题。
- 新增配置卡片开关 `require_title`、`require_topic`（默认关）：开启后缺标题/话题会拦住发布。
- 新增命令 `/bd title <标题>`（`无` = 不要标题）、`/bd type <原创|转载>`、`/bd topic skip`（不要话题）；
  用户明确说不要时记入草稿，必填策略不再拦。
- 新增 LLM 工具 `bili_platform_publish_options`（列模板/预设/默认值/必填策略，供模型提问）、
  `bili_platform_set_title`、`bili_platform_set_type`；工具总数 23 → 26。
- 修复：`/bd var` 补齐变量后草稿的 `missing_variables` 不刷新，导致 `/bd confirm` 一直报缺少变量。
- 修复：草稿里用 `/bd title`、`/bd type` 设的值被 `_build_plan` 丢弃（标题只取卡片/预设），
  现在草稿中"已决定"的标题和类型优先。
- 调整：`create` 限流从"构建计划"移到"真正创建任务"，预览和被拦住的反问不再消耗配额。
- 文档：USAGE 新增「4.6 缺项反问与必填策略」，LLM 工具清单改为从代码生成，避免文档漂移；测试 72 → 85。

## 0.4.0

- 时间解析支持中文自然语言：`明天上午八点`、`明早8点`、`今晚8点`、`今晚八点半`、
  `晚上七点一刻`、`9点30分`、`凌晨12点`、`中午`、`后天中午12点`、`下周三晚上7点`、
  `周三下午两点`、`三十分钟后`、`两小时后`、`三天后`、`1周后`。
- 中文数字支持 `零一二三四五六七八九十两`（到 59）；`凌晨12点` 视为 00:00，
  `中午` 12 点起，`下午/晚上` 小于 12 点自动 +12；未写日期时按今天、已过顺延到次日。
- 机器格式（`+30m`、`20:00`、ISO、时间戳）行为不变且优先级更高；新增 25 条时间解析用例，
  测试总数 70 → 72（含 23 条中文用例表）。
- 命令帮助与 `USAGE.md` 的时间格式说明同步更新，并修正文档里错位的小节编号。

## 0.3.2

- `sid` 输入兼容常见粘贴形态：纯值、`sid=值`、`SID=值`、带引号的值、整条 Cookie 字符串
  （`foo=1; sid=xxx; bar=2`），统一由 `normalize_sid()` 提取纯值；配置卡片、
  `BILI_PLATFORM_SID` 环境变量、`admin_cli.py set-session --sid` 三条入口都走同一套处理。
- 配置卡片里 `sid` 的 hint 明确说明不需要带 `sid=` 前缀。

## 0.3.1

- 修复配置卡片里**看不到“平台会话 sid”**：`invisible` 在 AstrBot 的卡片渲染里表示“整项不显示”
  （前端 `!item.invisible` 才渲染），不是密码框。已移除该标记并补上 `obvious_hint`，
  同时新增回归测试：卡片每一项都必须可见，且与代码里读取的配置项一一对应。
- `sid` 的 hint 补充了获取方式（浏览器 F12 → Cookies）与明文存储提醒。

## 0.3.0

- 新增 AstrBot WebUI 插件配置卡片（`_conf_schema.json`，17 项）：平台地址、主机白名单、
  平台会话 `sid`、展示账号名、默认（专用）B站账号、模板、标题、话题、内容类型、
  模板变量/署名槽位 JSON、单张图片上限、群聊写操作是否仅管理员、是否允许密码登录、
  发布通知开关与轮询间隔。
- 配置优先级明确为：插件配置卡片 > 环境变量 > 内置默认值，再叠加用户发布预设和单次覆盖。
- 配置卡片里配了 `account_id` 但账号不在平台列表时改为**显式报错**，不再静默回退到
  其他 B站账号（避免用错账号发布）。
- 新增测试：`_conf_schema.json` 的类型必须属于 AstrBot 支持的集合（不支持的类型会让
  整个插件加载失败），以及卡片各项确实生效；测试总数 53 → 66。
- `scripts/deploy_remote.sh` 重启后自动探测 WebUI 端口，若 60 秒内未就绪则再重启一次，
  规避第三方插件 `api.stardots.io` 更新检查卡死启动的已知问题。

## 0.2.1

- 修复 `bili_platform_logs` 的 docstring 参数类型 `integer`：AstrBot 在导入插件时只接受
  `string`/`number`/`object`/`array`/`boolean`，原写法会让整个插件加载失败，现改为 `number`，
  并新增回归测试扫描全部 `llm_*` 工具的 docstring 类型。
- 补齐 7 个文档中承诺但未实现的 LLM 工具：`bili_platform_preview`、
  `bili_platform_confirm`、`bili_platform_set_var`、`bili_platform_topic_search`、
  `bili_platform_topic_use`、`bili_platform_mention_search`、`bili_platform_mention_add`；
  LLM 工具总数为 23 个，README 与 USAGE 的工具清单已与实现对齐。
- 部署流程补充：上传前先在容器内 `import data.plugins.bili_platform_aux.main` 做预检，
  可提前发现加载期错误。

## 0.2.0

- 新增 `/bd edit <任务ID> <JSON>` 与 `bili_platform_job_edit`：编辑待发布任务并重新排队；
  只允许编辑 `pending` 任务，`publishing`/`published` 会提示改用 `/bd duplicate`；
  `scheduledAt` 支持自然语言时间。
- 新增 `/bd notify on|off` 与后台发布结果通知：任务变为 `published`/`failed` 时推送，
  会话过期（HTTP 401）时清除本地 `sid` 并提示重新登录；首次轮询只建立基线，状态未变化
  不重复推送；通知发往最近一次使用 `/bd` 的会话。
- 群聊写操作边界：群成员仍可查询、草稿、预览、搜索话题和 @用户；上传、导入、发布、编辑
  和任务操作仅管理员可用，私聊不受限制（AstrBot `is_admin()` 或 `raw_message.sender.role`）。
- 自然语言时间：`今天20:00`、`明天08:00`、`后天09:30`、`下周一09:00`、`下周日9:30`；
  同时修正正则里 `\s`/`\d` 写成字面反斜杠导致这些格式全部解析失败的问题。
- 修复 `_topic_results` / `_mention_results` 未初始化，导致 `/bd topic`、`/bd mention`
  抛 `AttributeError` 的问题。
- 修复 `_execute_plan` 中引用未定义 `lines` 的重复提醒代码；重复正文提醒改为出现在预览里。
- 任务操作校验 `action` 取值，非法值不再静默返回成功。
- 核对平台源码：`PUT /api/jobs/:id`、`POST /api/jobs` 字段与上传限制（单张 20MB、最多 9 张）
  一致，`published` / `failed` / `dynamicUrl` / `lastError` 字段名与通知逻辑一致。

## 0.1.0

- 首个可用版本：平台登录、账号/模板/预设、上传、预览确认、发布与定时、队列与任务管理、
  图库、话题与 @提及、LLM 工具；全部通过 380nm 平台 REST API 操作，不维护本地任务队列。

