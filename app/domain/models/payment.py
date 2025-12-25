from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Payment:

    id: UUID
    user_id: int
    payment_id: Optional[str]
    amount_tokens: int
    rub_amount: Decimal
    currency: str
    status: str
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
