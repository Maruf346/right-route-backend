from rest_framework import serializers
from finance.models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    created_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id",
            "vendor_company",
            "date_paid",
            "amount",
            "amount_display",
            "who_paid",
            "payment_method",
            "recurring",
            "description",
            "created_by",
            "created_by_email",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "amount_display",
            "created_by",
            "created_by_email",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def get_amount_display(self, obj):
        return f"${obj.amount:,.2f}"

    def get_created_by_email(self, obj):
        return obj.created_by.email if obj.created_by else None

    def create(self, validated_data):
        user = self.context.get("request").user if self.context.get("request") else None
        validated_data["created_by"] = user
        validated_data["updated_by"] = user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        user = self.context.get("request").user if self.context.get("request") else None
        validated_data["updated_by"] = user
        return super().update(instance, validated_data)


class FinanceSummarySerializer(serializers.Serializer):
    period = serializers.CharField()
    target_date = serializers.DateField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    formatted_label = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_total = serializers.CharField()
    display_bar_text = serializers.CharField()


class FleetPaymentItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    company_name = serializers.CharField()
    owner_email = serializers.EmailField()
    plan_name = serializers.CharField()
    driver_limit = serializers.IntegerField()
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2)
    formatted_amount = serializers.CharField()
    due_date = serializers.DateField(allow_null=True)
    status = serializers.CharField()
    user_account_id = serializers.IntegerField(allow_null=True)
