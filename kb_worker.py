import json
import logging
import os
import socket
import threading
import time
import uuid

from rag.job_queue import (
    acknowledge,
    claim,
    heartbeat_claim,
    requeue_expired,
    set_worker_heartbeat,
)
from rag.knowledge_base import begin_job, fail_job, init_db, process_index_job


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("kb-worker")


def main() -> None:
    init_db()
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    logger.info("knowledge-base worker started: %s", worker_id)
    active_claim = {"job_id": None, "token": None}
    active_lock = threading.Lock()

    def heartbeat_loop():
        while True:
            set_worker_heartbeat(worker_id, {
                "worker_id": worker_id,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "heartbeat_at": time.time(),
            })
            with active_lock:
                if active_claim["job_id"]:
                    heartbeat_claim(active_claim["job_id"], active_claim["token"])
            time.sleep(10)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    last_recovery = 0.0
    while True:
        now = time.time()
        if now - last_recovery > 15:
            expired = requeue_expired()
            if expired:
                logger.warning("requeued expired jobs: %s", expired)
            last_recovery = now

        claimed = claim(timeout=2)
        if not claimed:
            continue
        job_id = claimed["job_id"]
        token = claimed["claim_token"]
        with active_lock:
            active_claim.update({"job_id": job_id, "token": token})
        try:
            if not begin_job(job_id, token):
                acknowledge(job_id, token)
                continue
            heartbeat_claim(job_id, token)
            started = time.time()
            result = process_index_job(job_id, token)
            logger.info(json.dumps({
                "event": "kb_job_ready",
                "job_id": job_id,
                "duration_ms": int((time.time() - started) * 1000),
                **result,
            }, ensure_ascii=False))
        except Exception as exc:
            logger.exception("knowledge-base job failed: %s", job_id)
            fail_job(job_id, str(exc))
        finally:
            acknowledge(job_id, token)
            with active_lock:
                active_claim.update({"job_id": None, "token": None})


if __name__ == "__main__":
    main()
