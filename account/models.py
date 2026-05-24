from django.db import models
from core.common_models import BaseModel
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager
from core.constants import UserStatus, UserType, OTPPurpose, TeamMemberStatus, PaymentMethodType, TeamMemberRole
from django.db import transaction
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils.translation import gettext_lazy as _
import random
from core.utils import ImageDeleteOS, UsernameGenerate


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
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    profile_image = models.ImageField(
        upload_to="profiles/",
        null=True,
        blank=True
    )

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
    
    @property
    def full_name(self):
        return (
            f"{self.first_name or ''} {self.last_name or ''}"
        ).strip()
    
    def image_update(self, instance):
        image_delete = ImageDeleteOS(instance.profile_image)
        image_delete.previous_image(self.profile_image)
    
    def delete(self, *args, **kwargs):
        image_delete = ImageDeleteOS(self.profile_image)
        image_delete.instance_delete()
        return super().delete(*args, **kwargs)

    def generate_username(self):
        username = UsernameGenerate(self.first_name, self.last_name, self.email, self.phone)
        return username
    
    def save(self, *args, **kwargs):
        if self.pk and self.profile_image and User.objects.filter(pk=self.pk).exists():
            instance = User.objects.get(pk=self.pk)
            self.image_update(instance)
        
        if not self.username: self.username = self.generate_username()
        # if not self.referral_code: self.referral_code = self.generate_referral_code()
        return super().save(*args, **kwargs)

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
    is_active = models.BooleanField(default=True)
    
    @property
    def used_members(self, obj):
        return obj.members.filter(status=TeamMemberStatus.ACTIVE).count()
    
    def __str__(self):
        return f"{self.name} of {self.owner.email}"

class TeamMember(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=20, choices=TeamMemberRole.choices, default=TeamMemberRole.MEMBER)
    status = models.CharField(max_length=20, choices=TeamMemberStatus.choices, default=TeamMemberStatus.ACTIVE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'user'],
                name='unique_team_user'
            )
        ]
    
    def __str__(self):
        return f"{self.user.email} Member of {self.team}"

class UserPaymentMethod(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payment_methods")
    provider = models.CharField(max_length=50)  # stripe, razorpay
    method_type = models.CharField(max_length=30, choices=PaymentMethodType.choices, default=PaymentMethodType.CARD)

    payment_token = models.CharField(max_length=255)
    provider_payment_method_id = models.CharField(max_length=255, blank=True, null=True)
    fingerprint = models.CharField(max_length=50, blank=True, null=True)
    expiry_month = models.CharField(max_length=50, blank=True, null=True)
    expiry_year = models.CharField(max_length=50, blank=True, null=True)
    holder_name = models.CharField(max_length=50, blank=True, null=True)
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
            if not UserPaymentMethod.objects.filter(user=self.user).exists():
                self.is_default = True
            
            if self.is_default:
                UserPaymentMethod.objects.filter(
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
                next_method = UserPaymentMethod.objects.filter(user=user).first()
                if next_method:
                    next_method.is_default = True
                    next_method.save()

