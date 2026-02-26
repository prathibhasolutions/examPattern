from django.contrib import admin
from django.utils.html import format_html

from .models import Question, Option
from evaluation.ocr_service import get_ocr_service


class OptionInline(admin.TabularInline):
	model = Option
	extra = 4
	min_num = 2
	fields = ("order", "text", "image", "is_math", "is_correct")
	verbose_name_plural = "Options"


class QuestionInline(admin.TabularInline):
	"""Inline for creating questions within a section."""
	model = Question
	extra = 1
	fields = ("text", "is_math", "is_active")
	verbose_name_plural = "Questions"


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"section",
		"short_text",
		"is_math",
		"has_extracted_text",
		"is_active",
	)
	list_filter = ("section", "section__test", "is_active", "is_math")
	search_fields = ("text", "section__name", "section__test__name")
	ordering = ("section", "id")
	autocomplete_fields = ["section"]
	inlines = [OptionInline]
	save_on_top = True
	actions = ["extract_text_from_image"]
	fieldsets = (
		(None, {"fields": ("section",)}),
		("Content", {"fields": ("text", "is_math", "image", "explanation")}),
		(
			"OCR Extracted Text (editable)",
			{"fields": ("extracted_text",), "classes": ("collapse",), "description": "Text extracted from image via OCR. You can edit this."},
		),
		(
			"Marking (optional - leave blank to use section/test defaults)",
			{"fields": ("marks_override", "negative_marks_override"), "classes": ("collapse",)},
		),
		("Status", {"fields": ("is_active",)}),
		("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
	)
	readonly_fields = ("created_at", "updated_at")

	def short_text(self, obj):  # pragma: no cover
		return (obj.text or "").strip()[:60] + ("…" if len((obj.text or "")) > 60 else "")
	short_text.short_description = "Text"
	
	def has_extracted_text(self, obj):
		"""Show indicator if extracted text exists."""
		if obj.extracted_text:
			return format_html('<span style="color: green;">✓ OCR</span>')
		return format_html('<span style="color: gray;">—</span>')
	has_extracted_text.short_description = "Extracted"
	
	def extract_text_from_image(self, request, queryset):
		"""Admin action to extract text from images using OCR."""
		ocr_service = get_ocr_service()
		
		if not ocr_service.is_available():
			self.message_user(request, "OCR service is not available. Please install Tesseract.", level='error')
			return
		
		count = 0
		for question in queryset.filter(image__isnull=False):
			if question.image:
				try:
					image_path = question.image.path
					extracted = ocr_service.extract_text(image_path)
					if extracted:
						question.extracted_text = extracted
						question.save(update_fields=['extracted_text'])
						count += 1
				except Exception as e:
					self.message_user(request, f"Error processing question {question.id}: {str(e)}", level='error')
		
		self.message_user(request, f"Successfully extracted text from {count} question(s).")
	extract_text_from_image.short_description = "Extract text from image(s) using OCR"


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
	list_display = ("id", "question", "order", "is_correct", "is_math")
	list_filter = ("is_correct", "is_math", "question__section", "question__section__test")
	search_fields = ("question__text",)
	ordering = ("question", "order")
	raw_id_fields = ["question"]
