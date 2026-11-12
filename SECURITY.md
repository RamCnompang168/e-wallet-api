# NovaPay Security Architecture & Practices

## 1. Authentication & Token Lifecycle

* **Access Token**: Short-lived (default: 15 minutes).
* **Refresh Token**: Stored strictly as a SHA-256 hash inside `UserSession`. The raw token is returned only once to the client upon authentication.
* **Token Rotation**: Each refresh request rotates the refresh token, revoking the previous session record.
* **Compromise Detection**: If an already revoked or expired refresh token is presented, a high-priority `SUSPICIOUS_ACTIVITY` security event is logged, and existing sessions for that device are flagged.

---

## 2. Transaction Authorization & PIN Security

* High-value financial operations (Transfers, Withdrawals, Merchant Payments) require a 6-digit numeric PIN.
* **Storage**: Salted and hashed using Argon2id / PBKDF2 (`make_password`). Raw PIN is never logged or persisted.
* **Velocity Lockout**: 3 consecutive incorrect PIN entries trigger an automatic 30-minute lock (`pin_locked_until`).

---

## 3. Financial Mutex & Race Condition Prevention

* **Pessimistic Locking**: `Wallet.objects.select_for_update()` inside `transaction.atomic()`.
* **Canonical Sorting**: Multi-wallet row locks are acquired in sorted primary key order to prevent deadlocks under cross-traffic.
* **Database Check Constraints**: Balance safety invariants (`available_balance >= 0`, `hold_balance >= 0`) are hardcoded into the relational database engine. Even if application code fails, the database rejects negative balance updates.

---

## 4. Webhook Security & Idempotency

* **Cryptographic Signatures**: External webhooks are validated using HMAC-SHA256 signatures with constant-time equality comparisons (`hmac.compare_digest`).
* **Replay Attack Protection**: Every webhook provider event is uniquely indexed on `(provider, external_event_id)`. Duplicates are acknowledged without re-executing settlements.

---

## 5. Secret & Document Vaulting

* **Zero Hardcoded Secrets**: Secrets (`DJANGO_SECRET_KEY`, `JWT_SECRET_KEY`, `DATABASE_PASSWORD`, `WEBHOOK_SECRET`) are loaded strictly from environment variables.
* **Restricted KYC Vault**: Identity documents are stored in protected storage buckets and served exclusively through authenticated views with explicit role permissions, preventing direct public media URL access.
