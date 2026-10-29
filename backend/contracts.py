"""Small, serializable contracts shared by harness modules."""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversationEvent:
    group_id: int
    user_id: int
    source_id: int
    content: str
    created: float
    direct: bool = False


@dataclass(frozen=True)
class Intent:
    kind: str = 'discussion'
    target: str = 'unknown'
    topic: str = ''
    confidence: float = 0
    assistant_helpful: bool = False
    quoted: bool = False


@dataclass(frozen=True)
class ParticipationDecision:
    action: str
    reason: str
    topic: str = ''

    def data(self):
        return asdict(self)


@dataclass(frozen=True)
class ActionGrant:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def data(self):
        return asdict(self)
