from django.db import models

from attempts.models import TestAttempt


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

	def __str__(self) -> str:  # pragma: no cover
		return f"Evaluation for Attempt {self.attempt_id}"
