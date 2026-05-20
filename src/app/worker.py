import asyncio
import json
import logging
import os
import signal
import aiomysql
import redis.asyncio as redis

from .services import RedisCacheService, MySQLOrderRepository

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

class TicketQueueWorker:
    """Worker class to consume queue requests, check Lua cache, and persist to MySQL."""

    def __init__(
        self,
        redis_client: redis.Redis,
        db_pool: aiomysql.Pool,
        queue_name: str = "ticket:request:queue"
    ) -> None:
        self.redis = redis_client
        self.pool = db_pool
        self.queue_name = queue_name
        self.cache_service = RedisCacheService(self.redis)
        self.order_repo = MySQLOrderRepository(self.pool, self.redis)
        self.running = False

    async def start(self) -> None:
        """Load Lua script and start the consumption loop."""
        logger.info("Initializing Cache Lua script registration...")
        await self.cache_service.register_script()
        
        self.running = True
        logger.info(f"Worker started. Monitoring queue: {self.queue_name}")
        
        while self.running:
            try:
                # Pop request from the queue with a timeout of 1 second
                # Use brpop to block and prevent CPU hogging.
                result = await self.redis.brpop(self.queue_name, timeout=1)
                if not result:
                    continue

                _, message_json = result
                payload = json.loads(message_json)
                
                member_id = payload.get("member_id")
                event_id = payload.get("event_id")
                
                if member_id is None or event_id is None:
                    logger.warning(f"Malformed queue message discarded: {payload}")
                    continue

                logger.info(f"Processing reservation: member={member_id}, event={event_id}")

                # 1. Execute Atomic stock verification & pre-deduct on Redis Cache
                status = await self.cache_service.evaluate_lua_reserve(member_id, event_id)

                if status == "SUCCESS":
                    logger.info(f"Reservation pre-deduct SUCCESS for member={member_id}. Persisting to DB...")
                    # 2. Persist SUCCESS orders to MySQL database
                    db_success = await self.order_repo.create_order(member_id, event_id, "SUCCESS")
                    if not db_success:
                        logger.error(f"Failed to persist successful order to DB for member={member_id}")
                elif status == "SOLD_OUT":
                    # Mark sold out state globally to instantly fail future HTTP request checks
                    await self.redis.set("ticket:soldout:flag", "true", ex=86400)
                    logger.info(f"Event {event_id} is SOLD_OUT. Discarding request for member={member_id}")
                elif status == "DUPLICATE_ORDER":
                    logger.info(f"Duplicate booking request rejected for member={member_id}")

                # 3. Clean up the enqueued status key since request is processed
                enqueued_key = f"ticket:user:enqueued:{event_id}:{member_id}"
                await self.redis.delete(enqueued_key)

            except Exception as e:
                logger.error(f"Error encountered during request processing: {e}")
                # Wait before retrying to prevent rapid error loops
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal the loop to stop running."""
        logger.info("Stopping worker loop...")
        self.running = False


async def main() -> None:
    # Read configuration from environment variables
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_url = f"redis://{redis_host}:6379"
    mysql_host = os.getenv("DB_HOST", "localhost")
    mysql_port = int(os.getenv("DB_PORT", "3306"))
    mysql_user = os.getenv("DB_USER", "ticket_user")
    mysql_password = os.getenv("DB_PASSWORD", "ticket_password")
    mysql_db = os.getenv("DB_NAME", "ticketing_db")

    redis_client = redis.from_url(redis_url)
    db_pool = None
    logger.info(f"Connecting to MySQL at: {mysql_host}:{mysql_port}, db={mysql_db}")
    for attempt in range(1, 6):
        try:
            db_pool = await aiomysql.create_pool(
                host=mysql_host,
                port=mysql_port,
                user=mysql_user,
                password=mysql_password,
                db=mysql_db,
                minsize=5,
                maxsize=10,
                autocommit=True
            )
            logger.info("Successfully created MySQL connection pool.")
            break
        except Exception as e:
            logger.warning(f"Attempt {attempt}/5: Failed to create MySQL pool: {e}. Retrying in 2 seconds...")
            await asyncio.sleep(2)
            
    if db_pool is None:
        raise RuntimeError("Failed to initialize MySQL pool after 5 attempts.")

    worker = TicketQueueWorker(redis_client, db_pool)

    # Setup Graceful shutdown signal handling
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    try:
        await worker.start()
    finally:
        logger.info("Closing database and cache pools...")
        await redis_client.close()
        db_pool.close()
        await db_pool.wait_closed()
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
