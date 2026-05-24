from django.contrib.auth.models import BaseUserManager
from core.constants import UserType

class UserManager(BaseUserManager):
    def create_user(self, username, email, phone, password=None, **extra_fields):
        if not username:
            raise ValueError("Username required")
        if not email:
            raise ValueError("Email required")
        if not phone:
            raise ValueError("Phone number required")
        user = self.model(phone=phone, username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, phone, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("user_type", UserType.ADMIN)
        return self.create_user(username, email, phone, password, **extra_fields)

