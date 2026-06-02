from django.core.files.storage import default_storage
from django.db.models import Q
import string
import secrets
import random

class OTPService:
    def get_otp_object(self, data, type):
        from account.models import OTPVerification
        otp = data.get("otp")
        email = data.get("email")
        phone = data.get("phone")
        query = Q(otp_code=otp, is_verified=False, purpose=type)
        if phone:
            query &= Q(phone=phone)
        if email:
            query &= Q(email=email)
        otp_object = OTPVerification.objects.filter(query).last()
        if not otp_object:
            raise Exception("Invalid OTP")
        if otp_object.is_expired():
            raise Exception("OTP expired")
        otp_object.is_verified = True
        otp_object.save(update_fields=["is_verified"])
        return otp_object
    
    def generate_otp(self, length=6):
        from account.models import OTPVerification
        if length <= 0:
            raise ValueError("OTP length must be greater than 0")
        digits = string.digits
        otp = ''.join(secrets.choice(digits) for _ in range(length))
        while OTPVerification.objects.filter(otp=otp).exists():
            otp = ''.join(secrets.choice(digits) for _ in range(length))
        return otp

class ImageDeleteOS:
    def __init__(self, current_picture):
        self.current_picture = current_picture
    
    def previous_image(self, newpicture):
        if self.current_picture and self.current_picture != newpicture and default_storage.exists(self.current_picture.name):
            default_storage.delete(self.current_picture.name)
            return True
    
    def instance_delete(self):
        if self.current_picture and default_storage.exists(self.current_picture):
            default_storage.delete(self.current_picture.name)
            return True

class UsernameGenerate:
    def __init__(self, first_name, last_name, email, phone):
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.phone = phone
    
    def generate_by_fn(self, first_name):
        return first_name.replace(" ", "")
    
    def generate_by_fn_ln(self, first_name, last_name):
        return f"{first_name.replace(" ", "")}{last_name.replace(" ", "")}"
    
    def generate_by_ln(self, last_name):
        return last_name.replace(" ", "")
    
    def generate_by_email(self, email):
        return email.split("@")[0].replace(".", "")
    
    def generate_by_phone(self, phone):
        return f"user{phone}"
    
    def get(self):
        if self.first_name and self.last_name:
            username = self.generate_by_fn_ln(self.first_name, self.last_name)
        elif self.first_name:
            username = self.generate_by_fn(self.first_name)
        elif self.last_name:
            username = self.generate_by_ln(self.last_name)
        elif self.email:
            username = self.generate_by_email(self.email)
        elif self.phone:
            username = self.generate_by_phone(self.phone)
        else:
            raise ValueError("Cannot generate username")
        username = username.lower()
        from account.models import User
        if username and User.objects.filter(username=username).exists():
            username = f"{username}{random.randint(1000, 9999)}"


    
    
