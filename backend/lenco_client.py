
import hashlib
import hmac
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

try:
    from .money import ngwee_to_zmw, zmw_to_ngwee
except ImportError:
    from money import ngwee_to_zmw, zmw_to_ngwee

logger = logging.getLogger("bomapos.lenco")

ACTIVE_ATTEMPT_STATUSES = ("initiating", "pending", "otp-required", "pay-offline")


class LencoError(RuntimeError):
    """Base error for Lenco client operations."""
    pass


class LencoRejectedError(LencoError):
    """Raised for HTTP 4xx client errors from Lenco (e.g. invalid payload, rejected prompt, duplicate)."""
    pass


class LencoUnavailableError(LencoError):
    """Raised for timeouts, network connection failures, or HTTP 5xx provider errors."""
    pass


def mask_phone(phone: str) -> str:
    """Mask phone number so full customer phone numbers are never logged."""
    cleaned = (phone or "").strip()
    if len(cleaned) <= 3:
        return "***"
    return f"***{cleaned[-3:]}"


def format_zambian_phone(phone: str, format_type: Optional[str] = None) -> str:
    """
    Format and validate Zambian phone number across all Lenco operations.
    Configurable via LENCO_PHONE_FORMAT=local|international (default: local).
      - local: 0977123456 (10 digits starting with 0)
      - international: 260977123456 (12 digits MSISDN)
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", (phone or "").strip())
    if cleaned.startswith("+260"):
        cleaned = cleaned[4:]
    elif cleaned.startswith("260"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("0"):
        cleaned = cleaned[1:]

    pattern = r"^(97|96|95|77|76|75)\d{7}$"
    if not re.match(pattern, cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Zambian phone number format. Expected 097/096/095/077/076/075 series or 260...",
        )

    mode = (
        format_type
        if format_type is not None
        else os.getenv("LENCO_PHONE_FORMAT", "local")
    ).strip().lower()

    if mode == "international":
        return f"260{cleaned}"
    return f"0{cleaned}"


# Alias for backwards compatibility
normalize_zambian_phone = format_zambian_phone


def _normalize_lenco_status(raw_status: str) -> str:
    """Keep Lenco's statuses distinct: initiating, pending, otp-required, pay-offline, successful, failed, expired, abandoned."""
    st = (raw_status or "").strip().lower()
    if st in ("successful", "success", "paid"):
        return "successful"
    if st in ("failed", "declined", "cancelled"):
        return "failed"
    if st == "initiating":
        return "initiating"
    if st == "abandoned":
        return "abandoned"
    if st == "expired":
        return "expired"
    if st == "otp-required":
        return "otp-required"
    if st == "pay-offline":
        return "pay-offline"
    return "pending"


def _parse_fee_ngwee(raw_fee: Any) -> Optional[int]:
    if raw_fee is None:
        return None
    fee_str = str(raw_fee).strip()
    if not fee_str:
        return None
    return zmw_to_ngwee(fee_str)


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
    status: str  # 'pending', 'otp-required', 'pay-offline', 'successful', 'failed', 'expired'
    amount_ngwee: int
    currency: str = "ZMW"
    message: str = ""
    lenco_reference: Optional[str] = None
    collection_id: Optional[str] = None
    fee_ngwee: Optional[int] = None
    fee_bearer: Optional[str] = None
    settlement_status: Optional[str] = None


def _build_collection_result_from_data(
    data: Dict[str, Any],
    *,
    fallback_reference: str,
    fallback_amount_str: str = "0",
    fallback_currency: str = "ZMW",
    message: str = "",
) -> LencoCollectionResult:
    returned_amount = data.get("amount", fallback_amount_str)
    returned_currency = str(data.get("currency", fallback_currency)).upper()
    returned_status = _normalize_lenco_status(data.get("status", "pending"))
    raw_bearer = data.get("bearer")
    raw_settlement_status = data.get("settlementStatus")
    if raw_settlement_status is None and isinstance(data.get("settlement"), dict):
        raw_settlement_status = data["settlement"].get("status")

    return LencoCollectionResult(
        reference=str(data.get("reference") or fallback_reference),
        status=returned_status,
        amount_ngwee=zmw_to_ngwee(str(returned_amount)),
        currency=returned_currency,
        message=message,
        lenco_reference=(
            str(data["lencoReference"])
            if data.get("lencoReference") is not None
            else None
        ),
        collection_id=str(data["id"]) if data.get("id") is not None else None,
        fee_ngwee=_parse_fee_ngwee(data.get("fee")),
        fee_bearer=str(raw_bearer).strip().lower() if raw_bearer else None,
        settlement_status=(
            str(raw_settlement_status).strip().lower()
            if raw_settlement_status
            else None
        ),
    )


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
    def submit_mobile_money_otp(
        self,
        *,
        reference: str,
        otp: str,
        collection_id: Optional[str] = None,
        lenco_reference: Optional[str] = None,
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
        formatted_phone = format_zambian_phone(phone)
        amount_zmw_str = f"{ngwee_to_zmw(amount_ngwee):.2f}"
        payload = {
            "amount": amount_zmw_str,
            "reference": reference,
            "phone": formatted_phone,
            "operator": operator.lower(),
            "country": "zm",
            "bearer": "merchant",
        }
        logger.info(
            "Initiating Lenco mobile money collection ref=%s operator=%s phone=%s amount_zmw=%s",
            reference,
            operator,
            mask_phone(formatted_phone),
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
                if 400 <= resp.status_code < 500:
                    err_msg = ""
                    try:
                        err_body = resp.json()
                        err_msg = str(
                            err_body.get("message")
                            or err_body.get("detail")
                            or err_body.get("error")
                            or ""
                        )
                    except Exception:
                        pass
                    if not err_msg:
                        err_msg = f"Payment request rejected by Lenco ({resp.status_code})"
                    err_msg = re.sub(
                        r"\b(\+?260\d{9}|0\d{9})\b",
                        lambda m: mask_phone(m.group(0)),
                        err_msg,
                    )
                    logger.warning(
                        "Lenco collect_mobile_money 4xx rejection for ref=%s (phone=%s): %s",
                        reference,
                        mask_phone(formatted_phone),
                        err_msg,
                    )
                    raise LencoRejectedError(err_msg)

                resp.raise_for_status()
                body = resp.json()
        except LencoRejectedError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            logger.error(
                "Lenco collect_mobile_money network/timeout error for ref=%s (phone=%s): %s",
                reference,
                mask_phone(formatted_phone),
                exc.__class__.__name__,
            )
            raise LencoUnavailableError(
                "Payment provider timed out or network connection failed"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 500
            logger.error(
                "Lenco collect_mobile_money 5xx error for ref=%s (phone=%s): status=%d",
                reference,
                mask_phone(formatted_phone),
                status_code,
            )
            raise LencoUnavailableError(
                f"Payment provider server error ({status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "Lenco collect_mobile_money HTTP error for ref=%s (phone=%s): %s",
                reference,
                mask_phone(formatted_phone),
                exc.__class__.__name__,
            )
            raise LencoUnavailableError(
                "Failed to initiate mobile money collection with Lenco"
            ) from exc

        data = body.get("data") or {}
        return _build_collection_result_from_data(
            data,
            fallback_reference=reference,
            fallback_amount_str=amount_zmw_str,
            fallback_currency=currency,
            message=str(body.get("message") or "Mobile money prompt initiated"),
        )

    def submit_mobile_money_otp(
        self,
        *,
        reference: str,
        otp: str,
        collection_id: Optional[str] = None,
        lenco_reference: Optional[str] = None,
    ) -> LencoCollectionResult:
        resolved_id = collection_id
        if not resolved_id:
            existing = self.get_collection_by_reference(reference)
            if existing and existing.collection_id:
                resolved_id = existing.collection_id
        if not resolved_id:
            resolved_id = lenco_reference or reference

        payload = {
            "id": resolved_id,
            "reference": reference,
            "otp": otp.strip(),
        }
        logger.info(
            "Submitting Lenco mobile money OTP for ref=%s id=%s",
            reference,
            resolved_id,
        )
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout
            ) as client:
                resp = client.post(
                    "/collections/mobile-money/submit-otp",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.error(
                "Lenco submit_mobile_money_otp HTTP error for ref=%s: %s",
                reference,
                exc.__class__.__name__,
            )
            raise RuntimeError(
                "Failed to submit mobile money OTP to Lenco"
            ) from exc

        data = body.get("data") or {}
        return _build_collection_result_from_data(
            data,
            fallback_reference=reference,
            message=str(body.get("message") or "OTP submitted"),
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

        return _build_collection_result_from_data(
            data,
            fallback_reference=reference,
            message=str(body.get("message") or ""),
        )


class MockLencoClient(LencoClient):
    """In-memory mock implementation of LencoClient selected when LENCO_MODE=mock."""

    def __init__(self) -> None:
        self._collections: Dict[str, LencoCollectionResult] = {}
        self._next_initial_status: Optional[str] = None
        self._otp_next_status: str = "pay-offline"
        self._next_error: Optional[Exception] = None
        self._reference_errors: Dict[str, Exception] = {}

    def reset(self) -> None:
        self._collections.clear()
        self._next_initial_status = None
        self._otp_next_status = "pay-offline"
        self._next_error = None
        self._reference_errors.clear()

    def set_next_error(self, error: Optional[Exception]) -> None:
        """Configure an exception (e.g. LencoRejectedError, LencoUnavailableError) to be raised by collect_mobile_money."""
        self._next_error = error

    def set_reference_error(self, reference: str, error: Exception) -> None:
        """Configure an exception to be raised when get_collection_by_reference is called for reference."""
        self._reference_errors[reference] = error

    def set_next_initial_status(self, status: Optional[str]) -> None:
        """Configure the status returned by the next collect_mobile_money call (e.g. 'otp-required', 'pay-offline', 'pending')."""
        self._next_initial_status = (
            _normalize_lenco_status(status) if status is not None else None
        )

    def set_otp_next_status(self, status: str) -> None:
        """Configure the status returned when a valid OTP is submitted (default 'pay-offline', or 'successful')."""
        self._otp_next_status = _normalize_lenco_status(status)

    def collect_mobile_money(
        self,
        *,
        reference: str,
        phone: str,
        operator: str,
        amount_ngwee: int,
        currency: str = "ZMW",
    ) -> LencoCollectionResult:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err

        formatted_phone = format_zambian_phone(phone)
        logger.info(
            "MockLencoClient.collect_mobile_money ref=%s operator=%s phone=%s amount_ngwee=%d",
            reference,
            operator,
            mask_phone(formatted_phone),
            amount_ngwee,
        )
        if self._next_initial_status is not None:
            initial_status = self._next_initial_status
            self._next_initial_status = None
        elif formatted_phone.strip().endswith("0000"):
            initial_status = "otp-required"
        else:
            initial_status = "pay-offline"

        default_fee_ngwee = max(25, (amount_ngwee * 2) // 100)
        msg = (
            "OTP sent to customer phone"
            if initial_status == "otp-required"
            else "USSD push prompt simulated to customer phone"
        )
        result = LencoCollectionResult(
            reference=reference,
            status=initial_status,
            amount_ngwee=amount_ngwee,
            currency=currency.upper(),
            message=msg,
            lenco_reference=f"LENCO-SIM-{reference[:8]}",
            collection_id=f"col-{reference}",
            fee_ngwee=default_fee_ngwee,
            fee_bearer="merchant",
            settlement_status="pending",
        )
        self._collections[reference] = result
        return replace(result)

    def submit_mobile_money_otp(
        self,
        *,
        reference: str,
        otp: str,
        collection_id: Optional[str] = None,
        lenco_reference: Optional[str] = None,
    ) -> LencoCollectionResult:
        existing = self._collections.get(reference)
        if existing is None:
            raise RuntimeError(f"Collection with reference '{reference}' not found")

        cleaned_otp = (otp or "").strip()
        if cleaned_otp == "000000" or not cleaned_otp:
            new_status = "failed"
            msg = "Invalid OTP provided"
            settlement_st = existing.settlement_status
        else:
            new_status = self._otp_next_status
            msg = (
                "Payment successful"
                if new_status == "successful"
                else "OTP verified; awaiting customer authorization on phone"
            )
            settlement_st = (
                "settled" if new_status == "successful" else existing.settlement_status
            )

        updated = replace(
            existing,
            status=new_status,
            message=msg,
            settlement_status=settlement_st,
        )
        self._collections[reference] = updated
        return replace(updated)

    def get_collection_by_reference(
        self, reference: str
    ) -> Optional[LencoCollectionResult]:
        if reference in self._reference_errors:
            err = self._reference_errors.pop(reference)
            raise err
        item = self._collections.get(reference)
        if item is None:
            return None
        return replace(item)

    def set_collection_state(
        self,
        reference: str,
        *,
        status: str,
        amount_ngwee: Optional[int] = None,
        currency: Optional[str] = None,
        fee_ngwee: Optional[int] = None,
        fee_bearer: Optional[str] = None,
        settlement_status: Optional[str] = None,
        lenco_reference: Optional[str] = None,
    ) -> LencoCollectionResult:
        existing = self._collections.get(reference)
        normalized_status = _normalize_lenco_status(status)
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
        resolved_fee = (
            fee_ngwee
            if fee_ngwee is not None
            else (
                existing.fee_ngwee
                if existing and existing.fee_ngwee is not None
                else max(25, (resolved_amount * 2) // 100)
            )
        )
        resolved_bearer = (
            fee_bearer
            if fee_bearer is not None
            else (existing.fee_bearer if existing and existing.fee_bearer else "merchant")
        )
        resolved_settlement = (
            settlement_status
            if settlement_status is not None
            else (
                "settled"
                if normalized_status == "successful"
                else (existing.settlement_status if existing else "pending")
            )
        )
        resolved_lenco_ref = (
            lenco_reference
            if lenco_reference is not None
            else (
                existing.lenco_reference
                if existing and existing.lenco_reference
                else f"LENCO-SIM-{reference[:8]}"
            )
        )
        updated = LencoCollectionResult(
            reference=reference,
            status=normalized_status,
            amount_ngwee=resolved_amount,
            currency=resolved_currency,
            message=existing.message if existing else "Simulated state update",
            lenco_reference=resolved_lenco_ref,
            collection_id=(
                existing.collection_id if existing else f"col-{reference}"
            ),
            fee_ngwee=resolved_fee,
            fee_bearer=resolved_bearer,
            settlement_status=resolved_settlement,
        )
        self._collections[reference] = updated
        return replace(updated)


mock_lenco_client = MockLencoClient()
live_lenco_client = LiveLencoClient()


def get_lenco_client() -> LencoClient:
    mode = os.getenv("LENCO_MODE", "mock").strip().lower()
    if mode == "live":
        return live_lenco_client
    if mode == "mock":
        return mock_lenco_client
    raise RuntimeError(f"Unsupported LENCO_MODE '{mode}'. Expected 'mock' or 'live'.")
