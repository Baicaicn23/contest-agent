"""配置模块：决定"本项目连哪个网站、用哪个模型、数据存哪里"。

读取优先级（从高到低）：
    1. 环境变量（系统里或 .env 文件里设置的，比如 DEEPSEEK_API_KEY）
    2. config.yaml（项目根目录，随 git 提交）
    3. 代码里写死的默认值

为什么密钥不放 config.yaml？——因为 yaml 会提交进 git，
进了 git 的内容就等于公开了；密钥只能活在环境变量里。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# __file__ 是当前文件（settings.py）的路径；.resolve() 转成绝对路径；
# parents[2] 表示沿路径往上走两级：
#   settings.py 所在的 contest_agent 目录 -> src -> 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 默认数据库连接串：项目根目录 data/ 下的 SQLite 文件。
# "sqlite:///" 是 SQLAlchemy 规定的连接串格式，
# 作用类似 Java 里 JDBC 的 "jdbc:mysql://..."（协议://地址）
DEFAULT_DATABASE_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'contest_agent.db'}"


class ModelProfile(BaseModel):
    """一个"模型档案"：描述怎么连上一个大模型服务。

    继承 pydantic 的 BaseModel，可以理解成"自带格式校验的 Java Bean"：
    如果 yaml 里少写字段或类型写错，程序一启动加载配置时就报错，
    而不是等真正调用模型时才炸——问题暴露得越早，修复越便宜。
    """

    name: str         # 档案名，如 deepseek / qwen（yaml 里通常由键名自动补上）
    base_url: str     # 模型服务地址（OpenAI 兼容格式的接口）
    api_key_env: str  # 存放密钥的"环境变量名"——注意存的是名字，不是密钥本身
    model: str        # 具体模型名，如 deepseek-chat

    # —— 计费单价（M1 成本台账用），单位：元 / 百万 token ——
    # 照服务商价目页填（如 DeepSeek 官网"定价"页）；不填 = None，
    # 台账照样记 token 量，但算不出钱。调价时改这里即可，代码不动
    input_price_per_m: float | None = None   # 输入单价
    output_price_per_m: float | None = None  # 输出单价

    def resolve_api_key(self) -> str | None:
        """按档案里记录的变量名，去环境变量里取真实密钥；没设置就返回 None。"""
        return os.environ.get(self.api_key_env)


class SourceConfig(BaseModel):
    """一个"站点源"：描述一个要被扫描的网站（P1 爬虫的输入）。"""

    name: str              # 源的名字，方便日志和报告里辨认
    base_url: str          # 网站域名，如 https://xxx.edu.cn
    list_path: str         # 通知列表页的路径（爬虫从这里拿到"有哪些新通知"）
    detail_pattern: str    # 详情页 URL 的格式模板，{date}/{id} 是占位符
    request_interval: float = Field(default=1.5, ge=0.5)
    # ge=0.5 是 pydantic 的校验：值必须 >= 0.5。
    # 爬虫合规要求相邻请求至少间隔 1.5 秒，别给爬目标网站添堵
    selectors: dict[str, str] = Field(default_factory=dict)
    # CSS 选择器表：从列表页/详情页里"捞出"标题、链接、日期、正文的规则。
    # 选择器写在配置而不是代码里：网站改版时改配置即可，代码不动


class SearchConfig(BaseModel):
    """联网搜索的配置（P5 学习路径用）。"""

    engine_url: str = "https://cn.bing.com/search?q={query}&count=12"
    # {query} 占位符会被替换为 URL 编码后的搜索词
    fallback_engine_url: str = "https://www.so.com/s?q={query}"
    # 回退搜索引擎：主引擎被风控/失败时自动切换（360 搜索，国内直连）
    max_results: int = Field(default=6, ge=1, le=20)


class ContextSettings(BaseModel):
    """上下文管理的配置（M1：agent 循环的自动压缩阈值）。

    trigger_ratio 是"上下文占用达到模型窗口的百分之多少时触发压缩"。
    压缩本体由 AgentScope 框架执行（把旧对话压成结构化摘要），
    我们只负责把阈值配置进去——框架已验证的能力不自研（ADR-002 哲学）。
    """

    trigger_ratio: float = Field(default=0.8, gt=0, le=0.9)
    # le=0.9：压缩本身也要占窗口，阈值给到 90% 以上就来不及了（框架的同款约束）


class SmtpConfig(BaseModel):
    """邮件推送的连接配置（M3）。密码只存环境变量名，和模型密钥同一套安全规矩。"""

    host: str                          # SMTP 服务器，如 smtp.qq.com
    port: int = 465                    # 端口（465 = SSL）
    user: str                          # 发件邮箱账号
    password_env: str = "SMTP_PASSWORD"  # 存授权码/密码的环境变量名
    from_addr: str = ""                # 发件人显示地址；空则用 user
    to_addrs: list[str] = Field(default_factory=list)  # 收件人列表


class PushConfig(BaseModel):
    """推送通道配置（M3 定时推送用）。

    三个通道互相独立：配了哪个就启用哪个，全不配 = 只在终端播报不外推。
    - webhook：往一个 URL POST JSON（钉钉/企微/Server酱等机器人的通用形态）；
    - file：写 Markdown 文件到本地目录（开发调试、不想配外部服务时用）；
    - smtp：发邮件（需要邮箱开 SMTP 并拿授权码）。
    """

    webhook_url: str | None = None     # 接收 POST 的 URL；None = 不启用
    webhook_timeout: float = Field(default=10, gt=0)  # POST 超时（秒）
    file_dir: str | None = None        # 文件通道输出目录；None = 不启用
    smtp: SmtpConfig | None = None     # 邮件通道；None = 不启用


class PermissionConfig(BaseModel):
    """工具权限门的配置（M3）。两个名单都是空 = 所有工具照旧自动放行。

    - confirm_tools：交互模式（终端有人）下，执行前要 y/N 确认的工具名；
    - unattended_deny_tools：无人值守（cron / sai watch / HTTP 服务）时
      一律拒绝的工具名——拒绝理由会回给模型，让它换路走。
    """

    confirm_tools: list[str] = Field(default_factory=list)
    unattended_deny_tools: list[str] = Field(default_factory=list)


class YamlConfig(BaseModel):
    """config.yaml 整个文件的结构化映射：yaml 长什么样，这里就定义成什么样。"""

    active_model: str = "deepseek"          # 当前生效的模型档案名
    models: dict[str, ModelProfile]         # 全部模型档案，键是档案名
    sources: list[SourceConfig]             # 全部要扫描的网站
    search: SearchConfig = SearchConfig()   # 联网搜索配置（缺省也能跑）
    # —— M1 新增：按任务路由模型档案。键是任务名（identify / generate /
    # study_path），值是档案名；某个任务没写就用 active_model 兜底。
    # 用途：高频任务配便宜模型、低频重活配强模型，省钱不吃性能
    routing: dict[str, str] = Field(default_factory=dict)
    budget_per_task_yuan: float | None = None  # 单任务预算上限（元）；None = 不限
    context: ContextSettings = ContextSettings()  # agent 循环的上下文压缩阈值
    push: PushConfig = PushConfig()        # 推送通道（M3 定时推送用，默认全关）
    permissions: PermissionConfig = PermissionConfig()  # 工具权限门（M3，默认全放行）
    # —— M5 插件开关：能力插件的安装状态（前端插件市场写这里）。
    # 未列出的能力视为开启；features: eval=false 表示评测插件"未安装"
    features: dict[str, bool] = Field(default_factory=dict)
    # 完全访问总闸（M5）：True = 权限门全放行（名单忽略）；False = 名单生效
    access_full: bool = False


class Settings(BaseModel):
    """组装完成的运行时配置。全项目要用配置，都从 load_settings() 拿，
    不要各自散着去读环境变量或 yaml——配置入口只有一个，才好排查问题。"""

    database_url: str        # 数据库连接串（P3 存储层用）
    active_model: str        # 当前生效的模型档案名
    yaml_config: YamlConfig  # 站点源 + 全部模型档案
    budget_per_task_yuan: float | None = None  # 单任务预算上限（M1，env 可覆盖）

    @property  # @property 把方法包装成属性：写 settings.active_profile，不用加括号
    def active_profile(self) -> ModelProfile:
        """拿到当前生效的模型档案；配置错了就在这里明确报错。"""
        profile = self.yaml_config.models.get(self.active_model)
        if profile is None:
            raise KeyError(f"active_model '{self.active_model}' 不在 config.yaml models 中")
        return profile

    def profile_for_task(self, task_type: str) -> ModelProfile:
        """按任务名拿模型档案（M1 模型路由的解析入口）。

        规则：先查 routing 表（identify -> 便宜档案、generate -> 强档案），
        没配这个任务就用 active_model 兜底。routing 写错档案名时
        在这里明确报错，而不是等到调用时才炸。
        """
        name = self.yaml_config.routing.get(task_type) or self.active_model
        profile = self.yaml_config.models.get(name)
        if profile is None:
            raise KeyError(
                f"任务 {task_type!r} 路由到的档案 '{name}' 不在 config.yaml models 中"
            )
        return profile


def load_yaml_config(path: Path | None = None) -> YamlConfig:
    """读取并校验 config.yaml，返回结构化配置对象。

    path 不传就读项目根目录的 config.yaml；测试时可以传临时文件来模拟各种配置。
    """
    config_path = path or (PROJECT_ROOT / "config.yaml")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)  # 把 yaml 文本解析成 Python 字典

    # yaml 里模型档案的"键名"就是档案名（如 models: 下面的 deepseek:）。
    # 这里把键名自动补写进档案对象，避免要求用户在 yaml 里再重复写一遍 name
    models = raw.get("models")
    if models:
        for name, profile in models.items():
            profile.setdefault("name", name)

    # model_validate：把字典交给 pydantic 校验并转成 YamlConfig 对象。
    # 字段缺失、类型不对、间隔低于下限，都在这一步报错
    return YamlConfig.model_validate(raw)


def load_dotenv(path: Path | None = None) -> None:
    """把项目根目录 .env 文件里的 KEY=VALUE 读进环境变量。

    规则：已存在的环境变量不覆盖（真正的环境变量 > .env 文件），
    空行、# 开头的注释行、没有等号的行都跳过。

    为什么不装 python-dotenv 库？——这个功能本身就十几行，
    手写一遍正好看清"密钥是怎么进到进程环境里"的。
    """
    env_file = path or (PROJECT_ROOT / ".env")
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


@lru_cache  # Python 自带的"结果缓存"：第二次调用直接返回第一次的结果，
            # 效果类似手写单例——保证整个进程拿到的是同一份 Settings
def load_settings() -> Settings:
    """读取完整运行时配置（进程内只真正读取一次）。

    env 优先的效果举例：在终端设了 ACTIVE_MODEL=qwen 环境变量，
    就算 yaml 里写的 active_model 是 deepseek，也会用 qwen——
    临时切换模型做实验时，不用改文件。
    """
    load_dotenv()  # 先把 .env 里的密钥装进环境，后面的解析才有得用
    yaml_config = load_yaml_config()

    # 预算上限支持环境变量覆盖（BUDGET_PER_TASK_YUAN=5 表示 5 元；
    # 设成 0 或留空表示关闭），方便临时实验不改文件
    raw_budget: str | None = os.environ.get("BUDGET_PER_TASK_YUAN")
    if raw_budget:
        parsed = float(raw_budget)
        budget = parsed if parsed > 0 else None
    else:
        budget = yaml_config.budget_per_task_yuan

    return Settings(
        # os.environ.get(键, 默认值)：环境变量没设置时用默认值
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        active_model=os.environ.get("ACTIVE_MODEL", yaml_config.active_model),
        yaml_config=yaml_config,
        budget_per_task_yuan=budget,
    )


def set_active_model(name: str, config_path: Path | None = None) -> None:
    """把切换后的模型档案名写回 config.yaml（sai model use 的后端）。

    用"按行替换"而不是 yaml 库整体重写：整体重写会把文件里的
    中文注释全部冲掉，按行替换只动 active_model 那一行，注释原样保留。
    """
    config_file = config_path or (PROJECT_ROOT / "config.yaml")

    # 先验证目标档案存在，免得把配置文件写成谁也不认识的档案名
    yaml_config = load_yaml_config(config_file)
    if name not in yaml_config.models:
        available = ", ".join(yaml_config.models)
        raise KeyError(f"模型档案 '{name}' 不存在，可选：{available}")

    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("active_model:"):
            # 保留这一行原有的缩进，只替换值
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f"{indent}active_model: {name}\n"
            replaced = True
            break
    if not replaced:
        raise ValueError("config.yaml 里找不到 active_model 配置行")

    config_file.write_text("".join(lines), encoding="utf-8")
    # 清掉 load_settings 的进程内缓存，让切换立刻生效
    load_settings.cache_clear()


def set_budget(yuan: float | None, config_path: Path | None = None) -> None:
    """把预算上限写回 config.yaml（M4 前端 Settings 面板的后端）。

    沿用 set_active_model 的"按行替换"策略：只动 budget_per_task_yuan
    那一行，yaml 里的中文注释原样保留（整文件重写会把注释全冲掉）。
    yuan=None 写回 null（不限预算）；负数直接拒绝。
    """
    if yuan is not None and yuan < 0:
        raise ValueError("预算不能是负数（0 或 null 表示不限）")

    config_file = config_path or (PROJECT_ROOT / "config.yaml")
    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("budget_per_task_yuan:"):
            indent = line[: len(line) - len(line.lstrip())]
            value = "null" if yuan is None else f"{yuan}"
            lines[index] = f"{indent}budget_per_task_yuan: {value}\n"
            replaced = True
            break
    if not replaced:
        raise ValueError("config.yaml 里找不到 budget_per_task_yuan 配置行")

    config_file.write_text("".join(lines), encoding="utf-8")
    load_settings.cache_clear()


def set_feature(key: str, enabled: bool, config_path: Path | None = None) -> None:
    """写 config.yaml 的 features 插件开关（M5 插件市场的后端）。

    行级定位 features: 段下的 `  key:` 行改值；段里没有该键就插一行。
    features 是 M5 新增段、无历史注释负担，插入安全。
    """
    config_file = config_path or (PROJECT_ROOT / "config.yaml")
    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)

    feature_start = None
    for index, line in enumerate(lines):
        if line.rstrip("\n") == "features:":
            feature_start = index + 1
            break
    if feature_start is None:
        raise ValueError("config.yaml 里找不到 features: 配置段")

    target = f"  {key}:"
    value = "true" if enabled else "false"
    for index in range(feature_start, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith("  "):
            break  # 走出了 features 段
        if line.strip().startswith(f"{key}:"):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f"{indent}{key}: {value}\n"
            config_file.write_text("".join(lines), encoding="utf-8")
            load_settings.cache_clear()
            return

    # 段内没有该键：插到段首
    lines.insert(feature_start, f"{target} {value}\n")
    config_file.write_text("".join(lines), encoding="utf-8")
    load_settings.cache_clear()


def set_access_full(enabled: bool, config_path: Path | None = None) -> None:
    """写完全访问总闸（M5 前端的"⚠ 完全访问"开关后端）。

    True = 权限门全放行（名单忽略）；False = 名单生效。行级替换保注释。
    """
    config_file = config_path or (PROJECT_ROOT / "config.yaml")
    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("access_full:"):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f"{indent}access_full: {'true' if enabled else 'false'}\n"
            replaced = True
            break
    if not replaced:
        raise ValueError("config.yaml 里找不到 access_full 配置行")
    config_file.write_text("".join(lines), encoding="utf-8")
    load_settings.cache_clear()
