"""
Script to create sample test data for testing unpublish feature
Run this with: python manage.py shell < setup_test_data.py
"""

from accounts.models import CustomUser
from testseries.models import TestSeries

# Get or create admin user
try:
    admin = CustomUser.objects.get(username='admin')
    print(f"✓ Found admin user: {admin.username}")
except CustomUser.DoesNotExist:
    admin = CustomUser.objects.create_superuser(
        'admin',
        'admin@example.com',
        'admin123',
        mobile='9876543210'
    )
    print(f"✓ Created admin user: {admin.username}")

# Create a test series
series, created = TestSeries.objects.get_or_create(
    name='JEE Main Mock Tests',
    defaults={'description': 'Practice tests for JEE Main examination'}
)
if created:
    print(f"✓ Created test series: {series.name}")
else:
    print(f"✓ Found test series: {series.name}")

print("\n" + "="*60)
print("✅ Test data setup complete!")
print("="*60)
print(f"\nAdmin credentials:")
print(f"  Username: admin")
print(f"  Password: admin123")
print(f"\nYou can now:")
print(f"  1. Login at http://127.0.0.1:8000/accounts/login/")
print(f"  2. Go to Test Builder at http://127.0.0.1:8000/builder/")
print(f"  3. Create a test, add questions, and publish")
print(f"  4. Test the unpublish feature")
