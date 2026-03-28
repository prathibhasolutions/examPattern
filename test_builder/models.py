from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from testseries.models import TestSeries, SeriesSection, SeriesSubsection


class TestDraft(models.Model):
    """Simple draft model for test creation"""
    series = models.ForeignKey(TestSeries, on_delete=models.CASCADE, related_name='drafts')
    series_section = models.ForeignKey(
        SeriesSection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drafts',
        help_text="Section within the test series"
    )
    series_subsection = models.ForeignKey(
        SeriesSubsection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drafts',
        help_text="Subsection within the test series section"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_minutes = models.IntegerField(help_text="Total test duration in minutes")
    marks_per_question = models.DecimalField(max_digits=5, decimal_places=2)
    negative_marks = models.DecimalField(max_digits=5, decimal_places=2)
    use_sectional_timing = models.BooleanField(
        default=False, 
        help_text="If True, each section has its own time limit and auto-advances when time ends"
    )
    shuffle_questions = models.BooleanField(
        default=False,
        help_text="If True, questions and options are shuffled into a unique random order per student"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False)
    published_test_id = models.IntegerField(null=True, blank=True, help_text="ID of published test")
    
    # Locking mechanism for concurrent editing prevention
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='locked_drafts',
        help_text="Admin currently editing this draft"
    )
    locked_at = models.DateTimeField(null=True, blank=True, help_text="When the lock was acquired")
    
    def is_locked(self):
        """Check if draft is currently locked"""
        if not self.locked_by or not self.locked_at:
            return False
        
        # Auto-expire locks after 30 minutes of inactivity
        lock_expiry = timezone.now() - timezone.timedelta(minutes=30)
        if self.locked_at < lock_expiry:
            self.release_lock()
            return False
        
        return True
    
    def can_edit(self, user):
        """Check if user can edit this draft"""
        if not self.is_locked():
            return True
        return self.locked_by == user
    
    def acquire_lock(self, user):
        """Acquire lock for editing"""
        if self.can_edit(user):
            self.locked_by = user
            self.locked_at = timezone.now()
            self.save(update_fields=['locked_by', 'locked_at'])
            return True
        return False
    
    def release_lock(self):
        """Release the lock"""
        self.locked_by = None
        self.locked_at = None
        self.save(update_fields=['locked_by', 'locked_at'])
    
    def refresh_lock(self, user):
        """Refresh lock timestamp to keep it active"""
        if self.locked_by == user:
            self.locked_at = timezone.now()
            self.save(update_fields=['locked_at'])
    
    def __str__(self):
        return f"{self.name} (Draft)"
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['series', 'name', 'created_by'],
                name='unique_test_draft_per_user_series'
            )
        ]


class SectionDraft(models.Model):
    """Section in draft test"""
    test_draft = models.ForeignKey(TestDraft, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=100)
    order = models.IntegerField(default=1)
    time_limit_minutes = models.IntegerField(
        default=0, 
        help_text="Time limit for this section in minutes (only used if use_sectional_timing is True)"
    )
    
    def __str__(self):
        return f"{self.test_draft.name} - {self.name}"
    
    class Meta:
        ordering = ['order']


class QuestionDraft(models.Model):
    """Question in draft section"""
    section = models.ForeignKey(SectionDraft, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField(blank=True, help_text="Question text (optional if image provided)")
    question_image = models.ImageField(upload_to='draft_questions/', blank=True, null=True)
    solution_text = models.TextField(blank=True)
    solution_image = models.ImageField(upload_to='draft_solutions/', blank=True, null=True)
    order = models.IntegerField(default=1)
    
    def clean(self):
        """Validate that question has at least text or image"""
        super().clean()
        if not self.question_text and not self.question_image:
            raise ValidationError(
                'Question must have either text or an image (or both).'
            )
    
    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}"
    
    class Meta:
        ordering = ['order']


class OptionDraft(models.Model):
    """Option for draft question"""
    question = models.ForeignKey(QuestionDraft, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=500, blank=True, help_text="Option text (optional if image provided)")
    option_image = models.ImageField(upload_to='draft_options/', blank=True, null=True)
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField(default=1)
    
    def clean(self):
        """Validate that option has at least text or image"""
        super().clean()
        if not self.option_text and not self.option_image:
            raise ValidationError(
                'Option must have either text or an image (or both).'
            )
    
    def __str__(self):
        return f"Option {self.order}: {self.option_text[:30]}"
    
    class Meta:
        ordering = ['order']


class PDFImportJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    draft = models.ForeignKey(TestDraft, on_delete=models.CASCADE, related_name='pdf_import_jobs')
    section = models.ForeignKey(SectionDraft, on_delete=models.CASCADE, related_name='pdf_import_jobs')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pdf_import_jobs')
    source_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider_name = models.CharField(max_length=100, blank=True)
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    skip_summary = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"PDF import for {self.draft.name} -> {self.section.name} ({self.status})"
