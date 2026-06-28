from django.contrib import admin
from .models import SubscriptionPlan, UserSubscription, PurchaseInfo

admin.site.register(SubscriptionPlan)
admin.site.register(UserSubscription)
admin.site.register(PurchaseInfo)

