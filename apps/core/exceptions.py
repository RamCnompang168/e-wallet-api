"""Domain and banking exception definitions."""
from rest_framework import status


class BankingException(Exception):
    """Base exception for all banking and wallet business logic failures."""
    default_message = "A banking business rule violation occurred."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "banking_error"

    def __init__(self, message=None, status_code=None, code=None, errors=None):
        self.message = message or self.default_message
        self.status_code = status_code or self.default_status_code
        self.code = code or self.default_code
        self.errors = errors or {}
        super().__init__(self.message)


class InsufficientBalanceException(BankingException):
    default_message = "Insufficient available wallet balance to complete this transaction."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "insufficient_balance"


class LimitExceededException(BankingException):
    default_message = "Transaction amount exceeds permitted velocity or threshold limit."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "limit_exceeded"


class WalletInactiveException(BankingException):
    default_message = "Wallet is not active or has been frozen/closed."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "wallet_inactive"


class SelfTransferException(BankingException):
    default_message = "Sender and receiver wallet cannot be identical."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "self_transfer_prohibited"


class CurrencyMismatchException(BankingException):
    default_message = "Transaction currency does not match wallet denomination."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "currency_mismatch"


class InvalidTransactionStateException(BankingException):
    default_message = "The transaction cannot transition to the requested state."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_transaction_state"


class IdempotencyConflictException(BankingException):
    default_message = "A request with this idempotency key is already currently processing."
    default_status_code = status.HTTP_409_CONFLICT
    default_code = "idempotency_conflict"


class InvalidPINException(BankingException):
    default_message = "The provided transaction PIN is incorrect."
    default_status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_pin"


class PINLockedException(BankingException):
    default_message = "Transaction PIN has been locked due to too many failed attempts."
    default_status_code = status.HTTP_423_LOCKED
    default_code = "pin_locked"


class KYCRequiredException(BankingException):
    default_message = "This operation requires a higher KYC verification level."
    default_status_code = status.HTTP_403_FORBIDDEN
    default_code = "kyc_tier_insufficient"


class LedgerImbalanceException(BankingException):
    default_message = "Ledger invariant violated: Total debits must equal total credits."
    default_status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_code = "ledger_imbalance"


class ExternalProviderException(BankingException):
    default_message = "External payment provider rejected or failed to process the request."
    default_status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "provider_error"
