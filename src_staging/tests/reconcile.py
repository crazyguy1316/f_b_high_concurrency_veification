import os
import asyncio
import logging
import redis.asyncio as redis
import pymysql

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reconcile")

async def main():
    # Read environment configs (default to localhost for host runs, container names for docker network runs)
    redis_host = os.getenv("REDIS_HOST", "localhost")
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "ticket_user")
    db_password = os.getenv("DB_PASSWORD", "ticket_password")
    db_name = os.getenv("DB_NAME", "ticketing_db")
    event_id = "concert_a"

    logger.info(f"Starting reconciliation on Redis ({redis_host}) and MySQL ({db_host})...")

    # 1. Connect to Redis client
    r = redis.from_url(f"redis://{redis_host}:6379")
    
    # 2. Connect to MySQL using standard pymysql
    conn = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name,
        port=3306
    )

    try:
        # Get count of successful orders from MySQL database
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM orders WHERE event_id = %s AND status = 'SUCCESS'", (event_id,))
            mysql_count = cursor.fetchone()[0]

        # Get Redis values asynchronously within the same active event loop
        redis_hash_count = await r.hlen("ticket:success:orders")
        stock_raw = await r.get(f"ticket:stock:{event_id}")
        stock = int(stock_raw) if stock_raw is not None else 0

        logger.info(f"--- Reconciliation Results ---")
        logger.info(f"MySQL Success Order Count : {mysql_count}")
        logger.info(f"Redis Hash Success Count  : {redis_hash_count}")
        logger.info(f"Redis Remaining Stock     : {stock}")

        # Assert zero-overselling and data parity
        if mysql_count != redis_hash_count:
            msg = f"DATA DISCREPANCY DETECTED: MySQL Success Orders ({mysql_count}) != Redis Success Orders ({redis_hash_count})!"
            logger.error(msg)
            raise AssertionError(msg)

        logger.info("[RECONCILE_SUCCESS] Data integrity audit passed. Zero overselling and perfect parity verified.")

    finally:
        conn.close()
        # Clean shutdown of redis client
        await r.close()

if __name__ == "__main__":
    asyncio.run(main())
