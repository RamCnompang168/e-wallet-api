# NovaPay Database Architecture & Schema Specification

## 1. Schema Overview

The database design provides a 3NF relational model enhanced with PostgreSQL check constraints, unique constraints, and composite indexes designed for sub-millisecond lookups under high transaction throughput.

```text
Table Count: 19 Domain Entities + 3 System Balancing Accounts
Primary Key Strategy: UUIDv4 (public interfaces) / BigAutoField (immutable ledger journal)
Foreign Key Deletion Policy: models.PROTECT on financial relationships (preventing accidental cascading deletions)
```

---

## 2. Table Specifications & Constraints

### `users_user`
* **Purpose**: Core banking identity entity.
* **Fields**: `id` (UUID), `email` (Unique), `phone_number` (Unique), `password`, `full_name`, `role` (CUSTOMER, MERCHANT, STAFF, ADMIN, SUPER_ADMIN), `status` (ACTIVE, INACTIVE, SUSPENDED, FROZEN, CLOSED), `kyc_tier` (0, 1, 2), `pin_hash`, `pin_retry_count`, `pin_locked_until`.
* **Indexes**: `(email, status)`, `(phone_number, status)`, `(role, status)`.

### `wallets_wallet`
* **Purpose**: User balance account snapshot.
* **Fields**: `id` (UUID), `user_id` (FK), `wallet_number` (Unique), `currency`, `available_balance`, `hold_balance`, `current_balance`, `status`, `is_primary`.
* **Database Check Constraints**:
  * `wallet_available_balance_non_negative`: `available_balance >= 0`
  * `wallet_hold_balance_non_negative`: `hold_balance >= 0`
  * `wallet_current_balance_non_negative`: `current_balance >= 0`

### `wallets_systemaccount`
* **Purpose**: Internal balancing accounts enforcing zero-sum financial invariants.
* **Fields**: `id` (UUID), `account_code` (Unique), `account_name`, `currency`, `balance`, `description`.

### `wallets_ledgerentry`
* **Purpose**: Authoritative, immutable double-entry journal.
* **Fields**: `id` (BigInt PK), `transaction_id` (FK), `wallet_id` (FK, Nullable), `system_account_id` (FK, Nullable), `entry_type` (DEBIT, CREDIT), `amount`, `balance_before`, `balance_after`, `description`, `created_at`.
* **Constraints & Invariants**:
  * `ledger_amount_strictly_positive`: `amount > 0`
  * `ledger_entry_target_required`: `wallet_id IS NOT NULL OR system_account_id IS NOT NULL`
  * Immutability: Application level blocks updates and deletions.

### `transactions_transaction`
* **Purpose**: High-level state machine record of an intended or completed financial operation.
* **Fields**: `id` (UUID), `transaction_code` (Unique), `transaction_type` (TRANSFER, TOPUP, WITHDRAWAL, MERCHANT_PAYMENT, REFUND, REVERSAL), `status` (PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED, REVERSED, REFUNDED, PARTIALLY_REFUNDED), `sender_wallet_id` (FK), `receiver_wallet_id` (FK), `amount`, `fee_amount`, `total_amount`, `currency`, `reference_number`, `parent_transaction_id` (FK).
* **Constraints**:
  * `transaction_amount_strictly_positive`: `amount > 0`
  * `transaction_fee_non_negative`: `fee_amount >= 0`
  * `transaction_total_amount_gte_amount`: `total_amount >= amount`

### `core_idempotencykey`
* **Purpose**: Deduplication of mutating financial requests.
* **Fields**: `id` (UUID), `user_id` (FK), `key` (Varchar), `request_path`, `request_params_hash`, `status` (PENDING, RESOLVED, FAILED), `response_code`, `response_body`, `expires_at`.
* **Constraints**: `UniqueConstraint(user_id, key)`.

### `merchants_merchant` & `merchants_refund`
* **Purpose**: Merchant profile and refund tracking.
* **Over-Refund Protection**: Enforced by asserting $\sum \text{Refunds} \le \text{Original Transaction Amount}$.

### `settlement_webhookevent` & `settlement_reconciliationbatch`
* **Purpose**: Inbound gateway events with replay protection and statement audit records.
* **Constraints**: `UniqueConstraint(provider, external_event_id)`.
