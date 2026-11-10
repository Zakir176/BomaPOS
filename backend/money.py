from decimal import Decimal, ROUND_HALF_UP
from typing import Union

NGWEE_PER_ZMW = Decimal("100")


def zmw_to_ngwee(amount_zmw: Union[Decimal, int, str, float]) -> int:
    """Convert a ZMW amount to integer ngwee (1 ZMW = 100 ngwee)."""
    d = Decimal(str(amount_zmw))
    return int((d * NGWEE_PER_ZMW).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ngwee_to_zmw(amount_ngwee: int) -> float:
    """Convert integer ngwee to decimal ZMW for public JSON serialization."""
    d = (Decimal(int(amount_ngwee)) / NGWEE_PER_ZMW).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(d)

