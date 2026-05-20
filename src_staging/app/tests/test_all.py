import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import status

if "src_staging" in __file__:
    import src_staging.app.main as main
else:
    import src.app.main as main

# Prevent FastAPI dependency injection 503 errors by mocking the global connection references
main.redis_client = AsyncMock()
main.db_pool = MagicMock()

if "src_staging" in __file__:
    from src_staging.app.main import app, get_token_validator, get_queue_publisher, get_order_repository
    from src_staging.app.services import SimpleTokenValidator, RedisQueuePublisher, MySQLOrderRepository, RedisCacheService
    from src_staging.app.worker import TicketQueueWorker
else:
    from src.app.main import app, get_token_validator, get_queue_publisher, get_order_repository
    from src.app.services import SimpleTokenValidator, RedisQueuePublisher, MySQLOrderRepository, RedisCacheService
    from src.app.worker import TicketQueueWorker

# 1. Test SimpleTokenValidator
@pytest.mark.asyncio
async def test_simple_token_validator():
    validator = SimpleTokenValidator()
    
    # Valid pattern
    assert await validator.validate_token(12345, "token_12345") is True
    # Invalid patterns
    assert await validator.validate_token(12345, "token_wrong") is False
    assert await validator.validate_token(12345, "") is False
    assert await validator.validate_token(0, "token_0") is False


# 2. Test RedisQueuePublisher
@pytest.mark.asyncio
async def test_redis_queue_publisher():
    mock_redis = AsyncMock()
    publisher = RedisQueuePublisher(mock_redis, queue_name="test_queue")
    
    payload = {"event_id": "concert_a", "member_id": 999}
    success = await publisher.enqueue_request(payload)
    
    assert success is True
    # Check LPUSH call
    mock_redis.lpush.assert_called_once_with("test_queue", json.dumps(payload))
    # Check enqueued tracking key set call
    mock_redis.set.assert_called_once_with("ticket:user:enqueued:concert_a:999", "1", ex=3600)


# 3. Test MySQLOrderRepository - get_order_status
@pytest.mark.asyncio
async def test_mysql_order_repository_get_status_found_db():
    mock_db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.__aenter__.return_value = mock_cur
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    
    mock_cur.fetchone.return_value = ("SUCCESS",)
    
    mock_redis = AsyncMock()
    repo = MySQLOrderRepository(mock_db_pool, mock_redis)
    
    status_result = await repo.get_order_status(999, "concert_a")
    assert status_result == "SUCCESS"
    mock_cur.execute.assert_called_once()


@pytest.mark.asyncio
async def test_mysql_order_repository_get_status_found_redis_hash():
    mock_db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.__aenter__.return_value = mock_cur
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    
    mock_cur.fetchone.return_value = None
    
    mock_redis = AsyncMock()
    # Redis success hash hit
    mock_redis.hexists.return_value = True
    
    repo = MySQLOrderRepository(mock_db_pool, mock_redis)
    status_result = await repo.get_order_status(999, "concert_a")
    
    assert status_result == "SUCCESS"
    mock_redis.hexists.assert_called_once_with("ticket:success:orders", "999")


@pytest.mark.asyncio
async def test_mysql_order_repository_get_status_pending():
    mock_db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.__aenter__.return_value = mock_cur
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    
    mock_cur.fetchone.return_value = None
    
    mock_redis = AsyncMock()
    mock_redis.hexists.return_value = False
    # Redis enqueued key exists (PENDING)
    mock_redis.exists.return_value = True
    
    repo = MySQLOrderRepository(mock_db_pool, mock_redis)
    status_result = await repo.get_order_status(999, "concert_a")
    
    assert status_result == "PENDING"
    mock_redis.exists.assert_called_once_with("ticket:user:enqueued:concert_a:999")


@pytest.mark.asyncio
async def test_mysql_order_repository_get_status_failed():
    mock_db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.__aenter__.return_value = mock_cur
    mock_conn.cursor = MagicMock(return_value=mock_cur)
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    
    mock_cur.fetchone.return_value = None
    
    mock_redis = AsyncMock()
    mock_redis.hexists.return_value = False
    mock_redis.exists.return_value = False
    # Redis soldout is true
    mock_redis.get.return_value = b"true"
    
    repo = MySQLOrderRepository(mock_db_pool, mock_redis)
    status_result = await repo.get_order_status(999, "concert_a")
    
    assert status_result == "FAILED"


# 4. Test RedisCacheService Lua registration and run
@pytest.mark.asyncio
async def test_redis_cache_service():
    mock_redis = AsyncMock()
    mock_redis.script_load.return_value = "fake_sha_digest_123"
    mock_redis.evalsha.return_value = b"SUCCESS"
    
    # Mock the reading of the Lua script file to avoid path issues during unit tests
    with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="-- Lua script content")))))):
        cache_service = RedisCacheService(mock_redis, lua_script_path="mock_path.lua")
        
        # Test evaluation
        result = await cache_service.evaluate_lua_reserve(999, "concert_a")
        
        assert result == "SUCCESS"
        mock_redis.evalsha.assert_called_once()


# 5. Test API Endpoints using FastAPI TestClient
client = TestClient(app)

def test_api_reserve_ticket_unauthorized():
    mock_validator = MagicMock()
    mock_validator.validate_token = AsyncMock(return_value=False)
    app.dependency_overrides[get_token_validator] = lambda: mock_validator
    
    resp = client.post("/api/v1/tickets/concert_x/reserve", json={"member_id": 1, "token": "invalid"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"]["error"] == "UNAUTHORIZED"


def test_api_reserve_ticket_success():
    mock_validator = MagicMock()
    mock_validator.validate_token = AsyncMock(return_value=True)
    mock_publisher = MagicMock()
    mock_publisher.enqueue_request = AsyncMock(return_value=True)
    app.dependency_overrides[get_token_validator] = lambda: mock_validator
    app.dependency_overrides[get_queue_publisher] = lambda: mock_publisher
    
    resp = client.post("/api/v1/tickets/concert_x/reserve", json={"member_id": 123, "token": "token_123"})
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "QUEUED"
    assert "poll_url" in data
    assert "/orders/concert_x/123" in data["poll_url"]


def test_api_poll_order_status_success():
    mock_repo = MagicMock()
    mock_repo.get_order_status = AsyncMock(return_value="SUCCESS")
    app.dependency_overrides[get_order_repository] = lambda: mock_repo
    
    resp = client.get("/api/v1/orders/concert_x/123")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "SUCCESS"


def test_api_poll_order_status_not_found():
    mock_repo = MagicMock()
    mock_repo.get_order_status = AsyncMock(return_value="NOT_FOUND")
    app.dependency_overrides[get_order_repository] = lambda: mock_repo
    
    resp = client.get("/api/v1/orders/concert_x/123")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"]["error"] == "NOT_FOUND"


# 6. Test Background Worker consumption
@pytest.mark.asyncio
async def test_worker_consumption_loop():
    mock_redis = AsyncMock()
    mock_db_pool = MagicMock()
    
    worker = TicketQueueWorker(mock_redis, mock_db_pool)
    worker.cache_service = AsyncMock()
    worker.order_repo = AsyncMock()
    
    # Mock BRPOP to return a valid message, then raise exception or stop loop
    worker.cache_service.evaluate_lua_reserve.return_value = "SUCCESS"
    
    # Set brpop side effect to yield one request and then stop the worker
    async def brpop_mock(queue, timeout):
        # Stop worker inside the side effect to terminate loop after 1 run
        worker.stop()
        return ("test_queue", json.dumps({"member_id": 456, "event_id": "concert_b"}).encode())
        
    mock_redis.brpop.side_effect = brpop_mock
    
    await worker.start()
    
    # Verify Lua script execution
    worker.cache_service.evaluate_lua_reserve.assert_called_once_with(456, "concert_b")
    # Verify SQL order creation was triggered
    worker.order_repo.create_order.assert_called_once_with(456, "concert_b", "SUCCESS")
    # Verify cleanup of the enqueued Status key
    mock_redis.delete.assert_called_once_with("ticket:user:enqueued:concert_b:456")
