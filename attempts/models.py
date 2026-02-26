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

	STATUS_IN_PROGRESS = 'in_progress'
	STATUS_SUBMITTED = 'submitted'
	STATUS_ABANDONED = 'abandoned'
	STATUS_CHOICES = [
		(STATUS_IN_PROGRESS, 'In Progress'),
		(STATUS_SUBMITTED, 'Submitted'),
		(STATUS_ABANDONED, 'Abandoned'),
	]
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

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
			models.Index(fields=["user", "test"]),
			models.Index(fields=["test", "status"]),
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
        indexes = [
            models.Index(fields=["attempt", "question"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Ans Q{self.question_id} in Attempt {self.attempt_id}"
