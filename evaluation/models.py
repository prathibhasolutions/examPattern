from django.db import models

from attempts.models import TestAttempt
from testseries.models import Section


class EvaluationJob(models.Model):
	STATUS_PENDING = 'pending'
	STATUS_RUNNING = 'running'
	STATUS_SUCCESS = 'success'
	STATUS_FAILED = 'failed'
	STATUS_CHOICES = [
		(STATUS_PENDING, 'Pending'),
		(STATUS_RUNNING, 'Running'),
		(STATUS_SUCCESS, 'Success'),
		(STATUS_FAILED, 'Failed'),
	]

	attempt = models.ForeignKey(
		TestAttempt, on_delete=models.CASCADE, related_name='evaluation_jobs'
	)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
	queued_at = models.DateTimeField(auto_now_add=True)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)
	retry_count = models.PositiveIntegerField(default=0)
	worker_backend = models.CharField(max_length=20, blank=True, default='')
	error_message = models.TextField(blank=True, default='')

	class Meta:
		ordering = ['-queued_at']
		indexes = [
			models.Index(fields=['attempt', 'status']),
			models.Index(fields=['status', 'queued_at']),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"EvaluationJob(attempt={self.attempt_id}, status={self.status})"


class EvaluationResult(models.Model):
	attempt = models.OneToOneField(
		TestAttempt, on_delete=models.CASCADE, related_name='evaluation'
	)

	total_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
	section_scores = models.JSONField(default=dict, blank=True)

	rank = models.PositiveIntegerField(null=True, blank=True)
	percentile = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

	evaluated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-evaluated_at']
		indexes = [
			models.Index(fields=['total_score']),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"Evaluation for Attempt {self.attempt_id}"


class EvaluationSectionResult(models.Model):
	evaluation_result = models.ForeignKey(
		EvaluationResult, on_delete=models.CASCADE, related_name='section_results'
	)
	section = models.ForeignKey(
		Section, on_delete=models.CASCADE, related_name='evaluation_section_results'
	)
	score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
	correct_count = models.PositiveIntegerField(default=0)
	incorrect_count = models.PositiveIntegerField(default=0)
	unanswered_count = models.PositiveIntegerField(default=0)
	subjective_count = models.PositiveIntegerField(default=0)
	bonus_count = models.PositiveIntegerField(default=0)
	total_questions = models.PositiveIntegerField(default=0)

	class Meta:
		ordering = ['evaluation_result_id', 'section_id']
		constraints = [
			models.UniqueConstraint(
				fields=['evaluation_result', 'section'],
				name='uq_eval_section_result_per_section',
			)
		]
		indexes = [
			models.Index(fields=['evaluation_result']),
			models.Index(fields=['section']),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"SectionResult(eval={self.evaluation_result_id}, section={self.section_id})"
