"""Recurring singleton queue message configuration."""

from collections.abc import Iterable

from .maintenance import FAIL_ZOMBIE_JOBS_MESSAGE_TYPE
from .types import RecurringMessage

FAIL_ZOMBIE_JOBS_RECURRING_MESSAGE = RecurringMessage(
    msg_type=FAIL_ZOMBIE_JOBS_MESSAGE_TYPE,
    interval_seconds=300,
    jitter_seconds=10,
    payload={},
    created_by="system",
)

DEFAULT_RECURRING_MESSAGES = (FAIL_ZOMBIE_JOBS_RECURRING_MESSAGE,)

_configured_recurring_messages: tuple[RecurringMessage, ...] = (
    DEFAULT_RECURRING_MESSAGES
)


def configure_recurring_messages(
    messages: Iterable[RecurringMessage] = (),
) -> None:
    """Configure framework and app recurring MQ messages."""
    global _configured_recurring_messages
    _configured_recurring_messages = _dedupe_recurring_messages(
        (*DEFAULT_RECURRING_MESSAGES, *tuple(messages))
    )


def get_recurring_messages() -> tuple[RecurringMessage, ...]:
    """Return the configured recurring MQ messages."""
    return _configured_recurring_messages


def recurring_message_map(
    messages: Iterable[RecurringMessage],
) -> dict[str, RecurringMessage]:
    """Return recurring message config keyed by msg_type."""
    return {message.msg_type: message for message in messages}


def _dedupe_recurring_messages(
    messages: Iterable[RecurringMessage],
) -> tuple[RecurringMessage, ...]:
    deduped: dict[str, RecurringMessage] = {}
    for message in messages:
        deduped[message.msg_type] = message
    return tuple(deduped.values())
