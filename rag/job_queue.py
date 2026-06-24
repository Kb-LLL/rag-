import json
import os
import time
import uuid
from typing import Dict, List, Optional

from redis_client import get_redis


QUEUE_KEY = os.getenv("KB_QUEUE_KEY", "kb:jobs:pending")
PROCESSING_KEY = os.getenv("KB_PROCESSING_KEY", "kb:jobs:processing")
CLAIMS_KEY = os.getenv("KB_CLAIMS_KEY", "kb:jobs:claims")
WORKER_HEARTBEAT_PREFIX = "kb:worker:"
VISIBILITY_TIMEOUT = int(os.getenv("KB_JOB_VISIBILITY_TIMEOUT", "300"))


CLAIM_SCRIPT = """
local job_id = redis.call('RPOP', KEYS[1])
if not job_id then return nil end
redis.call('ZADD', KEYS[2], ARGV[1], job_id)
redis.call('HSET', KEYS[3], job_id, ARGV[2])
return job_id
"""


def enqueue(job_id: str) -> None:
    redis = get_redis()
    redis.lrem(QUEUE_KEY, 0, job_id)
    redis.lpush(QUEUE_KEY, job_id)


def claim(timeout: int = 2) -> Optional[Dict[str, str]]:
    redis = get_redis()
    deadline = time.time() + timeout
    while time.time() < deadline:
        token = uuid.uuid4().hex
        job_id = redis.eval(
            CLAIM_SCRIPT,
            3,
            QUEUE_KEY,
            PROCESSING_KEY,
            CLAIMS_KEY,
            time.time() + VISIBILITY_TIMEOUT,
            token,
        )
        if job_id:
            return {"job_id": job_id, "claim_token": token}
        time.sleep(0.2)
    return None


def heartbeat_claim(job_id: str, claim_token: str) -> bool:
    redis = get_redis()
    if redis.hget(CLAIMS_KEY, job_id) != claim_token:
        return False
    redis.zadd(PROCESSING_KEY, {job_id: time.time() + VISIBILITY_TIMEOUT})
    return True


def acknowledge(job_id: str, claim_token: str) -> bool:
    redis = get_redis()
    if redis.hget(CLAIMS_KEY, job_id) != claim_token:
        return False
    pipe = redis.pipeline()
    pipe.zrem(PROCESSING_KEY, job_id)
    pipe.hdel(CLAIMS_KEY, job_id)
    pipe.execute()
    return True


def requeue_expired() -> List[str]:
    redis = get_redis()
    expired = redis.zrangebyscore(PROCESSING_KEY, "-inf", time.time())
    for job_id in expired:
        pipe = redis.pipeline()
        pipe.zrem(PROCESSING_KEY, job_id)
        pipe.hdel(CLAIMS_KEY, job_id)
        pipe.lrem(QUEUE_KEY, 0, job_id)
        pipe.lpush(QUEUE_KEY, job_id)
        pipe.execute()
    return expired


def set_worker_heartbeat(worker_id: str, payload: Dict) -> None:
    get_redis().setex(
        f"{WORKER_HEARTBEAT_PREFIX}{worker_id}",
        30,
        json.dumps(payload, ensure_ascii=False),
    )


def list_workers() -> List[Dict]:
    redis = get_redis()
    workers = []
    for key in redis.scan_iter(match=f"{WORKER_HEARTBEAT_PREFIX}*"):
        value = redis.get(key)
        if value:
            try:
                workers.append(json.loads(value))
            except json.JSONDecodeError:
                continue
    return workers
