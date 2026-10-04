import asyncio
import logging
import os
import signal
import time
import uuid

from psycopg.types.json import Jsonb

from src.db import db, init_db, get_client_policies
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.pipeline import LeadDiscoveryPipeline

POLL_SECONDS = float(os.getenv('SCRAPPEE_SERP_WORKER_POLL_SECONDS', '1.0'))
STALE_SECONDS = int(os.getenv('SCRAPPEE_SERP_WORKER_STALE_SECONDS', '1800'))
MAX_ATTEMPTS = int(os.getenv('SCRAPPEE_SERP_WORKER_MAX_ATTEMPTS', '3'))
LOG = logging.getLogger('scrapee-serp-worker')
STOP = False


def stop(*_):
    global STOP
    STOP = True


def recover_stale():
    with db() as conn:
        conn.execute(
            "UPDATE serp_lead_queue SET status='queued', locked_at=NULL, updated_at=now() "
            "WHERE status='processing' AND locked_at < now() - (%s * interval '1 second')",
            (STALE_SECONDS,),
        )
        conn.commit()


def claim():
    with db() as conn:
        row = conn.execute(
            "SELECT id,scrap_id,records,attempts FROM serp_lead_queue "
            "WHERE status='queued' ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if not row:
            return None
        qid, scrap_id, records, attempts = row
        conn.execute(
            "UPDATE serp_lead_queue SET status='processing',attempts=%s,locked_at=now(),updated_at=now() WHERE id=%s",
            (attempts + 1, qid),
        )
        conn.commit()
        return str(qid), str(scrap_id), records or [], attempts + 1


def finish(qid, status, error=None):
    with db() as conn:
        conn.execute(
            "UPDATE serp_lead_queue SET status=%s,error=%s,locked_at=NULL,updated_at=now() WHERE id=%s",
            (status, error, uuid.UUID(qid)),
        )
        conn.commit()


def process(item):
    qid, scrap_id, records, attempts = item
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT user_id,criteria,crawler_config FROM scraps WHERE id=%s",
                (uuid.UUID(scrap_id),),
            ).fetchone()
        if not row:
            finish(qid, 'failed', 'Scrap not found')
            return
        user_id, raw_criteria, raw_crawler = row
        criteria = SearchCriteria.model_validate(raw_criteria or {})
        crawler = CrawlerConfig.model_validate(raw_crawler or {})
        prefixes, rules = get_client_policies(str(user_id))
        pipeline = LeadDiscoveryPipeline(
            crawler_config=crawler,
            generic_prefixes=prefixes,
            domain_rules=rules,
            llm_call_counter=lambda: increment_llm_calls(scrap_id),
        )
        asyncio.run(pipeline.process_serp_records(criteria, records, scrap_id=scrap_id))
        finish(qid, 'completed')
        LOG.info('completed queue=%s scrap=%s records=%s', qid, scrap_id, len(records))
    except Exception as exc:
        LOG.exception('queue=%s scrap=%s attempt=%s failed', qid, scrap_id, attempts)
        if attempts < MAX_ATTEMPTS:
            with db() as conn:
                conn.execute(
                    "UPDATE serp_lead_queue SET status='queued',error=%s,locked_at=NULL,updated_at=now() WHERE id=%s",
                    (str(exc)[:4000], uuid.UUID(qid)),
                )
                conn.commit()
        else:
            finish(qid, 'failed', str(exc)[:4000])


def increment_llm_calls(scrap_id):
    with db() as conn:
        conn.execute("UPDATE scraps SET llm_calls=llm_calls+1 WHERE id=%s", (uuid.UUID(scrap_id),))
        conn.commit()


def main():
    global STOP
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_db()
    recover_stale()
    LOG.info('SERP lead worker started; concurrency=1')
    while not STOP:
        recover_stale()
        item = claim()
        if item:
            process(item)
            continue
        time.sleep(POLL_SECONDS)
    LOG.info('SERP lead worker stopped')


if __name__ == '__main__':
    main()
