import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

try:
    from .money import ngwee_to_zmw, zmw_to_ngwee
except ImportError:
    from money import ngwee_to_zmw, zmw_to_ngwee

logger = logging.getLogger("bomapos.lenco")


def mask_phone(phone: str) -> str:
    """Mask phone number so full customer phone numbers are never logged."""
    cleaned = (phone or "").strip()
    if len(cleaned) <= 3:
        return "***"
    return f"***{cleaned[-3:]}"


def _normalize_lenco_status(raw_status: str) -> str:
    st = (raw_status or "").strip().lower()
    if st in ("successful", "success", "paid"):
        return "successful"
    if st in ("failed", "declined", "cancelled", "expired"):
        return "failed"
    return "pending"


def get_lenco_api_token() -> str:
    return os.getenv("LENCO_API_TOKEN", "").strip()


def compute_lenco_webhook_signature(
    raw_body: bytes, api_token: Optional[str] = None
) -> str:
    """
    Compute Lenco webhook HMAC-SHA512 signature:
      webhook_key = sha256(LENCO_API_TOKEN).hexdigest()
      signature   = hmac_sha512(webhook_key, raw_body).hexdigest()
    """
    token = (api_token if api_token is not None else get_lenco_api_token()).strip()
    if not token:
        raise RuntimeError("LENCO_API_TOKEN is not configured")
    webhook_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.new(
        webhook_key.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()


def verify_lenco_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    api_token: Optional[str] = None,
) -> bool:
    """Verify X-Lenco-Signature header against raw request body using hmac.compare_digest."""
    if not signature_header or not isinstance(signature_header, str):
        return False
    token = (api_token if api_token is not None else get_lenco_api_token()).strip()
    if not token:
        return False
    expected = compute_lenco_webhook_signature(raw_body, api_token=token)
    provided = signature_header.strip().lower()
    return hmac.compare_digest(expected.lower(), provided)


@dataclass
class LencoCollectionResult:
    reference: str
    status: str  # 'pending', 'successful', 'failed'
    amount_ngwee: int
    currency: str = "ZMW"
    message: str = ""
    lenco_reference: Optional[str] = None


class LencoClient(ABC):
    @abstractmethod
    def collect_mobile_money(
        self,
        *,
        reference: str,
        phone: str,
        operator: str,
        amount_ngwee: int,
        currency: str = "ZMW",
    ) -> LencoCollectionResult:
        raise NotImplementedError

    @abstractmethod
    def get_collection_by_reference(
        self, reference: str
    ) -> Optional[LencoCollectionResult]:
        raise NotImplementedError


class LiveLencoClient(LencoClient):
    """Thin httpx wrapper around Lenco v2 Mobile Money Collections API."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self._api_token = api_token
        self._base_url = (
            base_url
            or os.getenv("LENCO_API_BASE_URL", "https://api.lenco.co/access/v2")
        ).rstrip("/")
        self._timeout = timeout

    def _resolve_token(self) -> str:
        token = (
            self._api_token if self._api_token is not None else get_lenco_api_token()
        ).strip()
        if not token:
            raise RuntimeError(
                "LENCO_API_TOKEN environment variable is required when LENCO_MODE=live"
            )
        return token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._resolve_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def collect_mobile_money(
        self,
        *,
        reference: str,
        phone: str,
        operator: str,
        amount_ngwee: int,
        currency: str = "ZMW",
    ) -> LencoCollectionResult:
        amount_zmw_str = f"{ngwee_to_zmw(amount_ngwee):.2f}"
        payload = {
            "amount": amount_zmw_str,
            "reference": reference,
            "phone": phone,
            "operator": operator.lower(),
            "country": "zm",
            "bearer": "merchant",
        }
        logger.info(
            "Initiating Lenco mobile money collection ref=%s operator=%s phone=%s amount_zmw=%s",
            reference,
            operator,
            mask_phone(phone),
            amount_zmw_str,
        )
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout
            ) as client:
                resp = client.post(
                    "/collections/mobile-money",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.error(
                "Lenco collect_mobile_money HTTP error for ref=%s (phone=%s): %s",
                reference,
                mask_phone(phone),
                exc.__class__.__name__,
            )
            raise RuntimeError("Failed to initiate mobile money collection with Lenco") from exc

        data = body.get("data") or {}
        returned_amount = data.get("amount", amount_zmw_str)
        returned_currency = str(data.get("currency", currency)).upper()
        returned_status = _normalize_lenco_status(data.get("status", "pending"))

        return LencoCollectionResult(
            reference=str(data.get("reference") or reference),
            status=returned_status,
            amount_ngwee=zmw_to_ngwee(str(returned_amount)),
            currency=returned_currency,
            message=str(body.get("message") or "Mobile money prompt initiated"),
            lenco_reference=data.get("lencoReference"),
        )

    def get_collection_by_reference(
        self, reference: str
    ) -> Optional[LencoCollectionResult]:
        logger.info("Fetching Lenco collection status for ref=%s", reference)
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout
            ) as client:
                resp = client.get(
                    f"/collections/status/{reference}",
                    headers=self._headers(),
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.error(
                "Lenco get_collection_by_reference HTTP error for ref=%s: %s",
                reference,
                exc.__class__.__name__,
            )
            raise RuntimeError("Failed to fetch collection status from Lenco") from exc

        data = body.get("data")
        if not data:
            return None

        return LencoCollectionResult(
            reference=str(data.get("reference") or reference),
            status=_normalize_lenco_status(data.get("status", "pending")),
            amount_ngwee=zmw_to_ngwee(str(data.get("amount", "0"))),
            currency=str(data.get("currency", "ZMW")).upper(),
            message=str(body.get("message") or ""),
            lenco_reference=data.get("lencoReference"),
        )


class MockLencoClient(LencoClient):
    """In-memory mock implementation of LencoClient selected when LENCO_MODE=mock."""

    def __init__(self) -> None:
        self._collections: Dict[str, LencoCollectionResult] = {}

    def reset(self) -> None:
        self._collections.clear()

    def collect_mobile_money(
        self,
        *,
        reference: str,
        phone: str,
        operator: str,
        amount_ngwee: int,
        currency: str = "ZMW",
    ) -> LencoCollectionResult:
        logger.info(
            "MockLencoClient.collect_mobile_money ref=%s operator=%s phone=%s amount_ngwee=%d",
            reference,
            operator,
            mask_phone(phone),
            amount_ngwee,
        )
        result = LencoCollectionResult(
            reference=reference,
            status="pending",
            amount_ngwee=amount_ngwee,
            currency=currency.upper(),
            message="USSD push prompt simulated to customer phone",
            lenco_reference=f"LENCO-SIM-{reference[:8]}",
        )
        self._collections[reference] = result
        return result

    def get_collection_by_reference(
        self, reference: str
    ) -> Optional[LencoCollectionResult]:
        item = self._collections.get(reference)
        if item is None:
            return None
        return LencoCollectionResult(
            reference=item.reference,
            status=item.status,
            amount_ngwee=item.amount_ngwee,
            currency=item.currency,
            message=item.message,
            lenco_reference=item.lenco_reference,
        )

    def set_collection_state(
        self,
        reference: str,
        *,
        status: str,
        amount_ngwee: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> LencoCollectionResult:
        existing = self._collections.get(reference)
        resolved_amount = (
            amount_ngwee
            if amount_ngwee is not None
            else (existing.amount_ngwee if existing else 0)
        )
        resolved_currency = (
            currency.upper()
            if currency is not None
            else (existing.currency if existing else "ZMW")
        )
        updated = LencoCollectionResult(
            reference=reference,
            status=_normalize_lenco_status(status),
            amount_ngwee=resolved_amount,
            currency=resolved_currency,
            message=existing.message if existing else "Simulated state update",
            lenco_reference=existing.lenco_reference if existing else f"LENCO-SIM-{reference[:8]}",
        )
        self._collections[reference] = updated
        return updated


mock_lenco_client = MockLencoClient()
live_lenco_client = LiveLencoClient()


def get_lenco_client() -> LencoClient:
    mode = os.getenv("LENCO_MODE", "mock").strip().lower()
    if mode == "live":
        return live_lenco_client
    if mode == "mock":
        return mock_lenco_client
    raise RuntimeError(f"Unsupported LENCO_MODE '{mode}'. Expected 'mock' or 'live'.")

