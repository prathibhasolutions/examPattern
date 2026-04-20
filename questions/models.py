from django.db import models
from django.core.exceptions import ValidationError


class Question(models.Model):
	# Link a question to a specific section of a test
	section = models.ForeignKey(
		'testseries.Section', on_delete=models.CASCADE, related_name='questions'
	)

	# Content
	text = models.TextField(blank=True, help_text="Question text - Supports LaTeX markup (optional if image provided)")
	image = models.ImageField(
		upload_to='questions/images/', null=True, blank=True
	)
	extracted_text = models.TextField(
		blank=True, null=True,
		help_text="Text extracted from image via OCR. Admin can edit this."
	)
	is_math = models.BooleanField(
		default=False, help_text="If true, render text as LaTeX"
	)
	explanation = models.TextField(blank=True)
	solution_image = models.ImageField(
		upload_to='questions/solutions/', null=True, blank=True,
		help_text="Solution diagram or working steps image"
	)

	# Optional per-question marking overrides
	marks_override = models.DecimalField(
		max_digits=6, decimal_places=2, null=True, blank=True
	)
	negative_marks_override = models.DecimalField(
		max_digits=6, decimal_places=2, null=True, blank=True
	)
	is_bonus = models.BooleanField(
		default=False,
		help_text="If True, all students get full marks regardless of their answer"
	)

	# Cached list of correct Option PKs — populated at publish time so evaluation
	# needs zero extra DB queries to know the answer (pure Python set comparison).
	correct_option_ids = models.JSONField(
		default=list,
		blank=True,
		help_text="Auto-populated on publish. Do not edit manually.",
	)

	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	# Tracks which QuestionDraft this was created from (used for in-place re-publish)
	draft_question_id = models.IntegerField(null=True, blank=True, db_index=True)

	def clean(self):
		"""Validate that question has at least text or image"""
		super().clean()
		if not self.text and not self.image:
			raise ValidationError(
				'Question must have either text or an image (or both).'
			)

	class Meta:
		ordering = ["section", "id"]
		indexes = [
			models.Index(fields=["section"]),
			models.Index(fields=["is_active"]),
			models.Index(fields=["created_at"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"Q{self.pk} in {self.section.name}"


class Option(models.Model):
	question = models.ForeignKey(
		Question, on_delete=models.CASCADE, related_name='options'
	)
	text = models.TextField(blank=True)
	image = models.ImageField(
		upload_to='questions/options/', null=True, blank=True
	)
	is_math = models.BooleanField(default=False)
	is_correct = models.BooleanField(default=False)
	order = models.PositiveSmallIntegerField(default=1)
	# Tracks which OptionDraft this was created from (used for in-place re-publish)
	draft_option_id = models.IntegerField(null=True, blank=True, db_index=True)

	def clean(self):
		"""Validate that option has at least text or image"""
		super().clean()
		if not self.text and not self.image:
			raise ValidationError(
				'Option must have either text or an image (or both).'
			)

	class Meta:
		ordering = ["question", "order", "id"]
		constraints = [
			models.UniqueConstraint(
				fields=["question", "order"], name="uq_option_order_within_question"
			)
		]
		indexes = [
			models.Index(fields=["question", "is_correct"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"Option {self.order} for Q{self.question_id}"
	def get_option_label(self):
		"""Convert option order to letter label (A, B, C, D, etc.)"""
		return chr(64 + self.order)  # A=65, B=66, etc.