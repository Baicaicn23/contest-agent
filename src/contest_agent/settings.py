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


class YamlConfig(BaseModel):
    """config.yaml 整个文件的结构化映射：yaml 长什么样，这里就定义成什么样。"""

    active_model: str = "deepseek"          # 当前生效的模型档案名
    models: dict[str, ModelProfile]         # 全部模型档案，键是档案名
    sources: list[SourceConfig]             # 全部要扫描的网站


class Settings(BaseModel):
    """组装完成的运行时配置。全项目要用配置，都从 load_settings() 拿，
    不要各自散着去读环境变量或 yaml——配置入口只有一个，才好排查问题。"""

    database_url: str        # 数据库连接串（P3 存储层用）
    active_model: str        # 当前生效的模型档案名
    yaml_config: YamlConfig  # 站点源 + 全部模型档案

    @property  # @property 把方法包装成属性：写 settings.active_profile，不用加括号
    def active_profile(self) -> ModelProfile:
        """拿到当前生效的模型档案；配置错了就在这里明确报错。"""
        profile = self.yaml_config.models.get(self.active_model)
        if profile is None:
            raise KeyError(f"active_model '{self.active_model}' 不在 config.yaml models 中")
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

    return Settings(
        # os.environ.get(键, 默认值)：环境变量没设置时用默认值
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        active_model=os.environ.get("ACTIVE_MODEL", yaml_config.active_model),
        yaml_config=yaml_config,
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
