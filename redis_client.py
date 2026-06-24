import redis
import json
import os

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD') or None

_redis = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
    return _redis

def cache_get(key: str):
    """Get cached value, return None if not found"""
    try:
        r = get_redis()
        val = r.get(key)
        if val is not None:
            return json.loads(val)
        return None
    except Exception:
        return None

def cache_set(key: str, value, expire: int = 300):
    """Set cached value with expiration (seconds)"""
    try:
        r = get_redis()
        r.setex(key, expire, json.dumps(value))
        return True
    except Exception:
        return False

def cache_delete(key: str):
    """Delete cached value"""
    try:
        r = get_redis()
        r.delete(key)
        return True
    except Exception:
        return False

def cache_delete_pattern(pattern: str):
    """Delete all keys matching pattern"""
    try:
        r = get_redis()
        for key in r.scan_iter(match=pattern):
            r.delete(key)
        return True
    except Exception:
        return False
