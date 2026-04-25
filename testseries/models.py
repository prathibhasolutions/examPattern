from django.db import models


class TestSeries(models.Model):
	name = models.CharField(max_length=200, unique=True)
	slug = models.SlugField(max_length=220, unique=True)
	description = models.TextField(blank=True)
	exam_cover = models.ImageField(upload_to="series_exam_covers/", blank=True, null=True)
	price = models.DecimalField(
		max_digits=8, decimal_places=2, default=0,
		help_text="Price in INR. Set to 0 for a free series."
	)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]
		indexes = [
			models.Index(fields=["slug"]),
			models.Index(fields=["is_active"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return self.name


class TestSeriesExamSection(models.Model):
	series = models.ForeignKey(
		TestSeries, on_delete=models.CASCADE, related_name="exam_sections"
	)
	title = models.CharField(max_length=200)
	body = models.TextField(blank=True)
	image = models.ImageField(upload_to="series_exam_sections/", blank=True, null=True)
	order = models.PositiveSmallIntegerField(default=1)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["order", "id"]
		indexes = [
			models.Index(fields=["series"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.series.name} — {self.title}"


class TestSeriesHighlight(models.Model):
	series = models.ForeignKey(
		TestSeries, on_delete=models.CASCADE, related_name="highlights"
	)
	title = models.CharField(max_length=120)
	value = models.CharField(max_length=240, blank=True)
	order = models.PositiveSmallIntegerField(default=1)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["order", "id"]
		indexes = [
			models.Index(fields=["series"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.series.name} — {self.title}"


class SeriesSection(models.Model):
	series = models.ForeignKey(
		TestSeries, on_delete=models.CASCADE, related_name="sections"
	)
	name = models.CharField(max_length=150)
	slug = models.SlugField(max_length=170)
	order = models.PositiveSmallIntegerField(default=1)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["series", "order", "name"]
		constraints = [
			models.UniqueConstraint(
				fields=["series", "slug"], name="uq_series_section_slug"
			),
			models.UniqueConstraint(
				fields=["series", "name"], name="uq_series_section_name"
			),
		]
		indexes = [
			models.Index(fields=["series"]),
			models.Index(fields=["is_active"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.series.name} — {self.name}"


class SeriesSubsection(models.Model):
	section = models.ForeignKey(
		SeriesSection, on_delete=models.CASCADE, related_name="subsections"
	)
	name = models.CharField(max_length=150)
	slug = models.SlugField(max_length=170)
	order = models.PositiveSmallIntegerField(default=1)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["section", "order", "name"]
		constraints = [
			models.UniqueConstraint(
				fields=["section", "slug"], name="uq_series_subsection_slug"
			),
			models.UniqueConstraint(
				fields=["section", "name"], name="uq_series_subsection_name"
			),
		]
		indexes = [
			models.Index(fields=["section"]),
			models.Index(fields=["is_active"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.section.series.name} — {self.section.name} — {self.name}"


class Test(models.Model):
	series = models.ForeignKey(
		TestSeries, on_delete=models.CASCADE, related_name="tests"
	)
	series_section = models.ForeignKey(
		SeriesSection,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="tests",
	)
	series_subsection = models.ForeignKey(
		SeriesSubsection,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="tests",
	)
	name = models.CharField(max_length=200)
	slug = models.SlugField(max_length=220)
	description = models.TextField(blank=True)

	# Duration at test level (in seconds). Sections may have their own limits.
	duration_seconds = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
	use_sectional_timing = models.BooleanField(
		default=False,
		help_text="If True, each section has its own time limit and auto-advances when time ends"
	)
	shuffle_questions = models.BooleanField(
		default=False,
		help_text="If True, questions and options are shuffled into a unique random order per student"
	)
	continuous_numbering = models.BooleanField(
		default=False,
		help_text="If True, question numbers continue across sections (1, 2, …, N) instead of resetting to 1 per section"
	)

	# Default marking scheme (can be overridden at section/question level)
	marks_per_question = models.DecimalField(max_digits=6, decimal_places=2, default=1.0)
	negative_marks_per_question = models.DecimalField(
		max_digits=6, decimal_places=2, default=0.0
	)

	is_active = models.BooleanField(default=True)
	starts_at = models.DateTimeField(null=True, blank=True)
	ends_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["series", "name"]
		constraints = [
			models.UniqueConstraint(
				fields=["series", "slug"], name="uq_test_slug_within_series"
			)
		]
		indexes = [
			models.Index(fields=["is_active"]),
			models.Index(fields=["starts_at"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.series.name} — {self.name}"


class Section(models.Model):
	test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="sections")
	name = models.CharField(max_length=150)
	order = models.PositiveSmallIntegerField(default=1)
	# Tracks which SectionDraft this was created from (used for in-place re-publish)
	draft_section_id = models.IntegerField(null=True, blank=True, db_index=True)

	# Sectional timing (in seconds). 0/blank means no dedicated cap beyond test level
	time_limit_seconds = models.PositiveIntegerField(
		default=0, help_text="0 means no separate limit"
	)

	# Optional per-section marking overrides
	marks_per_question = models.DecimalField(
		max_digits=6, decimal_places=2, null=True, blank=True
	)
	negative_marks_per_question = models.DecimalField(
		max_digits=6, decimal_places=2, null=True, blank=True
	)

	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["test", "order", "name"]
		constraints = [
			models.UniqueConstraint(
				fields=["test", "name"], name="uq_section_name_within_test"
			),
			models.UniqueConstraint(
				fields=["test", "order"], name="uq_section_order_within_test"
			),
		]
		indexes = [
			models.Index(fields=["is_active"]),
		]

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.test.name} — {self.name}"
