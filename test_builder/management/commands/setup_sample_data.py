from django.core.management.base import BaseCommand
from accounts.models import CustomUser
from testseries.models import TestSeries


class Command(BaseCommand):
    help = 'Create sample test series for testing'

    def handle(self, *args, **options):
        # Check if admin exists
        try:
            admin = CustomUser.objects.get(username='admin')
            self.stdout.write(self.style.SUCCESS(f'✓ Found admin user: {admin.username}'))
        except CustomUser.DoesNotExist:
            self.stdout.write(self.style.ERROR('✗ Admin user not found. Please create it first.'))
            return

        # Create test series
        series, created = TestSeries.objects.get_or_create(
            name='JEE Main Mock Tests',
            defaults={'description': 'Practice tests for JEE Main examination'}
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created test series: {series.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Test series already exists: {series.name}'))

        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('✅ Setup complete!'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write('\nYou can now:')
        self.stdout.write('  1. Login at http://127.0.0.1:8000/accounts/login/')
        self.stdout.write('     Username: admin')
        self.stdout.write('     Password: admin123')
        self.stdout.write('  2. Go to Test Builder at http://127.0.0.1:8000/builder/')
        self.stdout.write('  3. Create a test, add questions, and publish')
        self.stdout.write('  4. Test the unpublish feature\n')
