"""Domain exceptions for `trade_order_engine`."""

from __future__ import annotations


class OrderEngineError(Exception):
    """Base exception for order lifecycle errors."""


class OrderNotFoundError(OrderEngineError):
    """Raised when an order targeted by `uniq_no` does not exist."""


class OrderConflictError(OrderEngineError):
    """Raised when an operation conflicts with the current order state."""


class OrderAlreadyCancelledError(OrderConflictError):
    """Raised when trying to modify or cancel an already-cancelled order."""


class DuplicateOrderError(OrderConflictError):
    """Raised when placing an order with a `uniq_no` that already exists."""


class OrderValidationError(OrderEngineError):
    """Raised when a merged order violates domain validation rules."""


class OrderForbiddenError(OrderEngineError):
    """Raised when an operation targets a disallowed `client_id`."""
