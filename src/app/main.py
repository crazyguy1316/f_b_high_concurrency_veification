import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Union
from fastapi import FastAPI, Depends, HTTPException, Header, status
from pydantic import BaseModel
import aiomysql
import redis.asyncio as redis

from .interfaces import ITokenValidator, IQueuePublisher, IOrderRepository
from .services import SimpleTokenValidator, RedisQueuePublisher, MySQLOrderRepository

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for connection pools
redis_client: Union[redis.Redis, None] = None
db_pool: Union[aiomysql.Pool, None] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, db_pool
    # Initialize Redis connection pool
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_url = f"redis://{redis_host}:6379"
    logger.info(f"Connecting to Redis at: {redis_url}")
    redis_client = redis.from_url(redis_url)

    # Initialize MySQL connection pool
    mysql_host = os.getenv("DB_HOST", "localhost")
    mysql_port = int(os.getenv("DB_PORT", "3306"))
    mysql_user = os.getenv("DB_USER", "ticket_user")
    mysql_password = os.getenv("DB_PASSWORD", "ticket_password")
    mysql_db = os.getenv("DB_NAME", "ticketing_db")

    logger.info(f"Connecting to MySQL at: {mysql_host}:{mysql_port}, db={mysql_db}")
    db_pool = None
    for attempt in range(1, 6):
        try:
            db_pool = await aiomysql.create_pool(
                host=mysql_host,
                port=mysql_port,
                user=mysql_user,
                password=mysql_password,
                db=mysql_db,
                minsize=5,
                maxsize=20,
                autocommit=True
            )
            logger.info("Successfully created MySQL connection pool.")
            break
        except Exception as e:
            logger.warning(f"Attempt {attempt}/5: Failed to create MySQL pool: {e}. Retrying in 2 seconds...")
            await asyncio.sleep(2)
            
    if db_pool is None:
        logger.error("Failed to initialize MySQL pool after 5 attempts.")

    yield
    # Clean up pools
    if redis_client:
        await redis_client.close()
        logger.info("Redis client closed.")
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()
        logger.info("MySQL connection pool closed.")


app = FastAPI(
    title="High-Concurrency Ticketing Verification System",
    description="Sprint 1 - Core OOP flow and asynchronous queue verification",
    version="1.0.0",
    lifespan=lifespan
)

# Pydantic schemas for request and responses
class ReserveRequest(BaseModel):
    member_id: int
    token: str

class QueueResponse(BaseModel):
    status: str
    message: str
    poll_url: str

class ErrorResponse(BaseModel):
    error: str
    message: str

class PollingResponse(BaseModel):
    member_id: int
    event_id: str
    status: str
    message: str


# Dependency injection providers
def get_token_validator() -> ITokenValidator:
    return SimpleTokenValidator()

def get_queue_publisher() -> IQueuePublisher:
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis client not initialized"
        )
    return RedisQueuePublisher(redis_client)

def get_order_repository() -> IOrderRepository:
    if db_pool is None or redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database/Redis connection pools not initialized"
        )
    return MySQLOrderRepository(db_pool, redis_client)


# POST Endpoint: Order Reservation Request
@app.post(
    "/api/v1/tickets/{event_id}/reserve",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QueueResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}
    }
)
async def reserve_ticket(
    event_id: str,
    req_body: ReserveRequest,
    authorization: Union[str, None] = Header(default=None),
    token_validator: ITokenValidator = Depends(get_token_validator),
    queue_publisher: IQueuePublisher = Depends(get_queue_publisher)
):
    # Retrieve token from either request body or authorization header (Authorization: Bearer <token>)
    token = req_body.token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    # Validate identity token
    is_valid = await token_validator.validate_token(req_body.member_id, token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Invalid or expired session token."
            }
        )

    # Enqueue request payload
    payload = {
        "event_id": event_id,
        "member_id": req_body.member_id,
        "timestamp": int(req_body.member_id)  # dummy dynamic tag
    }
    success = await queue_publisher.enqueue_request(payload)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "QUEUE_FAILED",
                "message": "Failed to enqueue order request. Please try again."
            }
        )

    return QueueResponse(
        status="QUEUED",
        message="Request successfully enqueued. Please poll order status.",
        poll_url=f"/api/v1/orders/{event_id}/{req_body.member_id}"
    )


# GET Endpoint: Order Status Polling
@app.get(
    "/api/v1/orders/{event_id}/{member_id}",
    status_code=status.HTTP_200_OK,
    response_model=PollingResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}
    }
)
async def poll_order_status(
    event_id: str,
    member_id: int,
    order_repo: IOrderRepository = Depends(get_order_repository)
):
    order_status = await order_repo.get_order_status(member_id, event_id)

    if order_status == "NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOT_FOUND",
                "message": "No order record found for this member and event."
            }
        )

    message_mapping = {
        "PENDING": "Order request is queued and waiting to be processed.",
        "SUCCESS": "Ticket purchase successful. Order created.",
        "FAILED": "Ticket purchase failed. Sold out or duplicate request."
    }

    return PollingResponse(
        member_id=member_id,
        event_id=event_id,
        status=order_status,
        message=message_mapping.get(order_status, "Status description")
    )
