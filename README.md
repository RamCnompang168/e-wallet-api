# NovaPay — Enterprise Banking & Digital Wallet REST API

A mission-critical, double-entry banking and digital wallet backend engineered with **Django 5.2+**, **Django REST Framework**, **PostgreSQL**, **Redis**, and **Celery**.

Designed specifically for fintech simulations, neobank portfolios, and digital wallet architectures where **financial correctness, deadlock-free concurrency, zero double-spending, and auditability** are paramount.

---

## Key Highlights & Architectural Features

* **Double-Entry Ledger Engine**: Authoritative, append-only journal (`LedgerEntry`). Every monetary operation enforces the absolute invariant:
  $$\sum \text{Debits} = \sum \text{Credits}$$
* **System Balancing Accounts**: Non-user accounts (`SYSTEM_FEE_REVENUE`, `SYSTEM_SETTLEMENT_ESCROW`, `SYSTEM_EXTERNAL_CLEARING`) balance single-sided operations (fees, top-ups, payouts).
* **Deadlock-Free Canonical Locking**: Multi-wallet mutations acquire row-level locks strictly ordered by primary key (`order_by('id')` with `select_for_update()`), preventing cyclic AB-BA deadlocks under high concurrency.
* **Idempotency Execution Guard**: Financial mutating endpoints (`/transfers/`, `/topups/`, `/withdrawals/`, `/merchant-payments/`, `/refunds/`) require an `Idempotency-Key` header with atomic lock-and-cache handling.
* **Tiered KYC Verification**: Document vault, image uploads, and compliance review workflows (Tier 0 Unverified to Tier 2 Enhanced) unlocking higher transaction limits.
* **Merchant Ecosystem & MDR Fees**: Merchant codes, QR checkout, Merchant Discount Rate (MDR) fee deductions, full and partial refunds with over-refund protection, and customer dispute resolution.
* **Replay-Proof Webhooks & Reconciliation**: HMAC-SHA256 signature verification and automated statement reconciliation engine.
* **Production Security**: SimpleJWT rotation, session revocation, SHA-256 token hashing, Argon2id PIN verification with 3-attempt lockouts, and security event audit trails.

---

## Technology Stack

* **Language**: Python 3.13+
* **Framework**: Django 5.2+ / Django REST Framework 3.16+
* **Database**: PostgreSQL 16+ (with row-level locking and check constraints)
* **Caching & Broker**: Redis 7+
* **Task Queue**: Celery 5.4+ / Celery Beat
* **Documentation**: OpenAPI 3.0 / drf-spectacular / Swagger UI / Redoc
* **Containerization**: Docker / Docker Compose

---

## Project Structure

```text
API/
├── API/                       # Project configuration & settings
│   ├── settings.py            # Hardened Django settings
│   ├── urls.py                # Root routing & versioned /api/v1/ mount
│   ├── celery.py              # Celery application instance
│   └── wsgi.py / asgi.py
├── apps/
│   ├── core/                  # Base models, idempotency interceptor, custom exceptions, pagination
│   ├── users/                 # Custom User, Devices, Sessions, Security Events, Audit Logs
│   ├── authentication/        # JWT issuance, refresh rotation, OTP service
│   ├── wallets/               # Wallet balances, System Accounts, Double-Entry Ledger Engine
│   ├── transactions/          # Transaction state machine, Limits, Fee rules
│   ├── transfers/             # P2P Transfers with canonical locking
│   ├── beneficiaries/         # Saved transfer recipients
│   ├── payments/              # Payment methods, Top-ups, Withdrawals
│   ├── merchants/             # Merchant registration, QR payments, Refunds, Disputes, Reversals
│   ├── kyc/                   # Tiered identity verification & compliance review
│   ├── notifications/         # Asynchronous alerts & Celery tasks
│   └── settlement/            # HMAC webhooks & automated reconciliation engine
├── tests/                     # Comprehensive test suite (Auth, Ledger, Concurrency, Refunds)
├── Dockerfile                 # Multi-stage production container
├── docker-compose.yml         # Postgres, Redis, Web, Celery Worker, Celery Beat
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## Getting Started

### 1. Local Development Setup

```bash
# 1. Clone repository and navigate to API directory
cd c:\Users\ASUS\Documents\e-wallet\API

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env

# 4. Run database migrations
python manage.py migrate

# 5. Seed initial data (System accounts, fee rules, limits, demo users)
python manage.py seed_data

# 6. Start development server
python manage.py runserver 8000
```

### 2. Running with Docker Compose

```bash
# Launch all 5 containers (PostgreSQL, Redis, Django, Celery Worker, Celery Beat)
docker-compose up --build -d

# Inspect running logs
docker-compose logs -f web
```

---

<!-- ## Seeded Demo Accounts

The `seed_data` command populates the following accounts for immediate testing:

| Role | Email | Password | PIN | Initial Balance |
|---|---|---|---|---|
| **Super Admin** | `admin@novapay.bank` | `AdminSecurePass123!` | `123456` | Unlimited |
| **Compliance Officer** | `compliance@novapay.bank` | `StaffSecurePass123!` | `123456` | Staff Privileges |
| **Merchant** | `coffee@shop.com` | `MerchantPass123!` | `123456` | $0 (MDR 1.5%) |
| **Customer (Alice)** | `alice@example.com` | `AlicePass123!` | `123456` | $1,000.00 |
| **Customer (Bob)** | `bob@example.com` | `BobPass123!` | `123456` | $250.00 |

--- -->

## Automated Test Suite

Run the full automated test suite covering unit tests, financial invariants, and multi-threaded race conditions:

```bash
pytest -v
```

### Verified Test Matrix
* **Authentication**: Registration, Login, Incorrect Password, OTP attempt limit lockout, Token rotation & revocation.
* **Transfers**: P2P settlement, Available balance validation, Self-transfer rejection, Idempotency duplicate protection.
* **Double-Entry Invariant**: Total Debits == Total Credits assert across every movement.
* **Concurrency**: Multi-threaded double-spend attack ($100 balance with simultaneous $80 requests).
* **Deadlock Prevention**: Canonical ID sorting verified across bidirectional transfers.
* **Merchant & Refunds**: QR payment with MDR fee, full and partial refunds with fee reversal, over-refund rejection, dispute escalation.
* **Top-Up & Withdrawal**: Payment rail routing, KYC Tier 1 withdrawal requirement enforcement.

---

## Interactive API Documentation

Once the server is running, explore the interactive OpenAPI 3.0 documentation:

* **Swagger UI**: [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
* **Redoc**: [http://localhost:8000/api/redoc/](http://localhost:8000/api/redoc/)
* **OpenAPI Raw Schema**: [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/)
