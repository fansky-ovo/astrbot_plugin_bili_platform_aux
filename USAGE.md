# 使用说明与功能清单

完整操作手册。权限规则先见 [权限边界](docs/PERMISSIONS.md)。插件的定位是**辅助**：所有账号、模板、图片、任务和日志都保存在
已有的 380nm 平台，AstrBot 只做入口和自动化，不维护独立任务队列，因此在 Web 后台
（`https://bilidyn.basmc.org/release`）和其他部署实例都能看到同样的任务。

- 平台根地址：`https://bilidyn.basmc.org`
- API 基址：`https://bilidyn.basmc.org/api`
- 机器人在群内/私聊的命令前缀：`/bd`
- 指令列表：`/bdhelp`

---

## 1. 安装与部署

1. 把插件目录放到 AstrBot 的插件目录下，目录名即模块名：

   ```text
   /root/astrbot/data/plugins/bili_platform_aux/
   ```

   目录内必须包含 `__init__.py`、`main.py`、`metadata.yaml`、`requirements.txt`。

2. AstrBot 加载插件时会自动安装 `requirements.txt`：

   ```text
   httpx>=0.27
   cryptography>=42
   Pillow>=10
   ```

   `cryptography` 缺失时插件会**拒绝启动**（不会退回明文存储）。生产环境必须安装。

3. 重启容器让插件生效：

   ```bash
   docker restart astrbot
   ```

4. 运行数据目录（默认 `data/bili_platform_aux`，即容器内
   `/AstrBot/data/bili_platform_aux`）保存：

   | 文件 | 内容 | 权限 |
   | --- | --- | --- |
   | `state.json` | 每个用户加密后的 `sid`、默认账号、草稿、预设、通知开关、通知会话 | `0600` |
   | `secret.key` | 本地加密密钥（未设置 `BILI_PLATFORM_AUX_SECRET_KEY` 时生成） | `0600` |

   可用 `BILI_PLATFORM_AUX_DATA_DIR` 改到别处（例如挂载出来的持久卷）。

---

## 2. 插件配置卡片（WebUI）

插件目录里的 `_conf_schema.json`会让 AstrBot WebUI 的插件详情页生成一张配置卡片，
保存后写入 AstrBot 自己管理的 `data/config/bili_platform_aux_config.json`。
**在 WebUI 里保存后 AstrBot 会自动热重载该插件**（提示“机器人正在热重载插件”），
不需要手动重启容器；正在等待确认的导入流程会被重载打断，改配置时请避开正在发布的时刻。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `platform_url` | string | `https://bilidyn.basmc.org` | 平台地址，插件自动拼接 `/api` |
| `allowed_hosts` | string | `bilidyn.basmc.org` | 主机白名单，逗号分隔，留空表示不限制 |
| `sid` | string | 空 | 平台会话 sid，等价于 `BILI_PLATFORM_SID`（明文输入框） |
| `shared_session_whitelist` | string | 空 | 共享账号完整会话标识白名单，逗号或换行分隔；空列表禁用共享账号 |
| `platform_username` | string | 空 | 仅用于展示和审计 |
| `account_id` | string | 空 | 默认（专用）B站发布账号 ID |
| `template_id` | string | 空 | 默认模板，留空使用「AstrBot 直发」 |
| `title` | string | 空 | 默认动态标题，平台限制 20 字以内 |
| `topic_id` / `topic_name` | string | 空 | 默认话题，两个都填才生效 |
| `task_type` | string | `原创` | 内容类型（原创/转载） |
| `variables_json` | text | 空 | 默认模板变量 JSON，例如 `{"extra":"x"}` |
| `slots_json` | text | 空 | 默认署名槽位 JSON |
| `max_upload_bytes` | int | 20971520 | 单张图片上限，只能调低，不会超过平台 20MB |
| `group_write_admin_only` | bool | 开 | 群聊写操作仅管理员可用 |
| `allow_password_login` | bool | 关 | 是否允许 `/bd login` 密码登录 |
| `notify_enabled` | bool | 开 | 发布结果通知总开关 |
| `notify_interval_seconds` | int | 20 | 通知轮询间隔，最小 5 秒 |
| `require_title` | bool | 关 | 标题必填：缺标题时不创建任务，先提示补齐 |
| `require_topic` | bool | 关 | 话题标签必填：同上 |
| `preview_card` | bool | 开 | 预览时发送渲染好的预览卡片图片 |
| `preview_footer` | string | 空 | 卡片底部文字，如 `IP属地：江苏` |
| `preview_avatar` | string | 空 | 左上角头像**兜底**：仅当待发布账号没有 B站头像时才用（URL 或本地路径） |

优先级：**插件配置卡片 > 环境变量 > 内置默认值**；再往上叠加用户发布预设和单次覆盖
（见「发布配置优先级」）。

注意：

- `sid` 只填 Cookie 里 `sid` 的**值**，不需要带 `sid=` 前缀。粘贴 `sid=xxx`、`"xxx"` 或整条
  Cookie（`foo=1; sid=xxx; bar=2`）也会被自动识别，配置卡片、`BILI_PLATFORM_SID` 环境变量和
  `admin_cli.py set-session --sid` 三个入口行为一致。
- `sid` 写在卡片里会明文保存在 AstrBot 的配置文件中。更在意安全就改用 `BILI_PLATFORM_SID`
  环境变量或 `admin_cli.py set-session`（插件自己的 `state.json` 是加密的）。卡片里的 `sid`
  只在该用户还没有会话时用于引导建立会话。
- 配置了 `account_id` 但该账号不在平台账号列表里时，发布会直接报错，**不会**悄悄换用
  其他账号。用 `/bd accounts` 核对 ID。
- `group_write_admin_only` 关掉后，群成员也能上传、导入、发布、编辑和操作任务。
- 配置卡片是插件级全局配置；用户的平台会话、草稿、预设按发送者 ID 保存，同一用户跨群和私聊共用；共享身份受会话白名单约束。

## 3. 登录 380nm 平台

插件不提供登录类 LLM 工具：**密码和 sid 不允许作为模型参数传递**。三种方式：

### 方式 A：环境变量（推荐给单账号部署）

```bash
BILI_PLATFORM_SID=<平台会话 sid>
BILI_PLATFORM_SHARED_SESSION_WHITELIST=<完整群聊或私聊会话标识>
BILI_PLATFORM_URL=https://bilidyn.basmc.org      # 可选
BILI_PLATFORM_USERNAME=<展示/审计用账号名>        # 可选
BILI_PLATFORM_ACCOUNT_ID=<专用 B站账号 ID>        # 可选
```

用户第一次在群里/私聊使用 `/bd` 时，插件会用这个 `sid` 调 `/auth/me` 校验并落盘加密保存，
之后按用户独立工作。专用账号直接来自环境变量，不经过聊天记录。

### 方式 B：服务器 CLI（推荐给多账号）

```bash
docker exec -it astrbot python /AstrBot/data/plugins/bili_platform_aux/admin_cli.py   set-session --owner <QQ号> --sid <sid>
# 省略 --sid 会走隐藏输入，不落 shell 历史
docker exec astrbot python /AstrBot/data/plugins/bili_platform_aux/admin_cli.py status
docker exec astrbot python /AstrBot/data/plugins/bili_platform_aux/admin_cli.py   clear-session --owner <QQ号>
```

`set-session` 会先请求平台校验 `sid`，校验通过才写入。

### 方式 C：密码登录（默认关闭，仅开发/兼容）

```bash
BILI_PLATFORM_ALLOW_PASSWORD_LOGIN=1
```

之后私聊执行 `/bd login <用户名> <密码>`，或 `/bd login <平台URL> <用户名> <密码>`。
群聊中始终拒绝该命令。密码只用于一次 `/api/auth/login`，不会被持久化。

### 查询/解绑

```text
/bd status      查看地址、用户、角色、默认账号、待发布图片数、当前预设、通知开关
/bd logout      退出并删除本地会话
```

`sid` 失效时（HTTP 401）插件会清除本地会话并提示重新登录；后台通知循环检测到 401 时也会
主动通知用户。

---

## 4. 命令总览

### 4.1 会话与配置

| 命令 | 说明 | 群聊限制 |
| --- | --- | --- |
| `/bdhelp` | 指令列表 | 无 |
| `/bd status` | 平台登录状态与默认值 | 无 |
| `/bd login <用户名> <密码>` | 密码登录（默认关闭） | 仅私聊 |
| `/bd logout` | 退出平台会话 | 无 |
| `/bd accounts` | 平台已绑定的 B站账号 | 无 |
| `/bd account use <账号ID>` | 设置默认发布账号 | 无 |
| `/bd templates` | 平台模板列表（含变量 key） | 无 |
| `/bd presets` / `/bd preset list` | 查看发布预设 | 无 |
| `/bd preset use <名称>` | 切换当前预设 | 无 |
| `/bd preset add <名称> <JSON>` | 新增/覆盖预设 | 无 |
| `/bd preset remove <名称>` | 删除预设 | 无 |
| `/bd notify on\|off` | 开关发布结果通知 | 无 |

### 4.2 素材

| 命令 | 说明 | 群聊限制 |
| --- | --- | --- |
| `/bd upload` | 把当前消息（或被引用消息）里的图片附件上传到平台图库，记为“待发布图片” | 仅管理员 |
| `/bd images` | 平台图库图片总数 | 无 |
| `/bd import <链接> [\|\| 正文]` | 调平台导入 Pixiv/X/Danbooru 链接图片 | 仅管理员 |
| `/bd library [关键词]` | 搜索平台图库（按文件名或 key），缓存最近 30 条 | 无 |
| `/bd image use <序号\|key>` | 把图库图片加入草稿 | 无 |
| `/bd image list` | 查看草稿图片顺序 | 无 |
| `/bd image order <key1,key2,...>` | 重排草稿图片（必须列全） | 无 |
| `/bd image remove <key>` | 从草稿移除一张 | 无 |
| `/bd image clear` | 清空草稿图片 | 无 |

### 4.3 内容与发布

| 命令 | 说明 | 群聊限制 |
| --- | --- | --- |
| `/bd preview <正文>` | 渲染预览（账号/模板/标题/话题/@/图片数/计划），**不写平台** | 无 |
| `/bd var <变量> <值>` | 设置模板变量 | 无 |
| `/bd title <标题>` | 设置草稿标题（`无` 表示不要标题） | 无 |
| `/bd type <原创\|转载>` | 设置草稿内容类型 | 无 |
| `/bd topic <关键词>` | 搜索话题（缓存最近 10 条） | 无 |
| `/bd topic use <序号>` | 绑定话题到草稿 | 无 |
| `/bd topic skip` | 本贴不绑定话题标签 | 无 |
| `/bd mention <关键词>` | 搜索可 @ 的用户（缓存最近 10 条） | 无 |
| `/bd mention add <序号>` | 添加 @用户到草稿 | 无 |
| `/bd draft` | 查看当前草稿 | 无 |
| `/bd draft cancel` | 取消当前草稿 | 无 |
| `/bd confirm` | 确认预览并创建平台任务 | 仅管理员 |
| `/bd post <正文>` | 直接创建任务（立即发布） | 仅管理员 |
| `/bd schedule <时间> \|\| <正文>` | 创建定时任务 | 仅管理员 |

`/bd post` 支持 `preset:<名称>` 前缀做单次预设覆盖，例如
`/bd post preset:daily 今天的更新`。

### 4.4 队列与任务

| 命令 | 说明 | 群聊限制 |
| --- | --- | --- |
| `/bd queue [状态]` | 队列概览 + 最多 30 条；状态可选 | 无 |
| `/bd job <任务ID>` | 任务详情（状态、计划、模板、账号、话题、@、图片数、尝试次数、错误、动态链接、正文） | 无 |
| `/bd edit <任务ID> <JSON>` | 编辑待发布任务并重新排队 | 仅管理员 |
| `/bd duplicate <任务ID>` | 复制任务为本地草稿（可再改再发） | 无 |
| `/bd cancel <任务ID>` | 取消任务 | 仅管理员 |
| `/bd now <任务ID>` | 立即发布 | 仅管理员 |
| `/bd retry <任务ID>` | 重新入队 | 仅管理员 |
| `/bd delete <任务ID>` | 删除任务 | 仅管理员 |
| `/bd logs [数量]` | 平台运行日志（默认 20 条） | 无 |

`/bd edit` 的 JSON 是平台 `PUT /api/jobs/:id` 的部分字段：`text`、`images`、`scheduledAt`、
`accountId`、`topic`、`title`。只允许编辑 `pending` 任务；`publishing`/`published` 会提示改用
`/bd duplicate`。`scheduledAt` 支持全部时间格式（见下）和 10 位秒 / 13 位毫秒时间戳。

```text
/bd edit job_xxx {"text":"修正后的正文","scheduledAt":"明天08:00"}
/bd edit job_xxx {"title":"新标题"}
```

### 4.5 时间格式

```text
+30m  +2h  +1d                       相对时间（数字）
三十分钟后  两小时后  3天后  1周后        相对时间（中文）
明天上午八点  明早8点  今晚8点            当天/近期 + 时段
今晚八点半  晚上七点一刻  9点30分         带分钟
明天08:00  后天09:30                 当天/近期 + 时刻
下周三晚上7点  下周一09:00  周三下午两点     指定星期
中午  晚上  早上                       只说时段（用默认钟点：中午12、晚上20、早上8）
2026-10-10 20:00                    绝对时间（也支持 ISO 字符串）
20:00                               纯时刻（已过则顺延到次日）
1700000000                          10 位以上 Unix 时间戳（秒）
```

规则与其它说明：

- 中文数字支持 `零一二三四五六七八九十两`，可解析到 59（`八`、`十二`、`二十`、`三十`、`两`）。
- 时段换算：`上午/早上/凌晨` 保持原钟点（`凌晨12点` = 00:00），`中午` 12 点起，
  `下午/傍晚/晚上/夜里` 小于 12 点时 +12（`晚上7点` = 19:00）。
- 没有写日期时按“今天”，**已过的时刻自动顺延到次日**（15:00 说「下午3点」= 明天 15:00）；
  `周三` 这种如果是本周已过，则顺延到下周同一时刻。
- 机器格式（`+30m`、`20:00`、ISO、时间戳）行为不变，优先于中文解析。

### 4.6 缺项反问与必填策略

预览和创建之前，插件会先算出"这次还缺什么"，再决定是提示还是拦住：

| 字段 | 默认 | 行为 |
| --- | --- | --- |
| 正文 | 必填 | 空正文直接拒绝 |
| 模板变量 | 必填 | 模板要求但没填的变量会列出并拦住 |
| 标题 | 可选（卡片 `require_title` 打开后必填） | 缺标题时列出并拦住 |
| 话题标签 | 可选（卡片 `require_topic` 打开后必填） | 同上 |
| 图片 / @提及 | 可选 | 只在预览里提示，不拦 |

被拦住时**不会创建任务**，草稿保留，返回的是"还差什么 + 怎么补"的清单，例如：

```text
任务未创建：还缺少必填信息。
请先向用户确认下面的信息，不要替用户编造，也不要在确认前重复提交：
- 标题（必填）：问用户标题写什么；用 /bd title <标题> 设置，用户明确不要标题时用 /bd title 无
- 话题标签（必填）：用 /bd topic <关键词> 搜索后 /bd topic use <序号>，不要话题时用 /bd topic skip
- 图片（可选）：把图片作为附件随消息发送，或 /bd import <链接>
补齐后可用 /bd confirm 创建，或 /bd draft cancel 取消。
```

**LLM 侧配合**：上面这段文字就是工具返回值，模型据此**反问用户**而不是自己编标题。模型也可以先调用
`bili_platform_publish_options` 拿到"可选模板 / 可用发布预设 / 当前默认值 / 必填策略"，然后一次问清
「用哪个模板或预设？标题和话题标签写什么？」；用户回答后用 `bili_platform_set_title`、
`bili_platform_topic_search` + `bili_platform_topic_use` 记录，再调 `bili_platform_post` 创建。

用户明确表示不要时：`/bd title 无`、`/bd topic skip` 会把"已决定"记进草稿，必填策略不再拦，
创建出来的动态就是空标题 / 不带话题。

### 4.7 预览卡片（渲染图）

`/bd preview`（以及 LLM 的 `bili_platform_preview`）除了文字预览，还会用 PIL 渲染一张卡片发出来，
布局与微博/B站动态预览类似：

```text
┌──────────────────────────────────────┐
│ 「标题」                               │
│ (头像) 账号名                  [001524] (组徽标) │
│        2026年10月7日 19:00            │
│ [#] 话题标签                          │
│ 正文（含 作者/X/授权/翻/嵌 等署名行）    │
│ ┌──────────────────────────────────┐ │
│ │            作品图片 1~9 张          │ │
│ └──────────────────────────────────┘ │
│ IP属地：江苏                           │
└──────────────────────────────────────┘
```

公开仓库不分发包含真实账号或第三方作品的本地预览样张。

字段来源：

| 卡片元素 | 来源 |
| --- | --- |
| 标题 | 草稿/卡片/预设的 `title` |
| 头像 + 账号名 | **待发布账号**的 B站头像与名称（`/api/accounts` 的 `avatar` / `name`/`uname`，按账号缓存）；账号没有头像时才用 `preview_avatar` / `resources/avatar.png` 兜底 |
| 时间 | 计划时间（`明天上午八点` → `2026年10月11日 08:00`）；立即发布显示「立即发布」 |
| 话题 | 草稿绑定的话题标签 |
| 正文 | 模板变量渲染后的内容 |
| 图片 | 同一条消息里的图片附件 + 待发布/草稿图片（按顺序，最多 9 张） |
| 底部文字 | 卡片 `preview_footer` |

行为与限制：

- 图片取平台 `/uploads/...`（公开可读）或图片附件本地文件；单张最大 12MB，取不到就跳过。
- 单张图按内容宽度等比缩放（超高时最高 1500px）；多张图两列排布，每张最高 720px。
- 有必填缺项时**不渲染**卡片，只给缺项清单，避免拿半成品误导。
- 渲染或发送失败不会影响文字预览，会附一句「预览图渲染失败/发送失败，以上方文字为准」。
- 临时图片放在 `data/bili_platform_aux/temp/`，30 分钟自动清理。
- 彩色 emoji：找到 emoji 字体时会彩色渲染（`嵌：🐷 & 明哲` 正常显示）；找不到就自动去掉 emoji，
  不会画成豆腐块。字体放在 `data/bili_platform_aux/resources/NotoColorEmoji.ttf`，
  用 `python scripts/fetch_assets.py` 一键获取（优先 apt，失败回退 HTTP 镜像）。
  注意放在插件目录里的字体在下次部署时会被覆盖，请放数据目录。
- 头像：左上角固定使用**待发布账号的 B站头像**，取值顺序为
  1) 平台账号的 `avatar` 字段（`/api/accounts` 返回的是 B站 face，按账号缓存）；
  2) 平台没存头像时，按账号 `uid` 向 B站 查一次 face（带浏览器 UA，失败即跳过）；
  3) `data/bili_platform_aux/resources/avatar.png` 或卡片 `preview_avatar` 指定的图片；
  4) 都没有就画首字圆形占位。账号由卡片 `account_id`、`/bd account use` 或平台第一个账号决定。
  右上角不再显示任何徽标。
- 关掉卡片：配置卡片里 `preview_card` 设为关闭，或单次用 `/bd preview` 之外的文字路径。

---

## 5. 典型工作流

### 5.1 有图有文的日常搬运

```text
1. 在群里发图 + 执行        /bd upload
2. 预览                     /bd preview preset:daily 今天的更新 #1
3. 需要时补变量             /bd var extra 来源已授权
4. 需要时加话题/@           /bd topic 原创插画  → /bd topic use 2
                            /bd mention 某UP主   → /bd mention add 1
5. 确认创建                 /bd confirm
6. 核对                     /bd job <返回的任务ID>
```

### 5.2 定时发布

```text
/bd schedule 明天08:00 || 明天早上的更新
/bd queue pending
```

### 5.3 链接导入

```text
/bd import https://www.pixiv.net/artworks/12345678 || 授权转载
```

导入的图片会作为“待发布图片”带入下一次预览/发布；也可以先 `/bd import` 再
`/bd preview <正文>` 分两步走。

### 5.4 改任务/重发

```text
/bd edit <任务ID> {"scheduledAt":"+2h"}
/bd duplicate <任务ID>     → 改文案后 /bd confirm 再发一条
```

---

## 6. 发布配置优先级

由低到高：

1. 环境变量默认值（`BILI_PLATFORM_ACCOUNT_ID`、`BILI_PLATFORM_TEMPLATE_ID`、
   `BILI_PLATFORM_TITLE`、`BILI_PLATFORM_TOPIC_ID`/`BILI_PLATFORM_TOPIC_NAME`、
   `BILI_PLATFORM_TASK_TYPE`、`BILI_PLATFORM_VARIABLES_JSON`、`BILI_PLATFORM_SLOTS_JSON`）
2. 插件配置卡片（WebUI）里的同名配置项，非空时覆盖环境变量
3. 当前用户激活的发布预设
4. 单次调用 `preset:<名称>`（命令）或 `preset` 参数（LLM 工具）
5. 命令正文覆盖模板的 `text` 变量

预设 JSON 只接受这些字段：`account_id`、`template_id`、`title`、`topic_id`、`topic_name`、
`task_type`、`variables`、`slots`。其他字段会被丢弃。

```text
/bd preset add daily {"account_id":"acc1","template_id":"tpl1","task_type":"转载"}
/bd preset use daily
```

没有配置模板时，插件会确保平台存在名为 `AstrBot 直发` 的模板（`{{text}}`，最多 9 图），
没有配置账号时使用平台的第一个账号——建议用 `/bd account use` 或 `BILI_PLATFORM_ACCOUNT_ID`
固定成专用账号。

若平台已存在相同正文的 `pending`/`publishing`/`published` 任务，预览会显示“重复提醒”，
避免重复搬运。

---

## 7. 群聊权限

| 能力 | 群成员 | 群管理员 | 私聊 |
| --- | --- | --- | --- |
| `/bdhelp`、`status`、`accounts`、`templates`、`presets` | 允许 | 允许 | 允许 |
| `queue`、`job`、`logs`、`library`、`images` | 允许 | 允许 | 允许 |
| `topic`、`mention`、`var`、`draft`、`preview`、`image`、`duplicate` | 允许 | 允许 | 允许 |
| `upload`、`import`、`confirm`、`post`、`schedule`、`edit` | 拒绝 | 允许 | 允许 |
| `cancel`、`now`、`retry`、`delete` | 拒绝 | 允许 | 允许 |
| `login`（密码登录） | 拒绝 | 拒绝 | 允许 |

管理员判定顺序：AstrBot `event.is_admin()` → `raw_message.sender.role` 为 `owner`/`admin`
（兼容 QQ 群主与群管理员）。被拒绝时只提示改用私聊，不会发出任何平台写请求。

此外所有写操作还受频率限制：创建 2 秒、上传 2 秒、导入 3 秒、任务操作 1 秒。

---

## 8. 发布结果通知

插件启动后运行一个后台循环（启动延迟 5 秒，之后每 20 秒一次），用已保存的 `sid` 拉取任务列表：

- 任务状态变为 `published`：推送“B站动态已发布 + 动态链接”。
- 任务状态变为 `failed`：推送“B站动态发布失败 + 失败原因”。
- 平台返回 HTTP 401：清除该用户本地会话并提示重新登录。
- 首次轮询只建立基线，不会补推历史任务；状态未变化不重复推送。
- 任务在 Web 后台或别的实例里被改动，也会被这个循环发现并通知。

通知发送到该用户**最近一次使用 `/bd` 的会话**（`unified_msg_origin`），所以私聊登录过就在
私聊通知、在群里用过就在群里通知。`/bd notify off` 关闭，`/bd notify` 查看当前状态和
通知会话。

---

## 9. 完整功能清单

### 9.1 已实现

会话与账号

- 插件配置卡片（WebUI）提供 22 项全局配置；配置优先级：卡片 → 环境变量 → 内置默认值。
- 三级配置：环境变量默认值 → 用户预设 → 单次覆盖。
- `sid` 使用 Fernet 加密落盘；支持外部密钥 `BILI_PLATFORM_AUX_SECRET_KEY`。
- 环境变量会话引导（`BILI_PLATFORM_SID`）、服务器 CLI（`set-session`/`clear-session`/`status`）、
  可选密码登录。
- 平台 URL 白名单（默认只允许 `bilidyn.basmc.org`）+ 强制 HTTPS。
- 401 自动清会话；账号、模板、预设统一管理。

素材

- 消息附件上传（单张 ≤20MB、最多 9 张，可调低）；**被引用的消息**里的图片也会一起取用。
- 平台图库搜索、图库图片加入草稿、草稿排序/移除/清空。
- 平台 `library/import` 导入 Pixiv/X/Danbooru 链接（含 `folderId` 预留参数）。

内容

- 模板变量、标题、话题（搜索 + 绑定）、@提及（搜索 + 添加，自动按 uid 去重）。
- 草稿预览（渲染后正文 + 账号/模板/标题/话题/@/图片/计划），缺变量时给出补齐提示。
- 重复正文检测提醒。
- 任务类型（原创/转载等）与署名槽位插槽。

发布

- 立即发布（`/bd post`）、定时发布（`/bd schedule`）、预览确认（`preview` + `confirm`）。
- 时间支持机器格式与中文自然语言（`明天上午八点`、`今晚8点`、`下周三晚上7点`、`3天后` 等）。
- 缺项反问：标题/正文/话题/图片为空时给出结构化清单，LLM 会先问用户；卡片可把标题/话题设为必填。
- 预览卡片：`/bd preview` 渲染一张图（标题/账号头像/计划时间/编号/话题/正文/图片/底部文字）。
- 草稿可编辑：`/bd title`、`/bd type`、`/bd var`、`/bd topic`（含 `skip`）、`/bd mention`、`/bd image`。
- 任务队列概览与状态过滤、任务详情、任务编辑并重新排队、复制任务为草稿。
- 取消、立即发布、重试、删除；操作前校验任务属于当前平台用户。

查询与通知

- 平台运行日志查询。
- 后台发布结果通知（published/failed）与会话过期通知。
- `/bd notify on|off` 通知开关与通知会话展示。

交互与权限

- `/bdhelp` 指令列表；完整命令路由与统一错误提示。
- 群聊写操作默认仅管理员；私聊仍须拥有个人会话或命中共享会话白名单。
- 写操作频率限制；密码/sid 不出现在日志、回复和 LLM 工具参数中。

LLM 工具（共 26 个）

`bili_platform_account_use`、`bili_platform_accounts`、`bili_platform_confirm`、
`bili_platform_duplicate`、`bili_platform_image_action`、`bili_platform_images`、
`bili_platform_import`、`bili_platform_job_action`、`bili_platform_job_detail`、
`bili_platform_job_edit`、`bili_platform_library`、`bili_platform_logs`、
`bili_platform_mention_add`、`bili_platform_mention_search`、`bili_platform_post`、
`bili_platform_preview`、`bili_platform_publish_options`、`bili_platform_queue`、
`bili_platform_set_title`、`bili_platform_set_type`、`bili_platform_set_var`、
`bili_platform_status`、`bili_platform_templates`、`bili_platform_topic_search`、
`bili_platform_topic_use`、`bili_platform_upload`

### 9.2 已知限制

- 平台硬限制：单张图片 20MB、单任务最多 9 张；插件不会突破，只能用
  `BILI_PLATFORM_MAX_UPLOAD_BYTES` 调低。
- 动态标题最多 20 字（平台限制）。
- `publishing`/`published` 的任务不能编辑，只能复制成新草稿。
- 图片只有文件名和 key，没有本地索引：找图依赖 `/bd library` 关键词或任务详情里的图片数量。
- 引用消息取图依赖平台的 OneBot `get_msg`（NapCat ✅）；其它平台可能读不到，此时会提示
  “当前平台无法读取引用消息里的图片”，把图直接发一次即可。
- 平台接口偶发抖动：插件会把连接超时压到 8 秒、总超时 30 秒，并对 **GET** 自动重试 3 次
  （POST/PUT/DELETE 不重试，避免重复建任务）；失败会返回可读提示而不是卡住。
- 查询有短缓存：账号/模板 60 秒、任务列表 15 秒。刚在网页端改完账号或模板，可能需要等一分钟
  才在插件里生效；重复预览不会再重复请求平台。
- 通知间隔为 20 秒，不是实时推送；只推送状态变化，不推送新建任务。
- 通知依赖 AstrBot 会话可用：如果机器人不在那个会话里，发送会失败并只记录 warning。
- 平台图库搜索是“拉全量后本地过滤”，图片很多时响应会变慢。
- 撤销 `sid` 只能通过 `/bd logout`、`clear-session` 或在平台侧改密码。

---

## 10. 安全说明

- 平台密码只用于一次登录请求，不落盘；持久化的只有加密后的 `sid`。
- 密码登录命令仅私聊可用，但 QQ 消息本身可能被平台消息日志记录——建议用专用的普通用户
  账号，不要用管理员账号。
- 默认只允许登录 `bilidyn.basmc.org`；换平台要通过 `BILI_PLATFORM_ALLOWED_HOSTS` 显式加入，
  且必须是 HTTPS。
- `state.json` / `secret.key` 权限 `0600`，数据目录 `0700`。
- 删除类操作、上传、导入、发布、编辑在群聊中只允许管理员。
- 任务操作先校验归属，再执行；越权访问返回“任务不存在或不属于当前平台用户”。
- 不在日志、回复、LLM 工具参数中出现密码、`sid` 或 Cookie。

---

## 11. 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示“尚未登录 380nm 平台” | 用环境变量 / `admin_cli.py set-session` / 私聊 `/bd login` 建立会话 |
| 提示“平台会话已过期” | 重新获取 `sid`（平台重新登录后取 Cookie），再 set-session |
| 提示“群聊中只有管理员可以…” | 改用私聊，或让群管理员操作 |
| 群聊里 `/bd notify` 显示“通知会话未记录” | 先在该会话执行一次 `/bd` 命令，插件就会记住 |
| 上传提示没有检测到图片 | 图片要和 `/bd upload` 或 `/bd post` 在同一条消息里发送 |
| 平台报“模板不存在”“请选择要发布的B站账号” | `/bd templates`、`/bd accounts` 核对，必要时 `/bd account use` |
| 平台报“图片数量超出限制” | 检查模板的 `maxImages`，或减少草稿图片 |
| 平台报“任务正在发布，无法编辑” | 等状态变成 `published`/`failed`，或 `/bd duplicate` |
| 插件加载失败 | 确认容器内有 `cryptography`；查看 `docker logs astrbot` |

---

## 12. 升级部署流程

仓库自带可复现的打包与部署脚本，避免手工 scp 出错：

```bash
# 1. 本地打包（文件名带 git short hash，产物在 dist 目录）
python scripts/package.py --out dist

# 2. 上传到服务器（首次使用还需单独上传 scripts/deploy_remote.sh）
scp dist/bili_platform_aux-<sha>.tar.gz root@<host>:/root/astrbot/plugin-backups/

# 3. 在服务器上执行（自动备份、解包、修权限、容器内预检、重启）
bash /root/astrbot/plugin-backups/deploy_remote.sh <sha>
```

`deploy_remote.sh` 的关键点：

1. 先把现有插件目录整体移到 `plugin-backups/<name>.backup-<时间戳>`，不做覆盖删除。
2. 解包后删除 `__pycache__` 并 `chmod -R a+rX`。
3. 重启前在容器内 `import data.plugins.<name>.main`，用真实的 AstrBot 装饰器跑一遍——
   AstrBot 对 LLM 工具的参数类型校验发生在导入期，这一步能在真正重启前暴露加载错误。
4. 最后 `docker restart astrbot`，再确认 `docker logs` 里出现
   `Plugin <name> (<version>) by ...` 且没有 `导入失败`。

回滚：把 `plugin-backups/<name>.backup-<时间戳>` 移回插件目录并重启容器。

## 13. 测试

```bash
python -m unittest discover -s tests -t .
```

测试使用最小 AstrBot stub，不启动 AstrBot；HTTP 走 `httpx.MockTransport` 或假客户端，
不访问网络。当前 53 个用例覆盖配置加解密、会话、预设、草稿、时间解析、平台客户端、
命令路由、群聊权限、任务编辑、通知循环，以及 LLM 工具 docstring 的参数类型校验。


## 共享账号会话白名单（2026-10-14）

配置卡片 `shared_session_whitelist`（或环境变量 `BILI_PLATFORM_SHARED_SESSION_WHITELIST`）接受逗号或换行分隔的完整 AstrBot `unified_msg_origin`，精确匹配，默认空列表禁止共享账号。请从 AstrBot 会话信息取得目标群聊或私聊的完整标识。授权群聊不会授权成员私聊，管理员也不能绕过白名单；群内写操作仍受管理员限制。

白名单外需绑定个人平台账号，否则不能访问平台。已有自动保存的共享会话同样受限，移除授权后缓存和结果通知不能绕过限制。旧会话若 sid 等于当前共享 sid 按共享处理；无法识别的历史会话请管理员核查后清理。若个人会话使用相同共享 sid，也按共享处理。个人账号可通过服务器 admin_cli.py set-session 绑定，密码登录默认关闭。

