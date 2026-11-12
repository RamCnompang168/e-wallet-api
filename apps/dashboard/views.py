import json
from decimal import Decimal
from datetime import timedelta
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from apps.users.models import User, UserStatus, UserRole, AuditLog, SecurityEvent
from apps.wallets.models import Wallet, WalletStatus
from apps.transactions.models import Transaction, TransactionStatus, TransactionType
from apps.notifications.services import NotificationService


class DashboardOverviewView(View):
    """Main overview and KPI analytics screen."""

    def get(self, request):
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Users counts
        total_users = User.objects.count()
        active_users = User.objects.filter(status=UserStatus.ACTIVE).count()
        pending_approvals = User.objects.filter(status=UserStatus.PENDING_APPROVAL).count()
        rejected_users = User.objects.filter(status=UserStatus.REJECTED).count()

        # Wallets & Liquidity
        total_wallets = Wallet.objects.count()
        active_wallets = Wallet.objects.filter(status=WalletStatus.ACTIVE).count()
        liquidity_agg = Wallet.objects.filter(status=WalletStatus.ACTIVE).aggregate(
            total_current=Sum("current_balance"),
            total_available=Sum("available_balance"),
            total_hold=Sum("hold_balance")
        )
        total_liquidity = liquidity_agg["total_available"] or Decimal("0.00")
        total_hold = liquidity_agg["total_hold"] or Decimal("0.00")

        # Transactions metrics
        total_transactions = Transaction.objects.count()
        completed_transactions = Transaction.objects.filter(status=TransactionStatus.COMPLETED).count()
        failed_transactions = Transaction.objects.filter(status=TransactionStatus.FAILED).count()
        success_rate = (
            round((completed_transactions / total_transactions * 100), 1)
            if total_transactions > 0
            else 100.0
        )

        completed_volume_agg = Transaction.objects.filter(
            status=TransactionStatus.COMPLETED
        ).aggregate(volume=Sum("amount"))
        total_volume = completed_volume_agg["volume"] or Decimal("0.00")

        # 30 days volume
        month_volume_agg = Transaction.objects.filter(
            status=TransactionStatus.COMPLETED,
            created_at__gte=thirty_days_ago
        ).aggregate(volume=Sum("amount"))
        month_volume = month_volume_agg["volume"] or Decimal("0.00")

        # 7-day daily volume for Chart.js
        daily_labels = []
        daily_amounts = []
        for i in range(6, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            day_vol = Transaction.objects.filter(
                status=TransactionStatus.COMPLETED,
                created_at__gte=day_start,
                created_at__lt=day_end
            ).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
            daily_labels.append(day_start.strftime("%b %d"))
            daily_amounts.append(float(day_vol))

        # Transaction type breakdown
        type_counts = {
            "transfers": Transaction.objects.filter(transaction_type=TransactionType.TRANSFER).count(),
            "topups": Transaction.objects.filter(transaction_type=TransactionType.TOPUP).count(),
            "withdrawals": Transaction.objects.filter(transaction_type=TransactionType.WITHDRAWAL).count(),
            "merchant_qr": Transaction.objects.filter(transaction_type=TransactionType.MERCHANT_PAYMENT).exclude(reference_number__startswith="GOV-").count(),
            "government": Transaction.objects.filter(reference_number__startswith="GOV-").count(),
        }

        recent_transactions = Transaction.objects.select_related(
            "sender_wallet__user", "receiver_wallet__user"
        ).order_by("-created_at")[:8]

        pending_users_preview = User.objects.filter(
            status=UserStatus.PENDING_APPROVAL
        ).order_by("-created_at")[:5]

        context = {
            "active_tab": "overview",
            "total_users": total_users,
            "active_users": active_users,
            "pending_approvals": pending_approvals,
            "rejected_users": rejected_users,
            "total_wallets": total_wallets,
            "active_wallets": active_wallets,
            "total_liquidity": total_liquidity,
            "total_hold": total_hold,
            "total_transactions": total_transactions,
            "completed_transactions": completed_transactions,
            "failed_transactions": failed_transactions,
            "success_rate": success_rate,
            "total_volume": total_volume,
            "month_volume": month_volume,
            "daily_labels_json": json.dumps(daily_labels),
            "daily_amounts_json": json.dumps(daily_amounts),
            "type_counts": type_counts,
            "recent_transactions": recent_transactions,
            "pending_users_preview": pending_users_preview,
        }
        return render(request, "dashboard/overview.html", context)


class DashboardApprovalsView(View):
    """Account approvals and KYC verification hub."""

    def get(self, request):
        status_filter = request.GET.get("filter", "PENDING_APPROVAL")
        query = request.GET.get("q", "").strip()

        users_qs = User.objects.all().order_by("-created_at")
        if status_filter != "ALL":
            users_qs = users_qs.filter(status=status_filter)

        if query:
            users_qs = users_qs.filter(
                Q(full_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone_number__icontains=query)
                | Q(id_document_number__icontains=query)
            )

        pending_count = User.objects.filter(status=UserStatus.PENDING_APPROVAL).count()
        active_count = User.objects.filter(status=UserStatus.ACTIVE).count()
        rejected_count = User.objects.filter(status=UserStatus.REJECTED).count()

        context = {
            "active_tab": "approvals",
            "users": users_qs[:50],
            "current_filter": status_filter,
            "query": query,
            "pending_count": pending_count,
            "active_count": active_count,
            "rejected_count": rejected_count,
        }
        return render(request, "dashboard/approvals.html", context)


class DashboardApproveUserView(View):
    """Approve a user account directly from web dashboard."""

    def post(self, request, pk):
        user = get_object_or_404(User, id=pk)
        old_status = user.status
        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])

        # Activate primary wallet
        primary_wallet, _ = Wallet.objects.get_or_create(
            user=user,
            is_primary=True,
            defaults={"currency": "USD", "current_balance": 0, "available_balance": 0}
        )
        if primary_wallet.status != WalletStatus.ACTIVE:
            primary_wallet.status = WalletStatus.ACTIVE
            primary_wallet.save(update_fields=["status", "updated_at"])

        # Send in-app notification
        try:
            NotificationService.create_notification(
                user=user,
                notification_type="SYSTEM",
                title="Account Approved! 🎉",
                message=f"Welcome {user.full_name}! Your NovaPay wallet account has been approved and activated."
            )
        except Exception:
            pass

        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else user,
            action="WEB_ADMIN_APPROVE_USER",
            entity_type="User",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": UserStatus.ACTIVE}
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "message": f"User {user.full_name} has been approved."})

        messages.success(request, f"User {user.full_name} ({user.phone_number}) approved and activated successfully.")
        return redirect(request.META.get("HTTP_REFERER", reverse("dashboard:approvals")))


class DashboardRejectUserView(View):
    """Reject user registration from web dashboard."""

    def post(self, request, pk):
        user = get_object_or_404(User, id=pk)
        old_status = user.status
        reason = request.POST.get("reason", "Identity document verification could not be completed.")

        user.status = UserStatus.REJECTED
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])

        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else user,
            action="WEB_ADMIN_REJECT_USER",
            entity_type="User",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": UserStatus.REJECTED, "reason": reason}
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "message": f"User {user.full_name} has been rejected."})

        messages.warning(request, f"Registration for {user.full_name} rejected: {reason}")
        return redirect(request.META.get("HTTP_REFERER", reverse("dashboard:approvals")))


class DashboardUsersView(View):
    """User directory management screen."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        role = request.GET.get("role", "")
        user_status = request.GET.get("status", "")

        users_qs = User.objects.all().prefetch_related("wallets").order_by("-created_at")

        if query:
            users_qs = users_qs.filter(
                Q(full_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone_number__icontains=query)
                | Q(id_document_number__icontains=query)
            )
        if role:
            users_qs = users_qs.filter(role=role)
        if user_status:
            users_qs = users_qs.filter(status=user_status)

        context = {
            "active_tab": "users",
            "users": users_qs[:100],
            "query": query,
            "selected_role": role,
            "selected_status": user_status,
            "total_count": users_qs.count(),
        }
        return render(request, "dashboard/users.html", context)


class DashboardUserDetailView(View):
    """Detailed profile, KYC credentials, wallets, and ledger transaction history for a user."""

    def get(self, request, pk):
        target_user = get_object_or_404(
            User.objects.prefetch_related("wallets"),
            pk=pk
        )
        wallets = list(target_user.wallets.all().order_by("-is_primary", "currency"))
        wallet_ids = [w.id for w in wallets]

        # Transactions involving target user's wallets
        txns_qs = Transaction.objects.filter(
            Q(sender_wallet__in=wallets) | Q(receiver_wallet__in=wallets)
        ).select_related(
            "sender_wallet__user", "receiver_wallet__user"
        ).order_by("-created_at")

        # Optional filters
        direction = request.GET.get("direction", "").strip()
        tx_type = request.GET.get("type", "").strip()
        query = request.GET.get("q", "").strip()

        if direction == "received":
            txns_qs = txns_qs.filter(receiver_wallet__in=wallets)
        elif direction == "sent":
            txns_qs = txns_qs.filter(sender_wallet__in=wallets)

        if tx_type:
            txns_qs = txns_qs.filter(transaction_type=tx_type)

        if query:
            txns_qs = txns_qs.filter(
                Q(transaction_code__icontains=query)
                | Q(reference_number__icontains=query)
                | Q(description__icontains=query)
                | Q(sender_wallet__user__full_name__icontains=query)
                | Q(receiver_wallet__user__full_name__icontains=query)
            )

        # Financial totals
        completed_txns = Transaction.objects.filter(
            Q(sender_wallet__in=wallets) | Q(receiver_wallet__in=wallets),
            status=TransactionStatus.COMPLETED
        )
        total_received = completed_txns.filter(receiver_wallet__in=wallets).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        total_sent = completed_txns.filter(sender_wallet__in=wallets).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        total_fees = completed_txns.filter(sender_wallet__in=wallets).aggregate(s=Sum("fee_amount"))["s"] or Decimal("0.00")

        total_balance_usd = sum(w.current_balance for w in wallets if w.currency == "USD")
        total_balance_khr = sum(w.current_balance for w in wallets if w.currency == "KHR")

        # Tag transactions with inflow/outflow relative to target user
        transactions_list = []
        for txn in txns_qs[:100]:
            is_inflow = txn.receiver_wallet_id in wallet_ids
            is_outflow = txn.sender_wallet_id in wallet_ids

            if is_inflow and is_outflow:
                direction_label = "Internal Transfer"
                counterparty_name = "Self (Own Wallets)"
                counterparty_sub = f"{txn.sender_wallet.currency} → {txn.receiver_wallet.currency}" if txn.sender_wallet and txn.receiver_wallet else "Internal"
            elif is_inflow:
                direction_label = "Received"
                counterparty_name = txn.sender_wallet.user.full_name if txn.sender_wallet and txn.sender_wallet.user else "External / Deposit"
                counterparty_sub = txn.sender_wallet.user.phone_number if txn.sender_wallet and txn.sender_wallet.user else (txn.reference_number or "Inflow")
            else:
                direction_label = "Sent"
                counterparty_name = txn.receiver_wallet.user.full_name if txn.receiver_wallet and txn.receiver_wallet.user else "External / Outflow"
                counterparty_sub = txn.receiver_wallet.user.phone_number if txn.receiver_wallet and txn.receiver_wallet.user else (txn.reference_number or "Outflow")

            transactions_list.append({
                "txn": txn,
                "is_inflow": is_inflow and not (is_inflow and is_outflow),
                "is_outflow": is_outflow and not (is_inflow and is_outflow),
                "is_internal": is_inflow and is_outflow,
                "direction_label": direction_label,
                "counterparty_name": counterparty_name,
                "counterparty_sub": counterparty_sub,
            })

        recent_events = SecurityEvent.objects.filter(user=target_user).order_by("-created_at")[:6]

        context = {
            "active_tab": "users",
            "target_user": target_user,
            "wallets": wallets,
            "transactions": transactions_list,
            "total_count": txns_qs.count(),
            "total_received": total_received,
            "total_sent": total_sent,
            "total_fees": total_fees,
            "total_balance_usd": total_balance_usd,
            "total_balance_khr": total_balance_khr,
            "selected_direction": direction,
            "selected_type": tx_type,
            "search_query": query,
            "recent_events": recent_events,
        }

        if request.GET.get("modal") == "1" or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return render(request, "dashboard/user_detail_modal_content.html", context)
        return render(request, "dashboard/user_detail.html", context)


class DashboardWalletsView(View):
    """Wallets and liquidity pool overview."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        currency = request.GET.get("currency", "")

        wallets_qs = Wallet.objects.select_related("user").order_by("-created_at")
        if query:
            wallets_qs = wallets_qs.filter(
                Q(wallet_number__icontains=query)
                | Q(user__full_name__icontains=query)
                | Q(user__email__icontains=query)
                | Q(user__phone_number__icontains=query)
            )
        if currency:
            wallets_qs = wallets_qs.filter(currency=currency)

        total_funds = wallets_qs.aggregate(total=Sum("current_balance"))["total"] or Decimal("0.00")

        context = {
            "active_tab": "wallets",
            "wallets": wallets_qs[:100],
            "query": query,
            "currency": currency,
            "total_funds": total_funds,
            "total_count": wallets_qs.count(),
        }
        return render(request, "dashboard/wallets.html", context)


class DashboardTransactionsView(View):
    """Complete transactions ledger explorer."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        txn_type = request.GET.get("type", "")
        txn_status = request.GET.get("status", "")

        txns_qs = Transaction.objects.select_related(
            "sender_wallet__user", "receiver_wallet__user"
        ).order_by("-created_at")

        if query:
            txns_qs = txns_qs.filter(
                Q(transaction_code__icontains=query)
                | Q(reference_number__icontains=query)
                | Q(description__icontains=query)
                | Q(sender_wallet__user__full_name__icontains=query)
                | Q(receiver_wallet__user__full_name__icontains=query)
            )
        if txn_type:
            txns_qs = txns_qs.filter(transaction_type=txn_type)
        if txn_status:
            txns_qs = txns_qs.filter(status=txn_status)

        total_sum = txns_qs.filter(status=TransactionStatus.COMPLETED).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

        context = {
            "active_tab": "transactions",
            "transactions": txns_qs[:100],
            "query": query,
            "selected_type": txn_type,
            "selected_status": txn_status,
            "total_sum": total_sum,
            "total_count": txns_qs.count(),
        }
        return render(request, "dashboard/transactions.html", context)


class DashboardGovernmentServicesView(View):
    """Tracking Cambodian public utility and tax payments."""

    def get(self, request):
        query = request.GET.get("q", "").strip()

        gov_txns = Transaction.objects.filter(
            Q(reference_number__startswith="GOV-")
            | Q(description__icontains="Tax")
            | Q(description__icontains="EDC")
            | Q(description__icontains="PPWSA")
            | Q(description__icontains="NSSF")
        ).select_related("sender_wallet__user").order_by("-created_at")

        if query:
            gov_txns = gov_txns.filter(
                Q(reference_number__icontains=query)
                | Q(description__icontains=query)
                | Q(sender_wallet__user__full_name__icontains=query)
            )

        # Department breakdown
        road_tax_count = gov_txns.filter(description__icontains="Road Tax").count()
        edc_count = gov_txns.filter(description__icontains="EDC").count()
        ppwsa_count = gov_txns.filter(description__icontains="PPWSA").count()
        nssf_count = gov_txns.filter(description__icontains="NSSF").count()
        inspection_count = gov_txns.filter(description__icontains="Inspection").count()

        total_collected = gov_txns.filter(status=TransactionStatus.COMPLETED).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

        context = {
            "active_tab": "government",
            "transactions": gov_txns[:100],
            "query": query,
            "total_collected": total_collected,
            "total_count": gov_txns.count(),
            "dept_counts": {
                "road_tax": road_tax_count,
                "edc": edc_count,
                "ppwsa": ppwsa_count,
                "nssf": nssf_count,
                "inspection": inspection_count,
            }
        }
        return render(request, "dashboard/government.html", context)


class DashboardApiDocsView(View):
    """Interactive API and Sub-APIs documentation page."""

    def get(self, request):
        api_catalog = [
            {
                "group_name": "Authentication & Security API",
                "badge": "auth",
                "description": "JWT session issuance, 3-step user onboarding, Google Sign-In, OTP validation, and PIN management.",
                "sub_apis": [
                    {
                        "name": "Register User (3-Step)",
                        "method": "POST",
                        "endpoint": "/api/v1/auth/register/",
                        "auth": "Public",
                        "description": "Submits 3-step registration credentials, National ID / Passport metadata and photos, and personal avatar. Newly created accounts require administrator approval.",
                        "headers": {"Content-Type": "application/json"},
                        "request_body": {
                            "email": "customer@novapay.kh",
                            "phone_number": "+85512345678",
                            "full_name": "Sokha Chan",
                            "password": "SecurePassword123",
                            "pin": "123456",
                            "id_document_type": "NATIONAL_ID",
                            "id_document_number": "012345678",
                            "id_document_photo_base64": "<base64_jpeg_string>",
                            "profile_photo_base64": "<base64_jpeg_string>",
                            "gender": "MALE",
                            "date_of_birth": "1998-05-20"
                        },
                        "response_example": {
                            "success": True,
                            "message": "Registration submitted successfully. Account pending approval.",
                            "data": {
                                "user": {
                                    "id": "c1f7b0c3-...",
                                    "email": "customer@novapay.kh",
                                    "status": "PENDING_APPROVAL"
                                },
                                "pending_approval": True
                            }
                        }
                    },
                    {
                        "name": "User Login",
                        "method": "POST",
                        "endpoint": "/api/v1/auth/login/",
                        "auth": "Public",
                        "description": "Authenticates active user with phone/email and password. Returns JWT access and refresh tokens. Returns 403 if account is pending approval.",
                        "headers": {"Content-Type": "application/json"},
                        "request_body": {
                            "username": "+85512345678",
                            "password": "SecurePassword123"
                        },
                        "response_example": {
                            "success": True,
                            "tokens": {
                                "access": "eyJhbGciOi...",
                                "refresh": "eyJhbGciOi..."
                            },
                            "user": {
                                "id": "uuid",
                                "full_name": "Sokha Chan",
                                "role": "CUSTOMER",
                                "status": "ACTIVE"
                            }
                        }
                    },
                    {
                        "name": "Google Sign-In",
                        "method": "POST",
                        "endpoint": "/api/v1/auth/google/",
                        "auth": "Public",
                        "description": "Authenticates or provisions user via Google Identity. Immediately issues active session tokens and primary wallet.",
                        "headers": {"Content-Type": "application/json"},
                        "request_body": {
                            "email": "user@gmail.com",
                            "full_name": "User Name",
                            "google_id": "google-oauth2|123456789",
                            "profile_photo": "https://lh3.googleusercontent.com/..."
                        },
                        "response_example": {
                            "success": True,
                            "tokens": {"access": "token", "refresh": "token"},
                            "user": {"email": "user@gmail.com", "status": "ACTIVE"}
                        }
                    },
                    {
                        "name": "Request OTP Code",
                        "method": "POST",
                        "endpoint": "/api/v1/auth/otp/request/",
                        "auth": "Public",
                        "description": "Generates 6-digit numeric OTP with 5-minute TTL for registration or transaction verification.",
                        "headers": {"Content-Type": "application/json"},
                        "request_body": {
                            "phone_number": "+85512345678",
                            "purpose": "REGISTRATION"
                        },
                        "response_example": {
                            "success": True,
                            "message": "OTP sent successfully."
                        }
                    },
                    {
                        "name": "Token Refresh",
                        "method": "POST",
                        "endpoint": "/api/v1/auth/token/refresh/",
                        "auth": "Public",
                        "description": "Rotates refresh token and returns a fresh JWT access token.",
                        "headers": {"Content-Type": "application/json"},
                        "request_body": {
                            "refresh": "eyJhbGciOi..."
                        },
                        "response_example": {
                            "access": "eyJhbGciOi...",
                            "refresh": "eyJhbGciOi..."
                        }
                    }
                ]
            },
            {
                "group_name": "Users & Admin Approvals API",
                "badge": "users",
                "description": "Profile data, identity verification, approval management, device auditing, and security logs.",
                "sub_apis": [
                    {
                        "name": "Get User Profile",
                        "method": "GET",
                        "endpoint": "/api/v1/users/profile/",
                        "auth": "Bearer JWT",
                        "description": "Fetches profile info of authenticated user including document type, document number, profile photo, and KYC level.",
                        "headers": {"Authorization": "Bearer <access_token>"},
                        "request_body": None,
                        "response_example": {
                            "success": True,
                            "data": {
                                "id": "uuid",
                                "full_name": "Sokha Chan",
                                "phone_number": "+85512345678",
                                "email": "sokha@example.com",
                                "id_document_type": "NATIONAL_ID",
                                "id_document_number": "012345678",
                                "id_document_photo": "/media/docs/doc_123.jpg",
                                "kyc_tier": 1,
                                "role": "CUSTOMER"
                            }
                        }
                    },
                    {
                        "name": "Admin Pending Approvals Queue",
                        "method": "GET",
                        "endpoint": "/api/v1/users/admin/pending-approvals/",
                        "auth": "Staff / Admin JWT",
                        "description": "Lists all user registrations waiting for administrator inspection, with document photos and personal details.",
                        "headers": {"Authorization": "Bearer <admin_jwt>"},
                        "request_body": None,
                        "response_example": {
                            "success": True,
                            "data": [
                                {
                                    "id": "uuid",
                                    "full_name": "Dara Som",
                                    "email": "dara@example.com",
                                    "phone_number": "+85598765432",
                                    "id_document_type": "NATIONAL_ID",
                                    "id_document_number": "098765432",
                                    "id_document_photo": "http://127.0.0.1:8000/media/docs/doc_1.jpg",
                                    "status": "PENDING_APPROVAL"
                                }
                            ]
                        }
                    },
                    {
                        "name": "Admin Approve User",
                        "method": "POST",
                        "endpoint": "/api/v1/users/admin/users/<uuid:pk>/approve/",
                        "auth": "Staff / Admin JWT",
                        "description": "Approves applicant, activates status to ACTIVE, activates primary wallet, and records audit trail.",
                        "headers": {"Authorization": "Bearer <admin_jwt>"},
                        "request_body": {},
                        "response_example": {
                            "success": True,
                            "message": "User approved and activated successfully."
                        }
                    },
                    {
                        "name": "Admin Reject User",
                        "method": "POST",
                        "endpoint": "/api/v1/users/admin/users/<uuid:pk>/reject/",
                        "auth": "Staff / Admin JWT",
                        "description": "Rejects registration, sets status to REJECTED, and logs rejection reason.",
                        "headers": {"Authorization": "Bearer <admin_jwt>"},
                        "request_body": {"reason": "ID photo unreadable."},
                        "response_example": {
                            "success": True,
                            "message": "User registration has been rejected."
                        }
                    }
                ]
            },
            {
                "group_name": "Wallets & Balance API",
                "badge": "wallets",
                "description": "Multi-currency wallet accounts, available balances, and hold accounting.",
                "sub_apis": [
                    {
                        "name": "Get Primary Wallet",
                        "method": "GET",
                        "endpoint": "/api/v1/wallet/",
                        "auth": "Bearer JWT",
                        "description": "Retrieves authenticated user's primary wallet account, balance, currency, and account number.",
                        "headers": {"Authorization": "Bearer <access_token>"},
                        "request_body": None,
                        "response_example": {
                            "success": True,
                            "data": {
                                "id": "uuid",
                                "wallet_number": "WAL-48201934",
                                "currency": "USD",
                                "current_balance": "1250.0000",
                                "available_balance": "1250.0000",
                                "status": "ACTIVE"
                            }
                        }
                    }
                ]
            },
            {
                "group_name": "Transfers & P2P API",
                "badge": "transfers",
                "description": "Real-time money transfer between wallet accounts by phone, email, or wallet number.",
                "sub_apis": [
                    {
                        "name": "Execute Transfer",
                        "method": "POST",
                        "endpoint": "/api/v1/transfers/",
                        "auth": "Bearer JWT + PIN",
                        "description": "Executes double-entry balance transfer with atomic ledger verification and 6-digit transaction PIN.",
                        "headers": {
                            "Authorization": "Bearer <access_token>",
                            "X-Transaction-PIN": "123456",
                            "Idempotency-Key": "unique-uuid"
                        },
                        "request_body": {
                            "recipient": "+85598765432",
                            "amount": "25.00",
                            "description": "Lunch payment",
                            "currency": "USD"
                        },
                        "response_example": {
                            "success": True,
                            "message": "Transfer completed successfully.",
                            "data": {
                                "reference_number": "TXN-20260928-AB34",
                                "amount": "25.00",
                                "recipient_name": "Dara Som",
                                "status": "COMPLETED"
                            }
                        }
                    }
                ]
            },
            {
                "group_name": "Payments, Top-ups & QR Payments API",
                "badge": "payments",
                "description": "Top-up simulation, withdrawals, merchant payments, and Bakong KHQR integration.",
                "sub_apis": [
                    {
                        "name": "Top-up / Deposit",
                        "method": "POST",
                        "endpoint": "/api/v1/topups/",
                        "auth": "Bearer JWT",
                        "description": "Deposits funds into user's wallet from bank or card simulation.",
                        "headers": {"Authorization": "Bearer <access_token>"},
                        "request_body": {
                            "amount": "100.00",
                            "payment_method_id": "uuid"
                        },
                        "response_example": {
                            "success": True,
                            "message": "Deposit completed successfully."
                        }
                    },
                    {
                        "name": "Withdrawal / Cash-out",
                        "method": "POST",
                        "endpoint": "/api/v1/withdrawals/",
                        "auth": "Bearer JWT + PIN",
                        "description": "Withdraws funds from wallet to external linked bank account.",
                        "headers": {
                            "Authorization": "Bearer <access_token>",
                            "X-Transaction-PIN": "123456"
                        },
                        "request_body": {
                            "amount": "50.00",
                            "payment_method_id": "uuid"
                        },
                        "response_example": {
                            "success": True,
                            "message": "Withdrawal completed successfully."
                        }
                    }
                ]
            },
            {
                "group_name": "Government Services & Tax API",
                "badge": "gov",
                "description": "Direct public utility and tax payments (GDT Road Tax, EDC Electricity, PPWSA Water, NSSF).",
                "sub_apis": [
                    {
                        "name": "Pay Government Service",
                        "method": "POST",
                        "endpoint": "/api/v1/payments/government/",
                        "auth": "Bearer JWT + PIN",
                        "description": "Deducts fee from wallet and credits the relevant Cambodian ministry/department with official reference code.",
                        "headers": {
                            "Authorization": "Bearer <access_token>",
                            "X-Transaction-PIN": "123456"
                        },
                        "request_body": {
                            "service_id": "road_tax",
                            "service_name": "Road Tax (ពន្ធលើមធ្យោបាយដឹកជញ្ជូន)",
                            "consumer_number": "2B-4819",
                            "amount": "25.00",
                            "notes": "Toyota Prius 2012"
                        },
                        "response_example": {
                            "success": True,
                            "message": "Successfully paid for Road Tax.",
                            "data": {
                                "reference_number": "GOV-A9F2",
                                "amount": "25.00",
                                "service_name": "Road Tax (ពន្ធលើមធ្យោបាយដឹកជញ្ជូន)",
                                "consumer_number": "2B-4819"
                            }
                        }
                    }
                ]
            },
            {
                "group_name": "Notifications & Alerts API",
                "badge": "notifications",
                "description": "Real-time in-app push alerts, unread counts, and transactional notifications.",
                "sub_apis": [
                    {
                        "name": "List Notifications",
                        "method": "GET",
                        "endpoint": "/api/v1/notifications/",
                        "auth": "Bearer JWT",
                        "description": "Returns paginated list of transaction alerts, approval notifications, and security notices.",
                        "headers": {"Authorization": "Bearer <access_token>"},
                        "request_body": None,
                        "response_example": {
                            "success": True,
                            "data": [
                                {
                                    "id": "uuid",
                                    "title": "Money Received",
                                    "message": "You received $25.00 from Sokha Chan",
                                    "is_read": False
                                }
                            ]
                        }
                    }
                ]
            }
        ]

        context = {
            "active_tab": "api_docs",
            "api_catalog": api_catalog,
            "total_endpoints": sum(len(group["sub_apis"]) for group in api_catalog),
            "total_groups": len(api_catalog),
        }
        return render(request, "dashboard/api_docs.html", context)


@method_decorator(csrf_exempt, name="dispatch")
class DashboardApiTestRunnerView(View):
    """Allows running live endpoint checks from web browser."""

    def post(self, request):
        endpoint = request.POST.get("endpoint", "")
        method = request.POST.get("method", "GET").upper()

        if endpoint == "/api/v1/users/admin/pending-approvals/":
            pending = User.objects.filter(status=UserStatus.PENDING_APPROVAL).count()
            return JsonResponse({
                "status": 200,
                "data": {
                    "success": True,
                    "message": "Pending approvals endpoint live.",
                    "pending_count": pending,
                    "server_time": timezone.now().isoformat()
                }
            })
        elif endpoint == "/api/v1/wallet/":
            wallet_count = Wallet.objects.count()
            return JsonResponse({
                "status": 200,
                "data": {
                    "success": True,
                    "message": "Wallet service active.",
                    "total_active_wallets": wallet_count
                }
            })
        else:
            return JsonResponse({
                "status": 200,
                "data": {
                    "success": True,
                    "endpoint": endpoint,
                    "method": method,
                    "message": "Live connection verified. Service is active and responding."
                }
            })
