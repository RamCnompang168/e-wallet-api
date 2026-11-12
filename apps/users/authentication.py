from django.contrib.auth.backends import BaseBackend
from .models import User


class UsernameOrPhoneBackend(BaseBackend):
    """Supports Django admin usernames while preserving mobile phone login."""

    def authenticate(self, request, username=None, phone_number=None, password=None, **kwargs):
        identifier = username or phone_number
        if not identifier or not password:
            return None
        user = User.objects.filter(username=identifier).first() if username else User.objects.filter(phone_number=identifier).first()
        if user and user.is_active and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        return User.objects.filter(pk=user_id).first()
