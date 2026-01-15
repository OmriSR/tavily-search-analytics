"""Event models for document access tracking."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass
class DocumentAccessEvent:
    """Event emitted when a document URL is accessed during search."""

    url: str
    domain: str
    query_hash: str
    request_id: str
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        """Validate event data after initialization."""
        if not self.url:
            raise ValueError("URL cannot be empty")
        if not self.domain:
            raise ValueError("Domain cannot be empty")
        if not self.query_hash:
            raise ValueError("Query hash cannot be empty")
        if not self.request_id:
            raise ValueError("Request ID cannot be empty")
