"""
统一配置管理模块

负责加载和管理应用程序配置，提供统一的配置访问接口。
"""
from pathlib import Path
from typing import Dict, Optional, Tuple

# 配置文件路径（项目根目录 key.txt）
CONFIG_PATH = Path(__file__).parent / 'key.txt'

# 配置缓存
_config_cache: Optional[Dict[str, str]] = None
_config_signature: Optional[Tuple[int, int]] = None


def load_config(force_reload: bool = False) -> Dict[str, str]:
    """加载配置文件

    Args:
        force_reload: 是否强制重新加载配置（忽略缓存）

    Returns:
        配置字典，key为配置项名称，value为配置值

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件格式错误
    """
    global _config_cache, _config_signature

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    stat = CONFIG_PATH.stat()
    signature = (stat.st_mtime_ns, stat.st_size)

    if (
        _config_cache is not None
        and _config_signature == signature
        and not force_reload
    ):
        return _config_cache

    config = {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                # 跳过空行和注释行
                if not line or line.startswith('#'):
                    continue

                # 解析 key: value 格式
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    if not key:
                        raise ValueError(f"第 {line_num} 行：配置项名称不能为空")

                    config[key] = value
                else:
                    raise ValueError(f"第 {line_num} 行：配置格式错误，应为 'key: value'")

    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"配置文件解析失败: {e}")

    _config_cache = config
    _config_signature = signature
    return config


def get_config(key: str, default: Optional[str] = None) -> str:
    """获取指定配置项的值

    Args:
        key: 配置项名称
        default: 默认值（当配置项不存在时返回）

    Returns:
        配置值

    Raises:
        KeyError: 配置项不存在且未提供默认值
    """
    config = load_config()
    if key not in config:
        if default is not None:
            return default
        raise KeyError(f"配置项 '{key}' 不存在")
    return config[key]


def clear_config_cache():
    """清除配置缓存，下次加载时会重新读取文件"""
    global _config_cache, _config_signature
    _config_cache = None
    _config_signature = None
