# NovaPay Architecture Specification

## 1. Clean / Hexagonal Domain Architecture

The application enforces strict separation of concerns across 5 distinct architectural layers:

```text
[HTTP Requests / Clients]
          ↓
[Transport Layer: DRF Views, Throttles, Idempotency Interceptor]
          ↓
[Validation Layer: DRF Serializers, Type Parsing]
          ↓
[Domain Service Layer: TransferService, LedgerService, KYCService, etc.]
          ↓
[Persistence Layer: Django ORM, Row Locks, Check Constraints, PostgreSQL]
          ↓
[Post-Commit Event Layer: transaction.on_commit() -> Celery Tasks / Redis]
```

### Invariant Rules
1. **Views do not execute business logic**: Views are thin HTTP controllers that extract parameters, validate permissions, and invoke services.
2. **Serializers do not mutate financial balances**: Serializers only validate data contracts and structure output envelopes.
3. **Services orchestrate transactions**: All database row locks, balance modifications, and ledger entries occur inside atomic service methods.
4. **Side effects are deferred**: External API calls, emails, and notifications are triggered strictly inside `transaction.on_commit()` hooks.

---

## 2. Double-Entry Accounting Model

Monetary movements are represented as an immutable journal of balanced legs. User wallets maintain cached balance columns for high-performance reading (`current_balance`, `available_balance`, `hold_balance`), but the **LedgerEntry** table is the authoritative financial truth.

### System Balancing Accounts
Single-sided user operations balance against internal platform accounts:

| System Account Code | Purpose |
|---|---|
| `SYSTEM_FEE_REVENUE` | Collects transaction fees and merchant discount rates (MDR). |
| `SYSTEM_SETTLEMENT_ESCROW` | Holds funds during multi-phase settlements and pending payouts. |
| `SYSTEM_EXTERNAL_CLEARING` | Represents external cash-in and cash-out gateway positions. |

### Mathematical Invariant
$$\sum \text{Debits} - \sum \text{Credits} = 0$$

```text
Peer-to-Peer Transfer Example:
Alice sends $100 to Bob (with $1 platform fee):
  1. DEBIT  Alice's Wallet:        $101.00
  2. CREDIT Bob's Wallet:          $100.00
  3. CREDIT SYSTEM_FEE_REVENUE:      $1.00
  Sum(Debits) = $101.00 == Sum(Credits) = $101.00

Merchant Payment Example:
Customer pays $100 to Merchant (with 1.5% MDR fee):
  1. DEBIT  Customer Wallet:       $100.00
  2. CREDIT Merchant Wallet:        $98.50
  3. CREDIT SYSTEM_FEE_REVENUE:      $1.50
  Sum(Debits) = $100.00 == Sum(Credits) = $100.00
```

---

## 3. Concurrency Control & Canonical Locking

To guarantee that simultaneous transactions cannot trigger database deadlocks, multi-wallet row locks are acquired in canonical ascending primary key order:

```python
# In LedgerService.lock_wallets_canonical:
clean_ids = [str(w.id) for w in [wallet_a, wallet_b]]
unique_sorted_ids = sorted(list(set(clean_ids)))

# Rows are locked in deterministic order (min_id, then max_id)
wallets = list(Wallet.objects.select_for_update().filter(id__in=unique_sorted_ids))
```

Regardless of whether Transaction 1 is transferring from Wallet A to Wallet B while Transaction 2 is transferring from Wallet B to Wallet A, both processes will request locks in the same sequence:
$$\text{Lock}( \min(A, B) ) \longrightarrow \text{Lock}( \max(A, B) )$$
This completely eliminates cyclic lock-wait graphs.

---

## 4. Idempotency Execution Flow

```text
Incoming Request with Idempotency-Key Header
                     ↓
        Select or Insert (user_id, key)
                     ↓
           Status == RESOLVED?
              ├── YES ──> Return Cached Response Payload (200/201)
              └── NO  ──> Status == PENDING?
                            ├── YES ──> Raise 409 Conflict (Currently Processing)
                            └── NO  ──> Execute Financial Mutation inside transaction.atomic()
                                          ↓
                                  Save Response Body & Code
                                          ↓
                                  Set Status = RESOLVED
```
