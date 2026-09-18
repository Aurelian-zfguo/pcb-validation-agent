"""配置加载：settings.yaml、field_mapping.yaml、API密钥解析。"""
import os
from pathlib import Path

import yaml

# 项目根目录 = config.py 的上两级（src/agent -> src -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path | None = None) -> None:
    """从项目根 .env 加载 KEY=VALUE 到环境变量（不覆盖已存在的环境变量）。"""
    p = path or PROJECT_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()  # 导入时即加载，保证 resolve_api_key 能读到 .env 里的密钥


def load_settings(path: Path | None = None) -> dict:
    p = path or PROJECT_ROOT / "config" / "settings.yaml"
    with open(p, encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    # knowledge.base_url 可被环境变量 KNOWLEDGE_BASE_URL 覆盖（容器内指向宿主 B 服务）。
    # 三层防御：setdefault 防 knowledge 缺失、.get 防 base_url 缺失、字面量兜底。
    knowledge = settings.setdefault("knowledge", {})
    knowledge["base_url"] = os.environ.get(
        "KNOWLEDGE_BASE_URL", knowledge.get("base_url", "http://127.0.0.1:8000"))
    return settings


def load_field_mapping(path: Path | None = None) -> dict:
    p = path or PROJECT_ROOT / "config" / "field_mapping.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_api_key(settings: dict) -> str:
    """密钥优先级：环境变量 > settings.yaml。DeepSeek与Claude的密钥都检查。"""
    return (os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("CLAUDE_API_KEY", "")
            or settings.get("llm", {}).get("api_key", ""))
