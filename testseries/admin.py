from django.contrib import admin
from django.utils.html import format_html

from .models import TestSeries, Test, Section
from questions.admin import QuestionInline


@admin.register(TestSeries)
class TestSeriesAdmin(admin.ModelAdmin):
	list_display = ("name", "slug", "is_active", "test_count", "created_at")
	search_fields = ("name", "slug")
	list_filter = ("is_active",)
	prepopulated_fields = {"slug": ("name",)}
	ordering = ("name",)
	fieldsets = (
		(None, {"fields": ("name", "slug", "description")}),
		("Status", {"fields": ("is_active",)}),
		("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
	)
	readonly_fields = ("created_at", "updated_at")
	save_on_top = True
	
	def save_model(self, request, obj, form, change):
		"""Override save to check for duplicate names"""
		from django.contrib import messages
		
		if not change:  # Only for new objects
			existing = TestSeries.objects.filter(name__iexact=obj.name).first()
			if existing:
				messages.error(request, f"A test series with the name '{obj.name}' already exists. Please choose a different name.")
				return
		else:  # For updates, check if name changed
			original = TestSeries.objects.get(pk=obj.pk)
			if original.name.lower() != obj.name.lower():
				existing = TestSeries.objects.filter(name__iexact=obj.name).exclude(pk=obj.pk).first()
				if existing:
					messages.error(request, f"A test series with the name '{obj.name}' already exists. Please choose a different name.")
					return
		
		super().save_model(request, obj, form, change)
	
	def test_count(self, obj):
		"""Show number of tests in this series."""
		count = obj.tests.count()
		return format_html('<span style="color: #666;">{} test{}</span>', count, 's' if count != 1 else '')
	test_count.short_description = "Tests"


class SectionInline(admin.TabularInline):
	model = Section
	extra = 1
	fields = (
		"name",
		"order",
		"time_limit_seconds",
		"marks_per_question",
		"negative_marks_per_question",
	)


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
	list_display = ("name", "series", "duration_seconds", "is_active", "created_at")
	search_fields = ("name", "series__name")
	list_filter = ("is_active", "series")
	prepopulated_fields = {"slug": ("name",)}
	ordering = ("-created_at",)
	inlines = [SectionInline]
	fieldsets = (
		(None, {"fields": ("series", "name", "slug", "description")}),
		(
			"Test Settings",
			{
				"fields": (
					"duration_seconds",
					"marks_per_question",
					"negative_marks_per_question",
				)
			},
		),
		("Status", {"fields": ("is_active",)}),
		(
			"Timestamps",
			{"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
		),
	)
	readonly_fields = ("created_at", "updated_at")
	save_on_top = True

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.select_related("series")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
	list_display = (
		"name",
		"test",
		"order",
		"time_limit_seconds",
		"marks_per_question",
		"negative_marks_per_question",
	)
	search_fields = ("name", "test__name")
	list_filter = ("test",)
	ordering = ("test", "order")
	inlines = [QuestionInline]
	fields = (
		"test",
		"name",
		"order",
		"time_limit_seconds",
		"marks_per_question",
		"negative_marks_per_question",
	)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.select_related("test")
