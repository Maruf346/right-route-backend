from django.contrib import admin
from .models import User, OTPVerification, Team, TeamMember, TeamMemberInvite, UserPaymentMethod, UserLogDevice

admin.site.register(User)
admin.site.register(OTPVerification)
admin.site.register(Team)
admin.site.register(TeamMember)
admin.site.register(TeamMemberInvite)
admin.site.register(UserPaymentMethod)
admin.site.register(UserLogDevice)
