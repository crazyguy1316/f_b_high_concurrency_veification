import json
import logging
import os
from typing import Optional
import aiomysql
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from .interfaces import (
    ITokenValidator,
    IQueuePublisher,
    IOrderRepository,
    ICacheService,
    QueuePayload,
)

logger = logging.getLogger(__name__)

class SimpleTokenValidator(ITokenValidator):
    """
    Lightweight token validator for sandbox load-testing purposes.

    [DESIGN DECISION — See ADR-001, Section 2: Lightweight Authentication]
    This intentionally uses a simple string-concatenation token pattern ("token_<member_id>")
    instead of JWT or cryptographic signing. The goal is to eliminate CPU overhead from
    complex signature verification, so that 100% of compute resources are available
    for benchmarking the core high-concurrency ticketing pipeline (Redis Lua atomicity,
    async queue, and MySQL persistence). This is NOT intended for production use.
    """

    async def validate_token(self, member_id: int, token: str) -> bool:
        if not token or not member_id:
            return False
        # Sandbox-only lightweight pattern: "token_<member_id>"
        # Intentionally minimal — see class docstring for rationale.
        expected_token = f"token_{member_id}"
        return token == expected_token


class RedisQueuePublisher(IQueuePublisher):
    """Concrete message queue publisher using Redis List."""

    def __init__(self, redis_client: Redis, queue_name: str = "ticket:request:queue") -> None:
        self.redis = redis_client
        self.queue_name = queue_name

    async def enqueue_request(self, payload: QueuePayload) -> bool:
        try:
            member_id = payload.get("member_id")
            event_id = payload.get("event_id")
            message_json = json.dumps(payload)
            # Push request to the tail of the list
            await self.redis.lpush(self.queue_name, message_json)
            
            # Record enqueue state in Redis to distinguish PENDING from NOT_FOUND
            if member_id is not None and event_id is not None:
                enqueued_key = f"ticket:user:enqueued:{event_id}:{member_id}"
                await self.redis.set(enqueued_key, "1", ex=3600)
                
            return True
        except Exception as e:
            logger.error(f"Failed to enqueue request to Redis: {e}")
            return False


class MySQLOrderRepository(IOrderRepository):
    """Concrete repository for persisting orders in MySQL and checking status."""

    def __init__(self, db_pool: aiomysql.Pool, redis_client: Redis) -> None:
        self.pool = db_pool
        self.redis = redis_client

    async def create_order(self, member_id: int, event_id: str, status: str) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = """
                        INSERT INTO orders (member_id, event_id, status)
                        VALUES (%s, %s, %s)
                    """
                    await cur.execute(sql, (member_id, event_id, status))
                    await conn.commit()
                    return True
        except aiomysql.IntegrityError as ie:
            # Handles duplicate keys safely (UNIQUE KEY uk_member_event constraint)
            logger.warning(f"Duplicate order insert prevented for member={member_id}, event={event_id}: {ie}")
            return False
        except Exception as e:
            logger.error(f"Database insertion failed for member={member_id}, event={event_id}: {e}")
            return False

    async def get_order_status(self, member_id: int, event_id: str) -> str:
        # 1. Query MySQL Database
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = "SELECT status FROM orders WHERE member_id = %s AND event_id = %s LIMIT 1"
                    await cur.execute(sql, (member_id, event_id))
                    row = await cur.fetchone()
                    if row:
                        return str(row[0])
        except Exception as e:
            logger.error(f"Error querying database for status: {e}")

        # 2. Query Redis Success orders Hash
        try:
            success_hash_key = "ticket:success:orders"
            is_winner = await self.redis.hexists(success_hash_key, str(member_id))
            if is_winner:
                return "SUCCESS"
        except Exception as e:
            logger.error(f"Error querying Redis success hash for status: {e}")

        # 3. Check if enqueued in Redis (PENDING)
        try:
            enqueued_key = f"ticket:user:enqueued:{event_id}:{member_id}"
            is_enqueued = await self.redis.exists(enqueued_key)
            if is_enqueued:
                return "PENDING"
        except Exception as e:
            logger.error(f"Error querying Redis enqueued key: {e}")

        # 4. Check if Sold Out has occurred
        try:
            soldout_flag = await self.redis.get("ticket:soldout:flag")
            if soldout_flag == b"true" or soldout_flag == "true":
                return "FAILED"
        except Exception as e:
            logger.error(f"Error checking Redis soldout flag: {e}")

        # 5. Otherwise, order was never requested or has expired
        return "NOT_FOUND"


class RedisCacheService(ICacheService):
    """Concrete cache service that pre-loads and executes the Redis Lua script."""

    def __init__(self, redis_client: Redis, lua_script_path: Optional[str] = None) -> None:
        self.redis = redis_client
        self.lua_sha: Optional[str] = None
        self.script_content: str = ""

        if lua_script_path is None:
            # Locate script relative to current directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            lua_script_path = os.path.join(current_dir, "..", "cache", "lua", "reserve_ticket.lua")
        
        self.lua_script_path = lua_script_path
        self._load_script_file()

    def _load_script_file(self) -> None:
        try:
            with open(self.lua_script_path, "r", encoding="utf-8") as f:
                self.script_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read Lua script file from {self.lua_script_path}: {e}")
            raise

    async def register_script(self) -> None:
        """Register the Lua script inside Redis and cache the SHA hash."""
        try:
            self.lua_sha = await self.redis.script_load(self.script_content)
            logger.info(f"Lua script loaded successfully. SHA: {self.lua_sha}")
        except Exception as e:
            logger.error(f"Failed to script_load in Redis: {e}")
            raise

    async def evaluate_lua_reserve(self, member_id: int, event_id: str) -> str:
        # Build Keys:
        # KEYS[1]: has_bought flag
        # KEYS[2]: stock key
        # KEYS[3]: success orders hash
        has_bought_key = f"ticket:user:has_bought:{event_id}:{member_id}"
        stock_key = f"ticket:stock:{event_id}"
        success_orders_key = "ticket:success:orders"

        keys = [has_bought_key, stock_key, success_orders_key]
        args = [str(member_id), str(event_id)]

        if not self.lua_sha:
            await self.register_script()

        try:
            result = await self.redis.evalsha(self.lua_sha, len(keys), *keys, *args)
            return result.decode("utf-8") if isinstance(result, bytes) else str(result)
        except ResponseError as re:
            # Fallback if the script is not cached in Redis
            if "NOSCRIPT" in str(re):
                logger.warning("Lua script SHA not found. Registering and evaluating script.")
                await self.register_script()
                result = await self.redis.eval(self.script_content, len(keys), *keys, *args)
                return result.decode("utf-8") if isinstance(result, bytes) else str(result)
            raise
        except Exception as e:
            logger.error(f"Lua evaluation error: {e}")
            raise
