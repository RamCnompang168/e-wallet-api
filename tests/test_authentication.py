import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.authentication.models import OTPCode, OTPPurpose
from apps.authentication.services import OTPService
from apps.users.models import User, UserDevice, UserRole, UserSession, UserStatus
from apps.wallets.models import Wallet


@pytest.mark.django_db
class TestAuthenticationFlow:
    @pytest.fixture(autouse=True)
    def setup_client(self):
        self.client = APIClient()

    def test_registration_success(self):
        payload = {
            "email": "charlie@example.com",
            "phone_number": "+19876543210",
            "full_name": "Charlie Chaplin",
            "password": "StrongPassword123!",
            "pin": "654321",
            "role": "CUSTOMER",
        }
        url = reverse("authentication:register")
        response = self.client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["success"] is True
        assert response.data["data"]["pending_approval"] is True

        # Verify User and Wallet automatically provisioned with PENDING_APPROVAL status
        user = User.objects.get(email="charlie@example.com")
        assert user.status == "PENDING_APPROVAL"
        assert user.check_password("StrongPassword123!")
        assert user.verify_pin("654321") is True
        assert Wallet.objects.filter(user=user, is_primary=True).exists()

    def test_login_success_and_device_tracking(self):
        user = User.objects.create_user(
            email="testlogin@example.com",
            phone_number="+15550001111",
            password="Password123!",
            full_name="Login Test"
        )
        url = reverse("authentication:login")
        payload = {
            "username": "testlogin@example.com",
            "password": "Password123!",
            "device_identifier": "device-uuid-999",
            "device_name": "iPhone 16 Pro",
            "device_type": "IOS",
        }
        response = self.client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "tokens" in response.data["data"]

        # Verify device & session recorded
        assert UserDevice.objects.filter(user=user, device_identifier="device-uuid-999").exists()
        assert UserSession.objects.filter(user=user, is_revoked=False).exists()

    def test_login_invalid_password(self):
        User.objects.create_user(
            email="testwrong@example.com",
            phone_number="+15550002222",
            password="CorrectPassword123!",
            full_name="Wrong Test"
        )
        url = reverse("authentication:login")
        payload = {"username": "testwrong@example.com", "password": "WrongPassword!"}
        response = self.client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["success"] is False

    def test_otp_lifecycle_and_attempt_limit(self):
        user = User.objects.create_user(
            email="otptest@example.com",
            phone_number="+15550003333",
            password="Password123!",
            full_name="OTP Test"
        )
        otp_rec, raw_code = OTPService.generate_otp(
            purpose=OTPPurpose.LOGIN,
            user=user,
            phone_number=user.phone_number
        )

        assert len(raw_code) == 6
        assert otp_rec.attempt_count == 0

        # Attempt 1: wrong code
        with pytest.raises(Exception):
            OTPService.verify_otp(purpose=OTPPurpose.LOGIN, code="000000", user=user)

        otp_rec.refresh_from_db()
        assert otp_rec.attempt_count == 1

        # Attempt 2: correct code
        verified = OTPService.verify_otp(purpose=OTPPurpose.LOGIN, code=raw_code, user=user)
        assert verified is True

        otp_rec.refresh_from_db()
        assert otp_rec.is_used is True

        # Replay attempt fails
        with pytest.raises(Exception):
            OTPService.verify_otp(purpose=OTPPurpose.LOGIN, code=raw_code, user=user)

    def test_refresh_token_rotation_and_revocation(self):
        user = User.objects.create_user(
            email="refreshtest@example.com",
            phone_number="+15550004444",
            password="Password123!",
            full_name="Refresh Test"
        )
        login_res = self.client.post(
            reverse("authentication:login"),
            {"username": "refreshtest@example.com", "password": "Password123!"},
            format="json"
        )
        raw_refresh = login_res.data["data"]["tokens"]["refresh_token"]

        # Rotate token
        rotate_res = self.client.post(
            reverse("authentication:refresh"),
            {"refresh_token": raw_refresh},
            format="json"
        )
        assert rotate_res.status_code == status.HTTP_200_OK
        new_refresh = rotate_res.data["data"]["refresh_token"]
        assert new_refresh != raw_refresh

        # Reuse of old refresh token must be rejected
        reuse_res = self.client.post(
            reverse("authentication:refresh"),
            {"refresh_token": raw_refresh},
            format="json"
        )
        assert reuse_res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_registration_with_profile_details_and_photo_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        payload = {
            "email": "sokha.chan@example.com",
            "phone_number": "012345678",
            "full_name": "Sokha Chan",
            "password": "StrongPassword123!",
            "pin": "123456",
            "gender": "FEMALE",
            "date_of_birth": "1998-05-20",
        }
        url = reverse("authentication:register")
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email="sokha.chan@example.com")
        assert user.phone_number == "+85512345678"
        assert user.gender == "FEMALE"
        assert str(user.date_of_birth) == "1998-05-20"
        assert user.status == "PENDING_APPROVAL"

        # Admin approves the account
        user.status = "ACTIVE"
        user.save()

        # User obtains session token after approval
        from apps.authentication.services import AuthService
        token_data = AuthService.create_user_session(user=user)
        token = token_data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        import io
        from PIL import Image
        img_buffer = io.BytesIO()
        image = Image.new("RGB", (100, 100), color=(70, 130, 180))
        image.save(img_buffer, format="JPEG")
        dummy_image = SimpleUploadedFile(
            "avatar.jpg",
            img_buffer.getvalue(),
            content_type="image/jpeg"
        )
        photo_url = reverse("users:profile_photo")
        upload_res = self.client.post(photo_url, {"profile_photo": dummy_image}, format="multipart")
        assert upload_res.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert bool(user.profile_photo) is True
