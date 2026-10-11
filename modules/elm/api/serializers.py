from rest_framework import serializers

from modules.elm.models import LeaveApplication, LeaveCalendar, LeaveCalendarDate, LeaveHierarchy, LeavePolicy


class LeaveApplicationInputSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=[("CL", "CL"), ("RH", "RH"), ("SCL", "SCL"),
                                               ("EL", "EL"), ("COL", "COL"), ("VL", "VL")])
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    cl_half = serializers.ChoiceField(choices=[("none", "Full day"), ("first", "First half"), ("second", "Second half")], required=False, default="none")
    purpose = serializers.CharField(max_length=1000)
    station_leave = serializers.BooleanField(required=False, default=False)
    station_leave_details = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    requires_substitute = serializers.BooleanField(required=False, default=False)
    substitute_user_id = serializers.IntegerField(required=False, allow_null=True)
    evidence_reference = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError({"end_date": "End date must not precede start date."})
        if attrs.get("station_leave") and not attrs.get("station_leave_details", "").strip():
            raise serializers.ValidationError({"station_leave_details": "Explain the Station Leave requirement."})
        if attrs.get("cl_half") != "none" and (attrs["category"] != "CL" or attrs["start_date"] != attrs["end_date"]):
            raise serializers.ValidationError({"cl_half": "Half-day selection is valid only for one-date CL."})
        if attrs.get("requires_substitute") and not attrs.get("substitute_user_id"):
            raise serializers.ValidationError({"substitute_user_id": "Select an eligible substitute."})
        return attrs


class LeaveApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveApplication
        fields = ("id", "applicant_user_id", "employee_kind", "department", "request_type",
                  "parent_application", "category", "start_date", "end_date", "cl_half",
                  "requested_days", "purpose", "station_leave", "station_leave_details",
                  "requires_substitute", "substitute_user_id", "substitute_response", "status",
                  "current_assignee_user_id", "unit_head_recommendation", "final_decision",
                  "final_decision_note", "action_reason", "actual_resumption_date", "evidence_reference",
                  "created_at", "updated_at")
        read_only_fields = fields


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject"),
                                               ("recommended", "Recommended"),
                                               ("not_recommended", "Not recommended"),
                                               ("route", "Route"), ("review", "Review")])
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class SubstituteResponseSerializer(serializers.Serializer):
    response = serializers.ChoiceField(choices=[("accept", "Accept"), ("decline", "Decline")])


class ActionReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ExtensionSerializer(ActionReasonSerializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    substitute_user_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError({"end_date": "End date must not precede start date."})
        return attrs


class ResumptionSerializer(serializers.Serializer):
    actual_resumption_date = serializers.DateField()
    details = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LeavePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicy
        fields = ("id", "category", "annual_entitlement", "employee_scope", "carry_forward",
                  "continuous_counting", "medical_evidence_required", "enabled", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class LeaveCalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveCalendar
        fields = ("id", "name", "year", "status", "created_by_user_id", "published_by_user_id", "published_at")
        read_only_fields = ("id", "status", "created_by_user_id", "published_by_user_id", "published_at")


class LeaveCalendarDateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveCalendarDate
        fields = ("id", "calendar", "day", "name", "is_restricted_holiday", "is_closed_day")


class LeaveHierarchySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveHierarchy
        fields = ("id", "unit_key", "unit_head_user_id", "establishment_user_id",
                  "sanctioning_authority_user_id", "director_user_id", "active")
        read_only_fields = ("id",)
