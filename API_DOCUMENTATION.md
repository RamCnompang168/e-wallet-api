# NovaPay API Documentation (`/api/v1/`)

All requests and responses use JSON and conform to the standardized response envelope:

### Success Response Envelope
```json
{
  "success": true,
  "message": "Operation completed successfully.",
  "data": {}
}
```

### Error Response Envelope
```json
{
  "success": false,
  "message": "Validation or business logic error.",
  "errors": {
    "field_name": ["Specific error description."]
  }
}
```

---

## 1. Authentication & Session Management (`/api/v1/auth/`)

### Register Account
* **Endpoint**: `POST /api/v1/auth/register/`
* **Access**: Public
* **Request Body**:
```json
{
  "email": "user@example.com",
  "phone_number": "+1234567890",
  "full_name": "Jane Doe",
  "password": "Password123!",
  "pin": "123456",
  "role": "CUSTOMER",
  "gender": "FEMALE",
  "date_of_birth": "1995-05-15"
}
```
* **Response (201 Created)**: Returns user profile and JWT token pair (`access_token`, `refresh_token`, `session_id`).

### Login
* **Endpoint**: `POST /api/v1/auth/login/`
* **Access**: Public
* **Request Body**:
```json
{
  "username": "user@example.com",
  "password": "Password123!",
  "device_identifier": "unique-device-uuid",
  "device_name": "Chrome on Windows",
  "device_type": "WEB"
}
```

### Rotate Refresh Token
* **Endpoint**: `POST /api/v1/auth/refresh/`
* **Access**: Public
* **Request Body**: `{"refresh_token": "<token>"}`

### Request / Verify OTP
* **Request OTP**: `POST /api/v1/auth/send-otp/`
  * Body: `{"purpose": "LOGIN", "phone_number": "+1234567890"}`
* **Verify OTP**: `POST /api/v1/auth/verify-otp/`
  * Body: `{"purpose": "LOGIN", "phone_number": "+1234567890", "code": "123456"}`

---

## 2. Wallets & Balances (`/api/v1/wallet/`)

### Get Primary Wallet Summary
* **Endpoint**: `GET /api/v1/wallet/`
* **Headers**: `Authorization: Bearer <token>`
* **Response**:
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "wallet_number": "WAL-12345678",
    "currency": "USD",
    "current_balance": "1000.0000",
    "available_balance": "1000.0000",
    "hold_balance": "0.0000",
    "status": "ACTIVE"
  }
}
```

### Get Authoritative Ledger History
* **Endpoint**: `GET /api/v1/wallet/ledger/?page=1&page_size=20&start_date=2026-01-01`
* **Response**: Paginated list of immutable debits and credits with balance before/after.

---

## 3. P2P Money Transfers (`/api/v1/transfers/`)

### Execute Transfer
* **Endpoint**: `POST /api/v1/transfers/`
* **Headers**:
  * `Authorization: Bearer <token>`
  * `Idempotency-Key: <unique-uuid>`
* **Request Body**:
```json
{
  "receiver_wallet_number": "WAL-87654321",
  "amount": "150.0000",
  "description": "Invoice settlement",
  "reference_number": "INV-2026-001",
  "pin": "123456"
}
```
* **Response (201 Created)**: Returns settled transaction code, fees, and timestamps.

---

## 4. Top-ups & Withdrawals (`/api/v1/topups/`, `/api/v1/withdrawals/`)

### Inbound Top-Up
* **Endpoint**: `POST /api/v1/topups/`
* **Headers**: `Idempotency-Key: <uuid>`
* **Request Body**:
```json
{
  "payment_method_id": "<uuid>",
  "amount": "200.0000",
  "provider_reference": "EXT-GATEWAY-REF-991"
}
```

### Outbound Withdrawal
* **Endpoint**: `POST /api/v1/withdrawals/`
* **Headers**: `Idempotency-Key: <uuid>`
* **Prerequisite**: User must hold KYC Tier 1 or higher.
* **Request Body**:
```json
{
  "payment_method_id": "<uuid>",
  "destination_account": "US89370001928374",
  "amount": "100.0000",
  "pin": "123456"
}
```

---

## 5. Merchant Ecosystem (`/api/v1/`)

* `GET /api/v1/merchants/?search=coffee` — Search verified merchants.
* `POST /api/v1/merchants/` — Register merchant business profile.
* `POST /api/v1/merchant-payments/` — Pay merchant via QR or code (*Requires Idempotency-Key & PIN*).
* `POST /api/v1/refunds/` — Merchant issues full or partial refund with proportional MDR fee reversal.
* `POST /api/v1/disputes/` — Customer files dispute for a completed transaction.

---

## 6. Tiered KYC Identity Compliance (`/api/v1/kyc/`)

* `POST /api/v1/kyc/` — Submit identity documents (multipart/form-data: `target_tier`, `document_type`, `document_number`, `front_image`, `back_image`, `selfie_image`).
* `GET /api/v1/kyc/status/` — Retrieve current verification tier and review status.

---

## 7. Administrative APIs (`/api/v1/admin/`)

* `GET /api/v1/admin/users/` — Query and filter users by role and status.
* `PATCH /api/v1/admin/users/{id}/status/` — Freeze or suspend user account.
* `GET /api/v1/admin/transactions/` — Global transaction audit with filtering.
* `POST /api/v1/admin/transactions/{id}/reverse/` — Administrative full reversal.
* `GET /api/v1/admin/kyc/` & `PATCH /api/v1/admin/kyc/{id}/review/` — KYC compliance queue.
* `PATCH /api/v1/admin/disputes/{id}/resolve/` — Resolve disputes (`ACCEPTED` triggers refund).
* `GET /api/v1/admin/reconciliation/` & `POST /api/v1/admin/reconciliation/run/` — Statement reconciliation.
* `GET /api/v1/admin/audit-logs/` — Immutable system audit log trail.
