from django.db import models
from core.common_models import BaseModel
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, AbstractUser
from .managers import UserManager
from core.constants import UserStatus, UserType, OTPPurpose, TeamMemberStatus, PaymentMethodType
from django.db import transaction
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils.translation import gettext_lazy as _


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    username_validator = UnicodeUsernameValidator()
    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."
        ),
        validators=[username_validator],
        error_messages={
            "unique": _("A user with that username already exists."),
        },
    )
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    profile_image = models.URLField(blank=True, null=True)

    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.MAIN_USER,)
    status = models.CharField( max_length=20, choices=UserStatus.choices, default=UserStatus.ACTIVE,)

    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_device_info = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["user_type"]),
        ]

    def __str__(self):
        return self.email

class OTPVerification(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    otp_code = models.CharField(max_length=10)
    purpose = models.CharField(max_length=20, choices=OTPPurpose.choices)
    is_verified = models.BooleanField(default=False)

    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_info = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["otp_code"]),
        ]
    
    def __str__(self):
        return f"{self.otp_code} OTP for {self.user.email}"

class Team(BaseModel):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_teams")
    subscription = models.OneToOneField("subscription.UserSubscription", on_delete=models.SET_NULL, related_name="team", blank=True, null=True)
    name = models.CharField(max_length=255)
    max_members = models.PositiveIntegerField(default=0)
    used_members = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.name} of {self.owner.email}"

class TeamMember(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    status = models.CharField(max_length=20, choices=TeamMemberStatus.choices, default=TeamMemberStatus.ACTIVE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["team", "user"]
    
    def __str__(self):
        return f"{self.user.email} Member of {self.team}"

class UserPaymentMethod(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payment_methods")
    provider = models.CharField(max_length=50)  # stripe, razorpay
    method_type = models.CharField(max_length=30, choices=PaymentMethodType.choices, default=PaymentMethodType.CARD)

    payment_token = models.CharField(max_length=255)
    brand = models.CharField(max_length=50, blank=True, null=True)
    last4 = models.CharField(max_length=4, blank=True, null=True)
    # optional extra data (non-sensitive only)
    method_data = models.JSONField(blank=True, null=True)

    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="unique_default_payment_per_user"
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not CustomerPaymentMethod.objects.filter(user=self.user).exists():
                self.is_default = True
            
            if self.is_default:
                CustomerPaymentMethod.objects.filter(
                    user=self.user,
                    is_default=True
                ).update(is_default=False)
            super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        with transaction.atomic():
            user = self.user
            is_default = self.is_default
            super().delete(*args, **kwargs)
            if is_default:
                next_method = CustomerPaymentMethod.objects.filter(user=user).first()
                if next_method:
                    next_method.is_default = True
                    next_method.save()

