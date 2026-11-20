"""Form prefill builders (Track K): read the Bank, never write it."""

from src.jd_bank.forms.comp_requisition import (
    REQUEST_TYPE_LABELS,
    RequestType,
    prefill_from_role,
)

__all__ = ["REQUEST_TYPE_LABELS", "RequestType", "prefill_from_role"]
