from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from fusion_auth.permissions import HasModuleGrant, HasPermission
from modules.elm.api.serializers import (
    ActionReasonSerializer, DecisionSerializer, ExtensionSerializer,
    LeaveApplicationInputSerializer, LeaveApplicationSerializer,
    LeaveCalendarDateSerializer, LeaveCalendarSerializer,
    LeaveHierarchySerializer, LeavePolicySerializer, ResumptionSerializer,
    SubstituteResponseSerializer,
)
from modules.elm.models import (
    LeaveApplication, LeaveBalance, LeaveCalendar, LeaveCalendarDate,
    LeaveHierarchy, LeaveLedgerEntry, LeaveNotice, LeavePolicy, LeaveSLAConfig,
    LeaveYearEndRun,
)
from modules.elm.services import (
    _balance, _employee_kind, _notify, _record, _transition,
    create_cancellation, create_extension, create_leave_application,
    create_resumption, decide_request, post_application_balance,
    process_sla_thresholds, process_year_end, respond_substitute,
    withdraw_request,
)

MODULE = HasModuleGrant("elm")
P_VIEW_SELF = "elm.leave.view_self"
P_VIEW_ALL = "elm.leave.view_all"
P_CREATE = "elm.leave.create"
P_SUBSTITUTE = "elm.leave.substitute"
P_REVIEW = "elm.leave.review"
P_SANCTION = "elm.leave.sanction"
P_MANAGE = "elm.leave.manage"
P_EXPORT = "elm.leave.export"


def _actor(request):
    return request.principal


def _accessible(app, actor):
    return (app.applicant_user_id == actor.user_id
            or app.current_assignee_user_id == actor.user_id
            or actor.has_permission(P_VIEW_ALL)
            or actor.has_permission(P_MANAGE))


class LeaveRequestListCreateView(APIView):
    def get_permissions(self):
        codes = (P_CREATE,) if self.request.method == "POST" else (P_VIEW_SELF, P_VIEW_ALL, P_REVIEW, P_SANCTION, P_SUBSTITUTE, P_MANAGE)
        return [MODULE(), HasPermission(*codes)()]

    def get(self, request):
        actor = _actor(request)
        qs = LeaveApplication.objects.all()
        if actor.has_permission(P_VIEW_ALL) or actor.has_permission(P_MANAGE):
            pass
        elif actor.has_permission(P_REVIEW) or actor.has_permission(P_SANCTION) or actor.has_permission(P_SUBSTITUTE):
            qs = qs.filter(Q(applicant_user_id=actor.user_id) | Q(current_assignee_user_id=actor.user_id) | Q(substitute_user_id=actor.user_id))
        else:
            qs = qs.filter(applicant_user_id=actor.user_id)
        status_filter = request.query_params.get("status")
        category_filter = request.query_params.get("category")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if category_filter:
            qs = qs.filter(category=category_filter)
        data = LeaveApplicationSerializer(qs[:200], many=True).data
        return Response({"results": data, "next": None})

    def post(self, request):
        payload = LeaveApplicationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        app = create_leave_application(_actor(request), payload.validated_data)
        return Response(LeaveApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


class LeaveRequestDetailView(APIView):
    permission_classes = [MODULE, HasPermission(P_VIEW_SELF, P_VIEW_ALL, P_REVIEW, P_SANCTION, P_MANAGE)]

    def get(self, request, pk):
        app = get_object_or_404(LeaveApplication, pk=pk)
        if not _accessible(app, _actor(request)):
            raise PermissionDenied("You cannot view this leave request.")
        return Response(LeaveApplicationSerializer(app).data)


class SubstituteResponseView(APIView):
    permission_classes = [MODULE, HasPermission(P_SUBSTITUTE)]

    def post(self, request, pk):
        payload = SubstituteResponseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        app = get_object_or_404(LeaveApplication, pk=pk)
        return Response(LeaveApplicationSerializer(respond_substitute(_actor(request), app, payload.validated_data["response"])).data)


class LeaveDecisionView(APIView):
    permission_classes = [MODULE, HasPermission(P_REVIEW, P_SANCTION, P_MANAGE)]

    def post(self, request, pk):
        payload = DecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        app = get_object_or_404(LeaveApplication, pk=pk)
        actor = _actor(request)
        if app.status in {"awaiting_unit_head", "awaiting_establishment"} and not (actor.has_permission(P_REVIEW) or actor.has_permission(P_MANAGE)):
            raise PermissionDenied("This action requires ELM review permission.")
        if app.status in {"awaiting_sanction", "awaiting_cancellation_sanction", "awaiting_resumption_review"} and not (actor.has_permission(P_SANCTION) or actor.has_permission(P_MANAGE)):
            raise PermissionDenied("This action requires ELM sanction permission.")
        return Response(LeaveApplicationSerializer(decide_request(
            actor, app, payload.validated_data["decision"], payload.validated_data.get("note", ""))).data)


class WithdrawRequestView(APIView):
    permission_classes = [MODULE, HasPermission(P_CREATE)]

    def post(self, request, pk):
        payload = ActionReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        app = get_object_or_404(LeaveApplication, pk=pk)
        return Response(LeaveApplicationSerializer(withdraw_request(_actor(request), app, payload.validated_data["reason"])).data)


class CancelLeaveView(APIView):
    permission_classes = [MODULE, HasPermission(P_CREATE)]

    def post(self, request, pk):
        payload = ActionReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        parent = get_object_or_404(LeaveApplication, pk=pk, request_type__in=("leave", "offline", "extension"))
        return Response(LeaveApplicationSerializer(create_cancellation(_actor(request), parent, payload.validated_data["reason"])).data,
                        status=status.HTTP_201_CREATED)


class ExtendLeaveView(APIView):
    permission_classes = [MODULE, HasPermission(P_CREATE)]

    def post(self, request, pk):
        payload = ExtensionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        parent = get_object_or_404(LeaveApplication, pk=pk, request_type__in=("leave", "extension", "offline"))
        data = payload.validated_data
        return Response(LeaveApplicationSerializer(create_extension(
            _actor(request), parent, data["start_date"], data["end_date"],
            data.get("reason", ""), data.get("substitute_user_id"))).data, status=status.HTTP_201_CREATED)


class ResumptionView(APIView):
    permission_classes = [MODULE, HasPermission(P_CREATE)]

    def post(self, request, pk):
        payload = ResumptionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        parent = get_object_or_404(LeaveApplication, pk=pk, request_type__in=("leave", "extension", "offline"))
        data = payload.validated_data
        return Response(LeaveApplicationSerializer(create_resumption(
            _actor(request), parent, data["actual_resumption_date"], data.get("details", ""))).data,
            status=status.HTTP_201_CREATED)


class LeaveBalanceView(APIView):
    permission_classes = [MODULE, HasPermission(P_VIEW_SELF, P_VIEW_ALL, P_MANAGE)]

    def get(self, request):
        actor = _actor(request)
        requested_user = request.query_params.get("user_id")
        if requested_user and (actor.has_permission(P_VIEW_ALL) or actor.has_permission(P_MANAGE)):
            try:
                user_id = int(requested_user)
            except ValueError as exc:
                raise ValidationError({"user_id": "Must be an integer."}) from exc
            kind = request.query_params.get("employee_kind", "staff")
        else:
            user_id = actor.user_id
            kind = _employee_kind(actor)
        year = int(request.query_params.get("year", timezone.localdate().year))
        rows = []
        for policy in LeavePolicy.objects.filter(enabled=True).order_by("category"):
            balance = _balance(user_id, kind, year, policy.category)
            rows.append({"year": year, "category": policy.category,
                         "entitlement": str(balance.entitlement), "carried_in": str(balance.carried_in),
                         "converted_in": str(balance.converted_in), "consumed": str(balance.consumed),
                         "lapsed": str(balance.lapsed), "converted_out": str(balance.converted_out),
                         "available": str(balance.available)})
        return Response({"results": rows})


class LeaveApplicationExportView(APIView):
    permission_classes = [MODULE, HasPermission(P_EXPORT)]

    def get(self, request, pk):
        app = get_object_or_404(LeaveApplication, pk=pk)
        if app.applicant_user_id != _actor(request).user_id and not _actor(request).has_permission(P_VIEW_ALL):
            raise PermissionDenied("You may export only your own leave application.")
        lines = ["Fusion ERP — Employee Leave Management", f"Request ID: EL-{app.pk}",
                 f"Type: {app.request_type}", f"Employee ID: {app.applicant_user_id}",
                 f"Category: {app.category}", f"Period: {app.start_date} to {app.end_date}",
                 f"Requested days: {app.requested_days}", f"Purpose: {app.purpose}",
                 f"Station Leave: {'Yes' if app.station_leave else 'No'}",
                 f"Status: {app.status}", f"Decision: {app.final_decision or 'Pending'}",
                 f"Decision note: {app.final_decision_note}"]
        return Response("\n".join(lines), content_type="text/plain; charset=utf-8")


class LeavePolicyView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def get(self, request, category=None):
        if category is not None:
            policy = get_object_or_404(LeavePolicy, category=category)
            return Response(LeavePolicySerializer(policy).data)
        return Response(LeavePolicySerializer(LeavePolicy.objects.order_by("category"), many=True).data)

    def patch(self, request, category):
        policy = get_object_or_404(LeavePolicy, category=category)
        payload = LeavePolicySerializer(policy, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        payload.save()
        return Response(payload.data)


class LeaveCalendarView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def get(self, request):
        return Response(LeaveCalendarSerializer(LeaveCalendar.objects.all()[:100], many=True).data)

    def post(self, request):
        payload = LeaveCalendarSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        calendar = payload.save(created_by_user_id=_actor(request).user_id)
        return Response(LeaveCalendarSerializer(calendar).data, status=status.HTTP_201_CREATED)


class LeaveCalendarDateView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def get(self, request, pk):
        get_object_or_404(LeaveCalendar, pk=pk)
        rows = LeaveCalendarDate.objects.filter(calendar_id=pk)
        return Response(LeaveCalendarDateSerializer(rows, many=True).data)

    def post(self, request, pk):
        get_object_or_404(LeaveCalendar, pk=pk, status="draft")
        payload = LeaveCalendarDateSerializer(data={**request.data, "calendar": pk})
        payload.is_valid(raise_exception=True)
        return Response(LeaveCalendarDateSerializer(payload.save()).data, status=status.HTTP_201_CREATED)


class PublishLeaveCalendarView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def post(self, request, pk):
        with transaction.atomic():
            calendar = get_object_or_404(LeaveCalendar.objects.select_for_update(), pk=pk)
            LeaveCalendar.objects.filter(status="published").exclude(pk=calendar.pk).update(status="draft", updated_at=timezone.now())
            calendar.status = "published"
            calendar.published_by_user_id = _actor(request).user_id
            calendar.published_at = timezone.now()
            calendar.save(update_fields=["status", "published_by_user_id", "published_at", "updated_at"])
        return Response(LeaveCalendarSerializer(calendar).data)


class LeaveHierarchyView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def get(self, request):
        return Response(LeaveHierarchySerializer(LeaveHierarchy.objects.all()[:500], many=True).data)

    def post(self, request):
        payload = LeaveHierarchySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row, created = LeaveHierarchy.objects.update_or_create(unit_key=payload.validated_data["unit_key"], defaults=payload.validated_data)
        return Response(LeaveHierarchySerializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class OfflineLeaveRecordView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def post(self, request):
        required = {"applicant_user_id", "employee_kind", "category", "start_date", "end_date", "purpose", "evidence_reference"}
        missing = sorted(required - set(request.data))
        if missing:
            raise ValidationError({key: "This field is required." for key in missing})
        kind = request.data["employee_kind"]
        if kind not in {"faculty", "staff"}:
            raise ValidationError({"employee_kind": "Must be faculty or staff."})
        start = date.fromisoformat(request.data["start_date"])
        end = date.fromisoformat(request.data["end_date"])
        category = request.data["category"]
        if category not in LeavePolicy.CATEGORY_CHOICES.__class__ and category not in {"CL", "RH", "SCL", "EL", "COL", "VL"}:
            raise ValidationError({"category": "Unsupported leave category."})
        days_by_year = {str(y): "1.00" for y in range(start.year, end.year + 1)} if start == end else {}
        if not days_by_year:
            from modules.elm.services import _days_by_year
            days_by_year = _days_by_year(category, start, end)
        total = sum((Decimal(x) for x in days_by_year.values()), Decimal("0"))
        app = LeaveApplication.objects.create(
            applicant_user_id=int(request.data["applicant_user_id"]), employee_kind=kind,
            department=str(request.data.get("department", "")), request_type="offline",
            category=category, start_date=start, end_date=end,
            requested_days=total, requested_days_by_year=days_by_year,
            purpose=str(request.data["purpose"]), status="approved",
            final_decision="approved", final_decided_at=timezone.now(),
            final_decision_note="Recorded from prior offline sanction; no second approval workflow.",
            evidence_reference=str(request.data["evidence_reference"]),
        )
        post_application_balance(app, _actor(request).user_id)
        _record(app, _actor(request).user_id, "offline_synchronized", "offline", "approved", app.evidence_reference)
        return Response(LeaveApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


class LeaveSLAConfigView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def get(self, request):
        config = LeaveSLAConfig.objects.order_by("id").first() or LeaveSLAConfig.objects.create()
        return Response({"reminder_after_hours": config.reminder_after_hours,
                         "escalation_after_hours": config.escalation_after_hours,
                         "escalation_user_id": config.escalation_user_id})

    def put(self, request):
        config = LeaveSLAConfig.objects.order_by("id").first() or LeaveSLAConfig.objects.create()
        reminder = request.data.get("reminder_after_hours", config.reminder_after_hours)
        escalation = request.data.get("escalation_after_hours", config.escalation_after_hours)
        try:
            reminder, escalation = int(reminder), int(escalation)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"thresholds": "SLA thresholds must be integer hours."}) from exc
        if reminder < 1 or escalation <= reminder:
            raise ValidationError({"thresholds": "Escalation threshold must exceed a positive reminder threshold."})
        config.reminder_after_hours = reminder
        config.escalation_after_hours = escalation
        config.escalation_user_id = request.data.get("escalation_user_id") or None
        config.save()
        return Response({"reminder_after_hours": reminder, "escalation_after_hours": escalation,
                         "escalation_user_id": config.escalation_user_id})


class LeaveNoticesView(APIView):
    permission_classes = [MODULE]

    def get(self, request):
        rows = LeaveNotice.objects.filter(user_id=_actor(request).user_id)[:100]
        return Response({"results": [{"id": r.id, "kind": r.kind, "message": r.message,
                                      "application_id": r.application_id, "created_at": r.created_at,
                                      "read_at": r.read_at} for r in rows]})


class LeaveYearEndView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def post(self, request):
        year = request.data.get("year")
        try:
            year = int(year)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"year": "Provide a calendar year."}) from exc
        run = process_year_end(year, _actor(request).user_id)
        return Response({"year": run.year, "processed_accounts": run.processed_accounts,
                         "exceptions": run.exceptions}, status=status.HTTP_201_CREATED)


class ProcessSLAView(APIView):
    permission_classes = [MODULE, HasPermission(P_MANAGE)]

    def post(self, request):
        created = process_sla_thresholds()
        return Response({"events_created": created})
