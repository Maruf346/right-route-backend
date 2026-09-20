from rest_framework import serializers


class MetricCardSerializer(serializers.Serializer):
    value = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_value = serializers.CharField()
    percentage_change = serializers.FloatField()
    formatted_change = serializers.CharField()
    comparison_text = serializers.CharField()
    is_positive = serializers.BooleanField()


class RevenueMixItemSerializer(serializers.Serializer):
    customer_type = serializers.CharField()
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_revenue = serializers.CharField()
    percentage = serializers.FloatField()


class RevenueMixSerializer(serializers.Serializer):
    center_arr = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_arr = serializers.CharField()
    total_mrr = serializers.DecimalField(max_digits=14, decimal_places=2)
    items = RevenueMixItemSerializer(many=True)


class RevenueByPlanItemSerializer(serializers.Serializer):
    plan_name = serializers.CharField()
    mrr = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_mrr = serializers.CharField()
    percentage = serializers.FloatField()


class PlanPerformanceRowSerializer(serializers.Serializer):
    plan = serializers.CharField()
    active_accounts = serializers.IntegerField()
    drivers_or_seats = serializers.IntegerField()
    mrr = serializers.DecimalField(max_digits=14, decimal_places=2)
    formatted_mrr = serializers.CharField()
    churn_rate = serializers.FloatField()
    formatted_churn_rate = serializers.CharField()


class PlanPerformanceTableSerializer(serializers.Serializer):
    rows = PlanPerformanceRowSerializer(many=True)
    total = PlanPerformanceRowSerializer()


class QuarterOptionSerializer(serializers.Serializer):
    key = serializers.CharField()
    year = serializers.IntegerField()
    quarter = serializers.IntegerField()
    label = serializers.CharField()
    is_current = serializers.BooleanField()


class YearOptionSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    label = serializers.CharField()
    is_current = serializers.BooleanField()


class TimePeriodOptionsSerializer(serializers.Serializer):
    quarters = QuarterOptionSerializer(many=True)
    years = YearOptionSerializer(many=True)
    default_quarter = serializers.CharField()
    default_year = serializers.IntegerField()


class RevenueMetricsCollectionSerializer(serializers.Serializer):
    active_paying_accounts = MetricCardSerializer()
    mrr = MetricCardSerializer()
    arr = MetricCardSerializer()
    arpa = MetricCardSerializer()
    new_mrr = MetricCardSerializer()
    churned_mrr = MetricCardSerializer()
    total_revenue = MetricCardSerializer()


class RevenueDashboardSerializer(serializers.Serializer):
    tab = serializers.CharField()
    time_period_options = TimePeriodOptionsSerializer()
    metrics = RevenueMetricsCollectionSerializer()
    revenue_mix = RevenueMixSerializer()
    revenue_by_plan = RevenueByPlanItemSerializer(many=True)
    plan_performance = PlanPerformanceTableSerializer()
