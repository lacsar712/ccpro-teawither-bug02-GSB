from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    UpdateView,
)

from .forms import GardenForm, TroughForm, WitherBatchForm
from .models import Garden, Trough, WitherBatch


def _wants_htmx(request):
    return request.headers.get("HX-Request") == "true"


@login_required
def home(request):
    context = {
        "garden_count": Garden.objects.count(),
        "trough_count": Trough.objects.count(),
        "batch_count": WitherBatch.objects.count(),
        "ready_count": Trough.objects.filter(status=Trough.STATUS_READY).count(),
        "withering_count": Trough.objects.filter(
            status=Trough.STATUS_WITHERING
        ).count(),
        "loading_count": Trough.objects.filter(
            status=Trough.STATUS_LOADING
        ).count(),
    }
    return render(request, "home.html", context)


# ---- Garden ----


class GardenListView(LoginRequiredMixin, ListView):
    model = Garden
    template_name = "gardens/list.html"
    context_object_name = "gardens"

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if _wants_htmx(request):
            html = render_to_string(
                "gardens/_table.html",
                {"gardens": self.object_list},
                request=request,
            )
            return HttpResponse(html)
        return super().get(request, *args, **kwargs)


class GardenCreateView(LoginRequiredMixin, CreateView):
    model = Garden
    form_class = GardenForm
    template_name = "gardens/form.html"
    success_url = reverse_lazy("garden_list")

    def form_valid(self, form):
        messages.success(self.request, "茶园已创建")
        response = super().form_valid(form)
        if _wants_htmx(self.request):
            return redirect("garden_list")
        return response


class GardenUpdateView(LoginRequiredMixin, UpdateView):
    model = Garden
    form_class = GardenForm
    template_name = "gardens/form.html"
    success_url = reverse_lazy("garden_list")

    def form_valid(self, form):
        messages.success(self.request, "茶园已更新")
        return super().form_valid(form)


class GardenDeleteView(LoginRequiredMixin, DeleteView):
    model = Garden
    template_name = "gardens/confirm_delete.html"
    success_url = reverse_lazy("garden_list")

    def form_valid(self, form):
        messages.success(self.request, "茶园已删除")
        return super().form_valid(form)


# ---- Trough ----


class TroughListView(LoginRequiredMixin, ListView):
    model = Trough
    template_name = "troughs/list.html"
    context_object_name = "troughs"

    def get_queryset(self):
        # 行数即 Trough.objects 计数，与首页 trough_count 同源，可直接对账。
        return Trough.objects.select_related("garden").all()

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if _wants_htmx(request):
            html = render_to_string(
                "troughs/_table.html",
                {"troughs": self.object_list},
                request=request,
            )
            return HttpResponse(html)
        return super().get(request, *args, **kwargs)


def _is_unique_violation(exc):
    """判断异常是否为 (茶园, 槽位编号) 唯一性冲突。

    UniqueConstraint 经模型 validate_constraints 报出时，code 为
    unique_together 且可能嵌在 error_dict['__all__'] 内，需递归检查。
    """
    if isinstance(exc, IntegrityError):
        return True

    def walk(error):
        if getattr(error, "code", None) in ("unique_together", "unique"):
            return True
        for sub in getattr(error, "error_list", []) or []:
            if walk(sub):
                return True
        for subs in (getattr(error, "error_dict", None) or {}).values():
            for sub in subs:
                if walk(sub):
                    return True
        return False

    return isinstance(exc, ValidationError) and walk(exc)


def _conflict_form(form):
    """并发同园同号落库失败后，把错误回填到槽位编号字段。"""
    form.add_error(
        "troughCode",
        "该茶园已存在相同槽位编号（可能刚被他人创建或占用），请刷新列表后更换编号。",
    )


class TroughCreateView(LoginRequiredMixin, CreateView):
    model = Trough
    form_class = TroughForm
    template_name = "troughs/form.html"
    success_url = reverse_lazy("trough_list")

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except (IntegrityError, ValidationError) as exc:
            # 两人同时提交同园同号：表单查重双双通过后，模型层 full_clean 与
            # 数据库唯一约束共同兜底，至多一笔入库；落后的一笔回到表单提示冲突。
            if not _is_unique_violation(exc):
                raise
            _conflict_form(form)
            return self.form_invalid(form)
        messages.success(self.request, "萎凋槽已创建")
        if _wants_htmx(self.request):
            return redirect("trough_list")
        return response


class TroughUpdateView(LoginRequiredMixin, UpdateView):
    model = Trough
    form_class = TroughForm
    template_name = "troughs/form.html"
    success_url = reverse_lazy("trough_list")

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except (IntegrityError, ValidationError) as exc:
            # 更新成已有编号：表单查重排除自身后拦截，竞态漏网时由模型/约束兜底。
            if not _is_unique_violation(exc):
                raise
            _conflict_form(form)
            return self.form_invalid(form)
        messages.success(self.request, "萎凋槽已更新")
        if _wants_htmx(self.request):
            return redirect("trough_list")
        return response


class TroughDeleteView(LoginRequiredMixin, DeleteView):
    model = Trough
    template_name = "troughs/confirm_delete.html"
    success_url = reverse_lazy("trough_list")

    def form_valid(self, form):
        messages.success(self.request, "萎凋槽已删除")
        return super().form_valid(form)


# ---- WitherBatch ----


class BatchListView(LoginRequiredMixin, ListView):
    model = WitherBatch
    template_name = "batches/list.html"
    context_object_name = "batches"

    def get_queryset(self):
        return WitherBatch.objects.select_related("trough", "trough__garden").all()

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if _wants_htmx(request):
            html = render_to_string(
                "batches/_table.html",
                {"batches": self.object_list},
                request=request,
            )
            return HttpResponse(html)
        return super().get(request, *args, **kwargs)


class BatchCreateView(LoginRequiredMixin, CreateView):
    model = WitherBatch
    form_class = WitherBatchForm
    template_name = "batches/form.html"
    success_url = reverse_lazy("batch_list")

    def form_valid(self, form):
        messages.success(self.request, "萎凋批次已创建")
        return super().form_valid(form)


class BatchUpdateView(LoginRequiredMixin, UpdateView):
    model = WitherBatch
    form_class = WitherBatchForm
    template_name = "batches/form.html"
    success_url = reverse_lazy("batch_list")

    def form_valid(self, form):
        messages.success(self.request, "萎凋批次已更新")
        return super().form_valid(form)


class BatchDeleteView(LoginRequiredMixin, DeleteView):
    model = WitherBatch
    template_name = "batches/confirm_delete.html"
    success_url = reverse_lazy("batch_list")

    def form_valid(self, form):
        messages.success(self.request, "萎凋批次已删除")
        return super().form_valid(form)
