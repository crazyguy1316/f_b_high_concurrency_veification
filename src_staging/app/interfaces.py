from abc import ABC, abstractmethod
from typing import Dict, Union

# Define the payload type for queue messages to ensure type safety.
QueuePayload = Dict[str, Union[str, int]]

class ITokenValidator(ABC):
    """Abstract Base Class for user token validation."""

    @abstractmethod
    async def validate_token(self, member_id: int, token: str) -> bool:
        """
        Verify if the given token is valid for the specified member_id.

        Args:
            member_id (int): The unique ID of the member.
            token (str): The token string to validate.

        Returns:
            bool: True if validation is successful, False otherwise.
        """
        pass


class IQueuePublisher(ABC):
    """Abstract Base Class for pushing ticket reserving tasks to the message queue."""

    @abstractmethod
    async def enqueue_request(self, payload: QueuePayload) -> bool:
        """
        Push the reserving request payload to the queue.

        Args:
            payload (QueuePayload): The message payload containing member_id and event_id.

        Returns:
            bool: True if enqueued successfully, False otherwise.
        """
        pass


class IOrderRepository(ABC):
    """Abstract Base Class for managing order data persistence in MySQL."""

    @abstractmethod
    async def create_order(self, member_id: int, event_id: str, status: str) -> bool:
        """
        Persist a new ticket purchase order inside the database.

        Args:
            member_id (int): The unique member ID.
            event_id (str): The unique event ID.
            status (str): The booking status (e.g. 'SUCCESS', 'FAILED').

        Returns:
            bool: True if insertion succeeded, False otherwise.
        """
        pass

    @abstractmethod
    async def get_order_status(self, member_id: int, event_id: str) -> str:
        """
        Query the order database status for a specific user and event.

        Args:
            member_id (int): The unique member ID.
            event_id (str): The unique event ID.

        Returns:
            str: The order status ('PENDING', 'SUCCESS', 'FAILED', or 'NOT_FOUND').
        """
        pass


class ICacheService(ABC):
    """Abstract Base Class for executing Redis operations and atomic Lua pre-deductions."""

    @abstractmethod
    async def evaluate_lua_reserve(self, member_id: int, event_id: str) -> str:
        """
        Execute the pre-loaded Lua script on Redis to atomically check/deduct stock.

        Args:
            member_id (int): The member ID requesting a ticket.
            event_id (str): The event ID for the ticketing.

        Returns:
            str: Result status code from Lua ('SUCCESS', 'SOLD_OUT', 'DUPLICATE_ORDER').
        """
        pass
