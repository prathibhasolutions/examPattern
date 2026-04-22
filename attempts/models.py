from django.conf import settings
from django.db import models


class TestAttempt(models.Model):
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='test_attempts'
	)
	test = models.ForeignKey(
		'testseries.Test', on_delete=models.CASCADE, related_name='attempts'
	)

	attempt_number = models.PositiveIntegerField(default=1)

	# Track timings
	started_at = models.DateTimeField(auto_now_add=True)
	submitted_at = models.DateTimeField(null=True, blank=True)

	# Per-section time spent (in seconds) keyed by section id
	# Example: {"12": 450, "13": 300}
	section_timings = models.JSONField(default=dict, blank=True)

	duration_seconds = models.PositiveIntegerField(default=0)
	# Saved timer state for resuming — stores remaining seconds as of last heartbeat
	time_remaining_seconds = models.IntegerField(null=True, blank=True)
	# Shuffled question order per section: {"<section_id>": [q_id, q_id, ...]}
	question_order = models.JSONField(default=dict, blank=True)
	# Shuffled option order per question: {"<question_id>": [opt_id, opt_id, ...]}
	option_order = models.JSONField(default=dict, blank=True)

	STATUS_IN_PROGRESS = 'in_progress'
	STATUS_SUBMITTED = 'submitted'
	STATUS_ABANDONED = 'abandoned'
	STATUS_CHOICES = [
		(STATUS_IN_PROGRESS, 'In Progress'),
		(STATUS_SUBMITTED, 'Submitted'),
		(STATUS_ABANDONED, 'Abandoned'),
	]
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

	EVAL_NOT_STARTED = 'not_started'
	EVAL_PENDING = 'pending'
	EVAL_RUNNING = 'running'
	EVAL_SUCCESS = 'success'
	EVAL_FAILED = 'failed'
	EVALUATION_STATE_CHOICES = [
		(EVAL_NOT_STARTED, 'Not Started'),
		(EVAL_PENDING, 'Pending'),
		(EVAL_RUNNING, 'Running'),
		(EVAL_SUCCESS, 'Success'),
		(EVAL_FAILED, 'Failed'),
	]
	evaluation_state = models.CharField(
		max_length=20,
		choices=EVALUATION_STATE_CHOICES,
		default=EVAL_NOT_STARTED,
	)
	evaluation_started_at = models.DateTimeField(null=True, blank=True)
	evaluation_finished_at = models.DateTimeField(null=True, blank=True)
	evaluation_error = models.TextField(blank=True, default='')

	score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

	class Meta:
		ordering = ["-started_at"]
		constraints = [
			models.UniqueConstraint(
				fields=["user", "test", "attempt_number"],
				name="uq_unique_attempt_number_per_test",
			)
		]
		indexes = [
			models.Index(fields=["test", "status", "attempt_number", "score"]),
			models.Index(fields=["status", "submitted_at"]),
			models.Index(fields=["evaluation_state", "submitted_at"]),
			models.Index(fields=["started_at"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"Attempt {self.attempt_number} — {self.user} — {self.test}"


class Answer(models.Model):
	attempt = models.ForeignKey(
		TestAttempt, on_delete=models.CASCADE, related_name='answers'
	)
	question = models.ForeignKey(
		'questions.Question', on_delete=models.CASCADE, related_name='answers'
	)

	# Track question status
	STATUS_NOT_VISITED = 'not_visited'
	STATUS_VISITED = 'visited'
	STATUS_ANSWERED = 'answered'
	STATUS_MARKED_FOR_REVIEW = 'marked_for_review'
	STATUS_ANSWERED_AND_MARKED = 'answered_and_marked'
	STATUS_CHOICES = [
		(STATUS_NOT_VISITED, 'Not Visited'),
		(STATUS_VISITED, 'Visited'),
		(STATUS_ANSWERED, 'Answered'),
		(STATUS_MARKED_FOR_REVIEW, 'Marked for Review'),
		(STATUS_ANSWERED_AND_MARKED, 'Answered & Marked'),
	]
	status = models.CharField(
		max_length=25, choices=STATUS_CHOICES, default=STATUS_NOT_VISITED
	)

	# For MCQ/MCA: link to chosen options (possibly multiple)
	selected_options = models.ManyToManyField(
		'questions.Option', blank=True, related_name='answers'
	)

	# For text/subjective responses
	response_text = models.TextField(blank=True)

	# Computed during evaluation; stored for efficient reporting
	marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

	# Time spent on this question in seconds
	time_spent_seconds = models.PositiveIntegerField(default=0)

	class Meta:
		ordering = ["attempt_id", "question_id"]
		constraints = [
			models.UniqueConstraint(
				fields=["attempt", "question"], name="uq_one_answer_per_question_per_attempt"
			)
		]
		indexes = []

	def __str__(self) -> str:  # pragma: no cover
		return f"Ans Q{self.question_id} in Attempt {self.attempt_id}"


class AttemptSectionTiming(models.Model):
	attempt = models.ForeignKey(
		TestAttempt, on_delete=models.CASCADE, related_name='section_timing_rows'
	)
	section = models.ForeignKey(
		'testseries.Section', on_delete=models.CASCADE, related_name='attempt_timing_rows'
	)
	time_spent_seconds = models.PositiveIntegerField(default=0)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=['attempt', 'section'], name='uq_attempt_section_timing'
			)
		]
		indexes = [
			models.Index(fields=['attempt', 'section']),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"Timing Attempt {self.attempt_id} Section {self.section_id}"
