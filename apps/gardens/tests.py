from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .forms import TroughForm
from .models import Garden, Trough


class TroughUniqueConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g1 = Garden.objects.create(name="一号园", altitudeBand="800m")
        cls.g2 = Garden.objects.create(name="二号园", altitudeBand="600m")

    def test_same_garden_same_code_rejected_at_db(self):
        # bulk_create 绕过模型 save/full_clean，直连数据库约束
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Trough.objects.bulk_create(
                    [
                        Trough(
                            garden=self.g1,
                            troughCode="A-01",
                            cultivar="福鼎大白",
                            loadKg=Decimal("100.00"),
                        ),
                        Trough(
                            garden=self.g1,
                            troughCode="A-01",
                            cultivar="铁观音",
                            loadKg=Decimal("90.00"),
                        ),
                    ]
                )
        dupes = Trough.objects.filter(garden=self.g1, troughCode="A-01")
        self.assertLessEqual(dupes.count(), 1)
        self.assertEqual(
            dupes.count(),
            dupes.values("garden", "troughCode").distinct().count(),
        )

    def test_same_code_different_garden_allowed(self):
        Trough.objects.create(
            garden=self.g1,
            troughCode="A-01",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
        )
        t2 = Trough.objects.create(
            garden=self.g2,
            troughCode="A-01",
            cultivar="黄金芽",
            loadKg=Decimal("80.00"),
        )
        self.assertEqual(Trough.objects.count(), 2)
        self.assertTrue(Trough.objects.filter(pk=t2.pk).exists())


class TroughFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g1 = Garden.objects.create(name="一号园", altitudeBand="800m")
        cls.g2 = Garden.objects.create(name="二号园", altitudeBand="600m")
        cls.t1 = Trough.objects.create(
            garden=cls.g1,
            troughCode="A-01",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
        )
        cls.t2 = Trough.objects.create(
            garden=cls.g2,
            troughCode="B-01",
            cultivar="黄金芽",
            loadKg=Decimal("80.00"),
        )

    def _data(self, garden, code, pk=None):
        return {
            "garden": garden.pk,
            "troughCode": code,
            "cultivar": "福鼎大白",
            "loadKg": "100.00",
            "status": Trough.STATUS_LOADING,
        }

    def test_create_duplicate_code_invalid(self):
        form = TroughForm(data=self._data(self.g1, "A-01"))
        self.assertFalse(form.is_valid())
        self.assertIn("troughCode", form.errors)

    def test_create_same_code_other_garden_valid(self):
        form = TroughForm(data=self._data(self.g2, "A-01"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_update_to_existing_code_invalid(self):
        # 把 B-01 更新成二号园已不存在的号可以，但更新成 A-01（一号园已有）不行：
        form = TroughForm(
            data=self._data(self.g1, "A-01"), instance=self.t2
        )
        # t2 原本属于 g2，改园又改号到已被占用组合
        self.assertFalse(form.is_valid())
        self.assertIn("troughCode", form.errors)

    def test_update_same_garden_collision_invalid(self):
        other = Trough.objects.create(
            garden=self.g1,
            troughCode="A-02",
            cultivar="铁观音",
            loadKg=Decimal("70.00"),
        )
        form = TroughForm(
            data=self._data(self.g1, "A-01"), instance=other
        )
        self.assertFalse(form.is_valid())
        self.assertIn("troughCode", form.errors)

    def test_update_keeping_own_code_valid(self):
        form = TroughForm(
            data=self._data(self.g1, "A-01"), instance=self.t1
        )
        self.assertTrue(form.is_valid(), form.errors)


class TroughViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="witherer", password="123456"
        )
        cls.g1 = Garden.objects.create(name="一号园", altitudeBand="800m")
        cls.g2 = Garden.objects.create(name="二号园", altitudeBand="600m")
        cls.t1 = Trough.objects.create(
            garden=cls.g1,
            troughCode="A-01",
            cultivar="福鼎大白",
            loadKg=Decimal("100.00"),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _post_data(self, code="A-01", garden=None):
        return {
            "garden": (garden or self.g1).pk,
            "troughCode": code,
            "cultivar": "福鼎大白",
            "loadKg": "100.00",
            "status": Trough.STATUS_LOADING,
        }

    def test_create_duplicate_rejected_stays_on_form(self):
        before = Trough.objects.count()
        resp = self.client.post(reverse("trough_create"), self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已存在槽位编号")
        self.assertEqual(Trough.objects.count(), before)

    def test_concurrent_two_new_codes_at_most_one(self):
        """两人同时新建全新同号：第一笔入库；第二笔表单查重漏网后，
        模型 full_clean 的唯一约束校验兜底拒绝。"""
        before = Trough.objects.count()

        resp1 = self.client.post(
            reverse("trough_create"), self._post_data("A-07")
        )
        self.assertEqual(resp1.status_code, 302)

        # 模拟第二笔请求的表单层查重发生在第一笔提交之前（竞态窗口）
        with patch.object(
            TroughForm,
            "clean_troughCode",
            lambda self: self.cleaned_data.get("troughCode"),
        ):
            resp2 = self.client.post(
                reverse("trough_create"), self._post_data("A-07")
            )
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "相同槽位编号")
        self.assertEqual(
            Trough.objects.filter(garden=self.g1, troughCode="A-07").count(), 1
        )
        self.assertEqual(Trough.objects.count(), before + 1)

    def test_create_db_integrity_error_fallback(self):
        """连模型层校验也漏网时（极端竞态），数据库唯一约束仍须拒绝且页面不崩。"""
        before = Trough.objects.count()
        with (
            patch.object(
                TroughForm,
                "clean_troughCode",
                lambda self: self.cleaned_data.get("troughCode"),
            ),
            patch.object(
                Trough, "validate_constraints", lambda self, exclude=None: None
            ),
        ):
            resp = self.client.post(
                reverse("trough_create"), self._post_data("A-01")
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "相同槽位编号")
        self.assertEqual(Trough.objects.count(), before)

    def test_update_collision_rejected(self):
        other = Trough.objects.create(
            garden=self.g1,
            troughCode="A-02",
            cultivar="铁观音",
            loadKg=Decimal("70.00"),
        )
        before_code = other.troughCode
        resp = self.client.post(
            reverse("trough_edit", args=[other.pk]),
            self._post_data("A-01"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已存在槽位编号")
        other.refresh_from_db()
        self.assertEqual(other.troughCode, before_code)

    def test_update_concurrent_collision_rejected(self):
        """更新竞态：表单查重漏网时，模型/DB 层仍须拒绝且不登出用户。"""
        other = Trough.objects.create(
            garden=self.g1,
            troughCode="A-02",
            cultivar="铁观音",
            loadKg=Decimal("70.00"),
        )
        with patch.object(
            TroughForm,
            "clean_troughCode",
            lambda self: self.cleaned_data.get("troughCode"),
        ):
            resp = self.client.post(
                reverse("trough_edit", args=[other.pk]),
                self._post_data("A-01"),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "相同槽位编号")
        other.refresh_from_db()
        self.assertEqual(other.troughCode, "A-02")
        # 会话未被破坏：失败后仍可访问需登录页面
        home = self.client.get(reverse("home"))
        self.assertEqual(home.status_code, 200)

    def test_update_db_integrity_error_fallback(self):
        """更新路径极端竞态直撞数据库约束：拒绝、留原号、页面可重开。"""
        other = Trough.objects.create(
            garden=self.g1,
            troughCode="A-02",
            cultivar="铁观音",
            loadKg=Decimal("70.00"),
        )
        with (
            patch.object(
                TroughForm,
                "clean_troughCode",
                lambda self: self.cleaned_data.get("troughCode"),
            ),
            patch.object(
                Trough, "validate_constraints", lambda self, exclude=None: None
            ),
        ):
            resp = self.client.post(
                reverse("trough_edit", args=[other.pk]),
                self._post_data("A-01"),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "相同槽位编号")
        other.refresh_from_db()
        self.assertEqual(other.troughCode, "A-02")

    def test_list_opens_after_failed_save_and_counts_reconcile(self):
        """保存失败之后列表必须能打开，行数与首页槽数对得上。"""
        resp_fail = self.client.post(
            reverse("trough_create"), self._post_data("A-01")
        )
        self.assertEqual(resp_fail.status_code, 200)

        resp_list = self.client.get(reverse("trough_list"))
        self.assertEqual(resp_list.status_code, 200)
        self.assertEqual(len(resp_list.context["troughs"]), Trough.objects.count())

        resp_home = self.client.get(reverse("home"))
        self.assertEqual(resp_home.status_code, 200)
        self.assertEqual(
            resp_home.context["trough_count"], Trough.objects.count()
        )
        self.assertEqual(
            resp_home.context["trough_count"],
            len(resp_list.context["troughs"]),
        )

    def test_htmx_list_refresh_after_failure(self):
        self.client.post(
            reverse("trough_create"), self._post_data("A-01"),
            HTTP_HX_REQUEST="true",
        )
        resp = self.client.get(
            reverse("trough_list"), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.content.decode().count("<tr>") - 1,  # 去掉表头行
            Trough.objects.count(),
        )
