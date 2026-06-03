import django_filters
from .models import SubscriptionPlan
from core.constants import PlanType, BillingType

class SubscriptionPlanFilterSet(django_filters.FilterSet):
    plan_type = django_filters.CharFilter(method="filter_plan_type")
    billing_type = django_filters.CharFilter(method="filter_billing_type")
    
    class Meta:
        model = SubscriptionPlan
        fields = ["plan_type", "billing_type", "is_active"]
    
    def filter_plan_type(self, queryset, name, value):
        value = value.upper()
        return queryset.filter(
            plan_type=value
        )
    
    def filter_billing_type(self, queryset, name, value):
        value = value.upper()
        return queryset.filter(
            billing_type=value
        )
    

