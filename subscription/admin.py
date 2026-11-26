from django.contrib import admin
from .models import SubscriptionPlan, UserSubscription, PurchaseInfo, FleetAccount, DiscountCoupon, CouponRedemption

admin.site.register(SubscriptionPlan)
admin.site.register(UserSubscription)
admin.site.register(PurchaseInfo)
admin.site.register(FleetAccount)
admin.site.register(DiscountCoupon)
admin.site.register(CouponRedemption)

