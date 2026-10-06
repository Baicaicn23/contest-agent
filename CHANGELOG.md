# 更新日志

本项目的全部重要变更都记录在此文件中。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] — M11 前端迁移 Next.js + TS + Tailwind（TeachX 形态）

### 变更

- **前端整体重写**：Vite + React 18 + JS + 手写 CSS → **Next.js 15 App Router +
  TypeScript + Tailwind + lucide-react**（用户指定完全迁移，参照 TeachX 项目形态）；
  `output: "export"` 静态导出到 out/，FastAPI 单端口托管不变（server 兼容 out/ 与旧 dist/）
- **形态复刻**：serif 时段问候（Good morning/afternoon/evening + Lora/宋体）+ 居中大
  圆角输入卡（内嵌工具行）+ 窄侧栏（导航/会话列表/底部用户盒）+ 顶部细条 + 建议行；
  shadcn 风格语义令牌（snow 纯白蓝单主题，变量结构可扩展）
- **多标签模型改为侧栏会话列表切换**（TeachX 形态；运行中转圈/任务徽章/相对时间/
  未归类组/按项目分组前置全保留）；会话路由用 ?session=N 查询参数（静态导出无动态段）
- **状态架构对齐 TeachX**：AppStateProvider 集中 config/sessions/聊天运行时——
  工作台发送 → 路由切 /chat，SSE 流跨页面不断线；15s sessions 轮询 + 60s 截止提醒挂 Provider
- 修复 M4 用量测试日期写死跨月失效（本周断言改相对构造）

### 测试

- 离线 178 项 + live 4 项全绿；`next build` 静态导出 6 页全部可达（/chat 307→/chat/）
- 端到端：工作台发消息 → 流式 → 自动路由 → 表格渲染 → 侧栏高亮 + 上下文 %

## [Unreleased] — M10 用户视角三连

### 新增

- **消息 Markdown 渲染**：手写块级解析器（表格/代码块/标题/引用/水平线 + 行内粗体
  行内码 + bullet/ordered），不引库、不走 innerHTML；fenced 未闭合流式容错；
  表格横滚 + 表头底色 + 斑马纹；agent 返回的表格终于"长成表格"
- **agent 读附件（read_attachment 第七件聊天工具）**：接通 M9 上传的断头路——
  纯文本直读、PDF 走 pypdf（限 40 页、8000 字截断）、Office 诚实告知不支持并给出路；
  防路径穿越（只取文件名）；找不到附件时列出现有文件；系统提示词同步工具引导
- **桌面截止提醒**：通知弹层开关（借用户手势申请浏览器 Notification 权限）+
  App 60 秒轮询 urgent_deadlines，只弹增量（首次开启标记存量防轰炸）；
  纯前端零后端，守望能力的最后一公里

### 变更

- 新依赖 pypdf（PDF 文本提取）；聊天系统提示词加入附件工具引导

### 测试

- 离线 178 项（新增 2：附件文本/穿越守卫、Office 边界 + pypdf 写读链路验证）
  + live 4 项全绿
- browser-use 三连验收：markdown 表格渲染实拍 / 附件问答端到端（agent 自主调
  read_attachment 逐条复述并结合真实截止日期）/ 通知开关与权限链路

## [Unreleased] — M9 首页精简与 Composer 集成

### 新增

- **Composer 工具行集成**（图四形态）：＋上传（POST /api/upload 落盘 output/uploads/，
  文件名清洗/重名时间戳/20MB 上限，附件 chip 可移除，发送并入消息文本）、
  **三档权限选择**（只读/变更前确认/完全访问，真实写 config permission_mode）、
  **上下文 %**（当前会话最后轮输入 token ÷ 模型窗口 1M；sessions 接口新增 prompt_tokens
  聚合，取 MAX 不取 SUM——每轮 prompt 含完整历史）、**模型切换下拉**（全部档案+缺密钥提示）
- **三档权限模式**（config permissions.permission_mode，单一真相）：
  只读=写类工具（扫官网/识别/存材料，WRITE_TOOL_NAMES）全局拒绝；
  变更前确认=终端交互走名单确认、**网页聊天拦下并说明原因**（block_unattended_writes
  仅聊天装配传 True，cron/watch 保持 M3 名单语义）；完全访问=全放行（同步旧 access_full）
- **会话号回写 tab**：首页开的会话在侧栏高亮、上下文 % 生效；回写不触发历史重载

### 变更

- 首页精简：移除截止临近/给你几个点子/chips 行/under-chips/底部状态条，只留
  云图标 + 大问题（居中）+ 底部输入卡；设置页权限卡从两个 Toggle 改三档 seg（同一真相）
- **修复聊天工具箱未挂权限门**（build_chat_tools 装配缺 gate 参数）——三档之前
  对聊天 agent 无效；修复 App 的 TDZ 白屏（contextPercent IIFE 引用未声明的 showChat）

### 测试

- 离线 176 项（新增 M9 五项：三档门语义含 cron 不受影响、行级写入回读、
  permission-mode 端点往返、上传清洗与自清理）+ live 4 项全绿
- 端到端三档实测：只读拒扫描给替代方案 → confirm 拦截说明"网页聊天无法弹确认" →
  full 真扫官网返回 8 条真实通知；上下文 %/模型切换/emoji 零命中

## [Unreleased] — M8 侧栏完全复刻（图标化 / 项目树 / 运行中转圈）

### 新增

- **SVG 线性图标系统**（手写 Icon.jsx，24 viewBox / currentColor / 细线风）：
  全站文字图标升级为图形图标，文件夹带开合两态
- **项目树完全复刻**：视图行（「📁 项目」胶囊 + 筛选/垃圾桶）+「项目 ⌄」标题行
  （整列折叠收纳 + 行内新建）；项目行折叠/展开、整列折叠、侧栏整体折叠
  （左上浮钮恢复）——三层折叠状态全部 localStorage 记忆
- **运行中任务转圈**：发消息即转圈（本地标记）+ 后端 status 对齐（15 秒轮询兜底 +
  done 帧即解除），完成转"任务徽章 + 相对时间"；未归属会话进"未归类"折叠组
- **删除项目**：垃圾桶进删除模式，仅手动项目可删（比赛卡派生项目后端 422 拒绝），
  红色确认态防误删；`DELETE /api/projects/{key}` 解绑会话不删会话
- **筛选**：漏斗滑出过滤框，按项目名/会话名实时过滤
- **用户盒**：头像圆 + 名字 + "本地"徽章 + 齿轮直达设置

### 变更

- **聊天会话状态机修复**：此前 chat 会话永远停在 running（僵尸状态）——现在
  一轮对话开始置回 running、完成置 completed、出错置 failed（set_status）；
  存量僵尸就地修复。"运行中"从此表示"正在生成回复"
- **修复切视图重发消息**：rail 切走再切回会重挂载 ChatView 并把首条消息重发一遍
  （M4 起的老 bug）——首条发送后立即清空 tab 的 initialUser
- 新增仓储方法 set_status / unbind_project / delete(project)；PUT 语义见 CHANGELOG 上文

### 测试

- 离线 171 项（新增：删除项目两态、聊天状态机生命周期）+ live 4 项全绿
- browser-use 交互闭环走查：删除确认/筛选/三层折叠/转圈完整生命周期
  （发送即转 → 完成即解除）/未归类组/emoji 零命中

## [Unreleased] — M7 工作台图二化与右侧工具坞

### 新增

- **侧栏图二化**（对照竞品截图）：顶部四操作入口（新建任务 ⌘N / 搜索 ⌘K /
  自动化 / 插件市场）+ 项目树两级（项目 → 归属会话子行，任务徽章 + 相对时间，
  grid 轨道展开过渡）+ 最近（未归属会话）；"自动化"弹层显示真实盯梢状态、
  立即扫描（不花 LLM，POST /scan）与 cron 接入命令
- **右侧工具坞 RightDock**（可开合悬浮面板，替代旧 ToolPanel）：
  文件树 tab（GET /api/tree 递归树，目录折叠，点文件预览）+
  终端 tab（POST /api/terminal 在项目根执行命令；30 秒超时、输出截断 10KB、
  结构化返回 exit 码与耗时；前端一次性会话历史，运行占位原位替换）
- **全局快捷键**：⌘K/Ctrl+K 搜索、⌘N/Ctrl+N 新建任务；三处"新聊天"收敛为 newChat()

### 变更

- /api/files/content 修复：允许相对子路径（notifications/xx.md 此前预览必失败），
  resolve 后必须落在 output/ 内（防穿越）；该端点改用装配注入的 output_dir
- WorkspaceService 新增 command_runner 注入点（终端执行回调，沿用
  "application 层不碰 subprocess"惯例）；旧 ToolPanel.jsx 删除

### 测试

- 离线 166 项（新增 M7 六项：树形/排序/隐藏文件/空目录/终端委托与守卫/HTTP+穿越防护）
  + live 4 项全绿
- browser-use 实测：左栏四入口/两级树/自动化真扫描（10 条新增）/文件树展开/
  子目录预览/终端真跑 sai cost（136 次调用 ¥0.9469 真台账）/⌘K/暗色三面板

## [Unreleased] — M6 界面美化与交互升级

### 新增

- **悬浮侧栏**：图标栏与侧栏脱离贴边（12px 留白 + 18px 圆角 + 常驻面板阴影），
  主区 margin 补偿、去掉边框分隔；应用启动时两面板错峰滑入（40ms stagger）
- **动效系统**：tokens 新增动效令牌（micro/std/exit 三档时长 + out/inout 两条曲线 +
  面板阴影），全站过渡只取令牌；`prefers-reduced-motion` 下全部动画直达终态
- **衔接动画**：视图切换淡入、弹层（搜索/通知/命令面板）遮罩淡入 + 面板浮出、
  消息上浮入场（流式增量不动画）、工具面板右滑入、toggle 旋钮过冲弹性
- **四态补齐**：全站可交互元素（侧栏项/标签页/chips/发送钮/插件按钮等 20 类）
  统一 hover 过渡 + 按压缩陷（scale 0.97，主行动钮更弹）+ 全局键盘焦点环（focus-visible）

### 变更

- **关闭钮统一左上**（设置全页/Customize/搜索/通知/工具面板五面），Esc 全覆盖
  （挂 document，焦点 anywhere 均可关）；toggle 旋钮从动画 `left` 改为 `transform`
- 修复三个 M5 遗留：侧栏"通知"按钮误开搜索（NotificationsPop 从未被渲染，
  且开启点击被根节点冒泡立即关闭）；关闭 Customize 后主区空白（rail 停留 'none'）；
  历史会话回放点不开（回放标签 key 不满足主区显示条件）
- 界面去 emoji 扫尾（本地 chip、工具调用折叠块标题）

### 测试

- 离线 160 项 + live 4 项全绿（纯前端改动，后端零改动）
- browser-use 亮暗双主题实拍验收：悬浮侧栏留白/阴影、五面关闭钮左上、
  hover/焦点环实拍、通知/搜索/工具面板开合、回放消息流、emoji 源码清零

## [Unreleased] — M5 Codex 化界面

### 新增

- **Codex 式布局**：图标栏（工作台/统计/截止日程）+ 侧栏重构
  （Contest Agent 头部 / 通知铃 / 全局搜索 / 项目树 / skills配置 / 最近）
  + 聊天标签页（多标签并行）+ 右侧工具分屏（output 真实文件列表与预览）
- **项目体系**：比赛卡自动派生项目（不落库现算）+ 手动新建（projects 表）+
  会话归属（sessions 幂等加 project_key）；composer 项目 chip 弹面板
  （搜索/新建/绑定），发首条消息自动归属
- **插件市场**：7 个能力插件（截止守望/评测/盯梢/PPT导出 + 三种推送通道），
  安装/卸载真实写 config 的 features 段（行级读写保注释）；
  未安装能力对应接口降级 503；Skills 页列真实技能清单
- **完全访问总闸**：config `access_full` + 权限门两层模型
  （总闸开=全放行，名单无损保留）；composer"⚠ 完全访问"开关真实写配置
- **后端端点**：/api/projects(+/bind) /api/search /api/notifications
  /api/skills /api/files(+/content) /api/git/branch /api/plugins(+/toggle)
  /api/config/access

### 变更

- settings.set_feature / set_access_full（按行替换保注释）；
  PermissionGate 支持 full_access 总闸；sessions 表幂等小迁移

### 测试

- 离线 160 项（新增 12）+ live 4 项全绿
- 浏览器对照五张 Codex 原图验收：项目树/chips popover/设置权限卡/插件墙；
  功能真实性：切项目绑定落库、总闸写 yaml、插件 toggle 后接口降级、
  搜索命中、git 分支真实读取

## [Unreleased] — M4 收尾批

### 新增

- **聊天区升级为真 agent（聊天即行动）**：/api/chat 背后从纯 LLM 文本调用
  改为 AgentScope 工具循环——挂聊天工具箱六件（查卡片/读通知原文/联网搜索/
  查截止/扫官网/识别最新通知），用户在前台说"准备一下最新的比赛"，
  agent 自己扫官网→识别→读原文→给出备赛简报；reply_stream 事件流
  翻译成 SSE 帧（逐字流式保得住），工具调用实时渲染折叠块并存档可回放；
  计价器/预算熔断/6 轮上下文全继承。移除旧纯流式路径
  （OpenAiStreamChat/ChatStreamPort）
- **截止日期守望（Deadline Sentinel）**：卡片 deadline 字段的四档倒计时警报
  （T-7/3/1/0 天；记忆去重同档不重吵；窗口内晚添加立即补发；过期自动停报；
  推送全挂不记账、下轮重试）；`sai watch` 一轮同时推新比赛与截止警报；
  `sai deadlines` 只读列表 + `GET /api/deadlines` + 情报站首页截止临近卡
- **生成材料导出真 .pptx**：`sai generate --skill ppt-outline`（及前端 /生成、
  POST /generate）在大纲落盘后自动经"LLM 结构化整理 → python-pptx 渲染"
  产出 16:9 幻灯片文件；铁律只排版不改写（标题要点全来自大纲原文）；
  导出失败降级不毁任务（大纲 .md 照常在手）。新依赖 `python-pptx==1.0.2`

## [0.2.0] - 2026-10-01

v2 四个里程碑合并发版：成本台账与上下文管理、记忆与会话存档与评测、推送与子代理与权限门、Web 界面。

### 新增

- **一键启动脚本 `start.sh`**：首次运行自动安装前端依赖并构建，之后直接起
  FastAPI 单端口服务（界面 + API）；`--build` 强制重建，其余参数透传 sai serve
- **Web 界面**（frontend/，React 18 + Vite + 手写 CSS 设计令牌，中文本地化）：
  - **工作台**：问候语 + Overview 卡（会话/消息/总 token/活跃天数/高峰时段/
    常用模型六统计 + 18 周热力图 + 模型用量表 + 周对比趣味文案）——
    全部来自新接口 `GET /api/usage/summary` 的真实台账聚合
  - **情报站**：serif 大字问候 + 居中输入卡 + 点子列表（识别/生成/备考/账单一键执行）
  - **会话视图**：自由对话（SSE 逐字流式）+ 历史任务轨迹回放
    （M2 存档事件 → 右气泡/助手正文/工具折叠块；chat 会话可续聊）
  - **Settings**：亮暗主题与字号真切换（CSS 变量 + localStorage）；
    切模型档案、改预算上限（按行替换写回 config.yaml）；路由/权限/推送只读；
    其余分区视觉占位
  - **/ 命令面板**：/识别 /扫描 /生成 /备考 /账单 /报告
- **后端**：`GET /api/usage/summary`（UsageReport 聚合用例）、
  `POST /api/chat`（SSE 逐 token，人设注入实时数据 + 最近 6 轮上下文，
  花费照常入台账）、`GET /api/config`（脱敏）、`POST /api/config/model|budget`、
  `POST /identify`（P6 缺项补全）、FastAPI 托管 frontend/dist（sai serve 单端口）
- **新端口**：ChatStreamPort（能力十：流式自由对话）

### 变更

- settings.set_budget：预算按行替换写回 config.yaml（保注释），env 覆盖依旧优先
- 内存库 StaticPool 关闭跨线程检查（SSE 流式响应的工作线程需要）

### 测试

- 离线 133 项（M4 新增 16）+ live 4 项全绿
- 浏览器真实验收（对照五张 Claude Desktop 原图）：三视图、Settings 弹窗、
  用户菜单、暗色主题切换、Overview 真实数据、会话轨迹回放、
  chat 逐字流式（人设注入的实时卡片数正确）、/账单命令执行

**—— v2/M3 定时推送 + 研究分身 + 权限门 ——**

### 新增

- **定时推送**：`sai watch` 盯一次官网（识别与 `sai identify` 完全同款，
  幂等+记忆让反复跑几乎零成本），发现新比赛推送到所有已启用通道；
  三通道实现 PushPort——webhook（POST JSON，钉钉/企微/Server酱通用）、
  邮件（SMTP，密码走 `SMTP_PASSWORD`）、本地文件（Markdown 落盘，默认开启）；
  定时交给 cron/launchd（README 附 crontab 一行），`--loop` 可临时值守；
  单通道故障不拖累其他通道
- **研究分身（子代理）**：study-path 新增 `research_digest` 工具——分身内部
  搜索前 3 条、精读前 2 页、一次结构化调用压缩成"概述/要点/有用网址"摘要，
  主循环只收千字摘要；网址铁律照抄材料（P5 引用校验同源）；分身与主循环
  共用同一个计价器和会话记录（花费合并算账、轨迹同份存档）
- **权限门**：config.yaml `permissions` 两个名单——`confirm_tools`
  （交互模式执行前 y/N 确认）、`unattended_deny_tools`（无人值守一律拒绝，
  理由回给模型）；拒绝理由进会话轨迹；对照 pi"沙箱学派"的取舍已记录
  （工具自有且有界，权限门够用；引入 shell 类工具时再评估沙箱）

### 变更

- 识别用例补 `new_cards` 清单（推送只推本次新入库的卡片）
- 工具注册链扩为"截断 → 权限门 → 会话记录"，权限门的拒绝也留档可回放
- config.yaml 新增 `push` / `permissions` 配置段（默认零行为变化）

### 测试

- 离线 117 项（M3 新增 18）+ live 4 项全绿
- 真实验收：本地 HTTP 收包器验证 webhook 推送闭环（JSON 全字段正确）、
  file 通道同秒防覆盖落盘、digest 有界且网址全来自材料、
  确认门/禁用门按名单生效

**—— v2/M2 记忆 + 会话存档 + 评测套件 ——**

### 新增

- **持久记忆**：memories 结论缓存——识别过的通知（比赛与否都记）直接
  命中、跳过 LLM；正文指纹防过期（内容变了自动重判）；
  `sai memory list/clear`。验收：二次扫描 0 次 LLM 调用
- **会话存档**：agent_sessions / session_events 两表 +
  SessionArchivePort（借鉴 pi 会话后端接口化思想）；模型调用、压缩、
  工具调用、逐条结果全埋点；成本台账按 session_id 归集到任务；
  `sai sessions` / `sai replay 编号` / `GET /sessions(/{id})`
- **评测套件**：31 条真实历史通知考卷（19 比赛 / 12 杂事，人工标注，
  进 git 作为契约）；准确率/精确率/召回/F1 + 比赛名称/截止日期命中；
  `sai eval --save` 建基线，之后每次自动回归比对（阈值 5 个百分点，
  判翻的题逐条点名）。**新纪律：改识别提示词/粗筛词表/模型路由后必跑**
- **评测考卷**：`tests/fixtures/eval_identify.json`（2019-2026 七年
  真实通知，可自行按格式扩充）

### 变更

- usage_records 台账新增 session_id 列（老库幂等就地迁移——账本含真实
  花费，不删库重建）；`SessionSummary` 带 llm_calls，显示区分"¥0（没调用）"
  与"费用未知（调了没配单价）"
- 识别用例：粗筛后查记忆、LLM 后写结论；ScanOutcome 带 from_memory 标记，
  CLI 播报"记忆命中省下 N 次调用"

### 测试

- 离线 99 项（M2 新增 15）+ live 4 项全绿
- 真实验收：二次扫描 0 调用；`sai replay` 回放完整轨迹（含每轮 token
  与总花费）；`sai eval` 两轮真跑 100% 准确率，基线闭环 PASS

**—— v2/M1 成本台账与上下文管理 ——**

### 新增

- **成本台账**：新表 `usage_records` 记录每次 LLM 调用的 token 与费用；
  `sai cost`（支持 `--task` / `--today` / `--date`）与 `GET /cost` 查询；
  能回答"识别 10 条通知花了多少钱"（实测 ¥0.0173/4 次）
- **预算闸门**：`budget_per_task_yuan`（config.yaml 或环境变量
  `BUDGET_PER_TASK_YUAN`）设单任务花费上限，超限熔断；已产生的
  调用与入库结果保留（熔断不是清算）
- **模型路由**：config.yaml 的 `routing` 表按任务指定模型档案
  （识别配便宜模型、生成配强模型），`sai model` 展示路由表，
  台账按模型分组可证
- **上下文管理**：agent 循环接入 AgentScope 内置压缩
  （`context.trigger_ratio`，超阈值自动把旧对话压成结构化摘要）；
  所有工具返回值统一截断（4000 字安全网）；离线测试验证自动压缩真实发生
- **HTTP 接口**：`GET /cost`（按任务/日期过滤的成本账单）

### 设计决策

- **ADR-003**：成本记账走"两条 LLM 通路各设卡口"——结构化调用在
  `OpenAiCompatLlm` 注入 `CostMeter`，agent 循环用 `MeteredChatModel`
  代理包住框架模型客户端（熔断前查 + 调用后记账，用例层零改动）；
  上下文压缩采用框架内置能力不自研（沿 ADR-002 原则），被否决选项
  与已知缺口（压缩摘要调用不入账）见 ADR

### 变更

- `IdentifyCompetitions.execute` 逐条捕获预算熔断，保留已完成结果
- `settings.py` 新增模型单价（`input_price_per_m`/`output_price_per_m`）、
  路由、预算、上下文四组配置；config.yaml 同步
- 熔断时序定稿：`precheck()` 在下一次调用发出前拦截；
  打穿预算的当前调用照常入账

### 测试

- 离线 84 项（M1 新增 22 + /cost 接口回归 3）+ live 4 项全绿
- 真实验收：识别 10 条通知花费可答；`BUDGET_PER_TASK_YUAN=0.001`
  真实熔断演示通过；live 备考路径 13 笔循环调用全部入账

## [0.1.0] - 2026-09-30

首个公开发布版本：完整的"盯官网 → 识别比赛 → 生成材料/备考路径"闭环。

### 新增

- **自动盯官网（P1）**：爬取学院官网通知公告，选择器全配置化，限速 ≥1.5s、
  失败重试、逐条容错；真实页面样本离线测试
- **比赛识别（P2）**：关键词粗筛 + DeepSeek 单次结构化调用；卡片带逐字原文
  证据防幻觉；多模型档案热切换（`sai model use`）
- **存储与报告（P3）**：SQLAlchemy 两表（notices 台账 / competitions 资产）、
  双层幂等防线（代码判重 + 唯一索引）、Markdown 情报报告、可换数据库连接串
- **材料生成（P4）**：AgentScope 2.0.8 驱动的 ReAct 循环；技能外置
  （skills/*.md）；内置 PPT 大纲 / 参赛计划书两个技能；工具轨迹透明播报
- **备考路径（P5）**：联网搜索（Bing→360 多引擎回退，无需密钥）+
  引用存在性校验（死链自动反馈重做），全部链接经过程序验证
- **FastAPI 接口（P6）**：`/health` `/scan` `/competitions` `/report`
  `/generate` `/study-path`；密钥缺失时 LLM 接口优雅降级 503
- **CLI**：`sai scan / identify / report / generate / study-path / model / serve`
- **工程配套**：pytest 58 项（联网验收单独标记）、GitHub Actions CI、
  逐阶段学习讲解文档与术语表、ADR-001/002 架构决策记录

### 设计决策

- DDD 洋葱四层 + 装配根：换爬虫/模型/数据库实现只动一个文件（已实测两次）
- 架构边界：识别/提取走单次结构化调用；材料生成走 agent 循环（ADR-001 → ADR-002 记录了从手写循环到 AgentScope 的完整选型闭环）
