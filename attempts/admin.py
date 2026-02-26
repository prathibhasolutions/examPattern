from django.contrib import admin

from .models import TestAttempt, Answer


class AnswerInline(admin.TabularInline):
	model = Answer
	extra = 0
	show_change_link = True
	raw_id_fields = ["question"]
	filter_horizontal = ("selected_options",)
	fields = (
		"question",
		"selected_options",
		"response_text",
		"marks_obtained",
		"time_spent_seconds",
	)


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"user",
		"test",
		"attempt_number",
		"status",
		"started_at",
		"submitted_at",
		"score",
	)
	list_filter = ("status", "test", "started_at")
	search_fields = ("user__username", "user__email", "test__name")
	date_hierarchy = "started_at"
	ordering = ("-started_at",)
	raw_id_fields = ["user", "test"]
	list_select_related = ("user", "test")
	inlines = [AnswerInline]
	save_on_top = True
	fieldsets = (
		("Participant & Test", {"fields": ("user", "test", "attempt_number")}),
		(
			"Status & Timing",
			{"fields": ("status", "started_at", "submitted_at", "duration_seconds")},
		),
		("Scoring & Timings", {"fields": ("score", "section_timings")}),
	)
	readonly_fields = ("started_at",)


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"attempt",
		"question",
		"marks_obtained",
		"time_spent_seconds",
	)
	list_filter = ("attempt__test", "attempt__status")
	search_fields = ("question__text", "attempt__user__username", "attempt__user__email")
	raw_id_fields = ["attempt", "question"]
	filter_horizontal = ("selected_options",)
	ordering = ("attempt", "question")
