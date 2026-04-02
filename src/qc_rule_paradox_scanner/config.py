"""配置模块

加载环境变量，提供默认配置，API key 管理
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    max_tokens: int = 2048
    temperature: float = 0.0


@dataclass
class AppConfig:
    """应用配置"""
    llm: LLMConfig = None
    conflict_threshold: float = 0.5
    verbose: bool = False

    def __post_init__(self):
        if self.llm is None:
            self.llm = LLMConfig()


def load_config() -> AppConfig:
    """加载配置

    优先级：环境变量 > .env 文件 > 默认值

    Returns:
        AppConfig 实例
    """
    # 尝试从项目根目录加载 .env 文件
    # 项目根目录是 src 的父目录
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    # 构建 LLM 配置
    llm_config = LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("MODEL_NAME", "gpt-4o-mini"),
        max_tokens=int(os.getenv("MAX_TOKENS", "2048")),
        temperature=float(os.getenv("TEMPERATURE", "0.0")),
    )

    # 构建应用配置
    config = AppConfig(
        llm=llm_config,
        conflict_threshold=float(os.getenv("CONFLICT_THRESHOLD", "0.5")),
        verbose=os.getenv("VERBOSE", "").lower() in ("true", "1", "yes"),
    )

    return config


def check_api_key(config: Optional[AppConfig] = None) -> bool:
    """检查 API key 是否设置

    Args:
        config: 应用配置，如果为 None 则加载配置

    Returns:
        True if API key is set, False otherwise
    """
    if config is None:
        config = load_config()

    return config.llm.api_key is not None and config.llm.api_key != ""


def get_api_key_hint() -> str:
    """获取 API key 设置提示

    Returns:
        设置提示文本
    """
    return """
请通过以下方式之一设置 API Key：

1. 在项目根目录创建 .env 文件：
   OPENAI_API_KEY=your_api_key_here

2. 设置环境变量：
   Linux/macOS: export OPENAI_API_KEY=your_api_key_here
   Windows:    set OPENAI_API_KEY=your_api_key_here

3. 使用 --no-llm 参数跳过 LLM 调用（仅使用规则引擎）
""".strip()


def require_api_key(config: Optional[AppConfig] = None) -> str:
    """获取 API key，如果未设置则退出程序

    Args:
        config: 应用配置，如果为 None 则加载配置

    Returns:
        API key 字符串

    Raises:
        SystemExit: 如果 API key 未设置
    """
    if config is None:
        config = load_config()

    if not check_api_key(config):
        print("错误：未设置 OPENAI_API_KEY")
        print(get_api_key_hint())
        sys.exit(1)

    return config.llm.api_key


# 全局配置实例（延迟加载）
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置实例

    Returns:
        AppConfig 实例
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


if __name__ == "__main__":
    # 测试配置加载
    config = load_config()
    print("=== 配置信息 ===")
    print(f"API Key 设置: {'是' if check_api_key(config) else '否'}")
    if config.llm.api_key:
        masked_key = config.llm.api_key[:8] + "..." + config.llm.api_key[-4:] if len(config.llm.api_key) > 12 else "***"
        print(f"API Key: {masked_key}")
    print(f"Base URL: {config.llm.base_url or '默认'}")
    print(f"Model: {config.llm.model}")
    print(f"冲突阈值: {config.conflict_threshold}")
