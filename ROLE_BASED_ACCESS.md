# Role-Based Access Control (RBAC) Guide

## Overview
Your MockTest Platform now has **two distinct user roles**:

### 1. **👑 Administrator (Superuser)**
- Can create and manage tests using the Test Builder
- Can access Django Admin Portal (`/admin/`)
- Full control over test series, questions, and options
- Can create other admin accounts through Django Admin
- Can view and manage all system data

### 2. **📚 Student (Regular User)**
- Can only attempt tests
- Can view test results and analysis
- Can review solutions after attempting
- Cannot access Test Builder or Admin Portal
- Cannot create or modify tests

---

## Key Security Features

### ✅ **Test Builder Access** (`/builder/`)
- **Protected by `@admin_required` decorator**
- Only accessible to users with `is_staff=True` AND `is_superuser=True`
- Regular users trying to access will see: "Access Denied - You do not have permission"
- All builder operations require admin authentication:
  - Creating tests
  - Managing sections
  - Adding questions
  - Publishing tests
  - Editing published tests
  - Deleting tests

### ✅ **Django Admin Portal** (`/admin/`)
- Protected by Django's default authentication
- Only superuser accounts can login
- Regular users cannot access even if they guess the URL

### ✅ **Test Attempt Features** (`/tests/`)
- All students can view available tests
- Only authenticated users can attempt tests
- Login prompt shown for non-authenticated users
- Attempt limit enforced (max 2 attempts per test)

---

## How to Create Admin Accounts

**Only through Django Admin Portal:**

1. Go to `http://localhost:8000/admin/`
2. Login with your superuser account (e.g., admin)
3. Navigate to **Users** section
4. Click **"Add User"**
5. Fill in username and password
6. **Check the checkboxes:**
   - ✅ `Staff status` - Allows admin portal access
   - ✅ `Superuser status` - Full admin privileges
7. Click **"Save"**

The new admin will now see:
- "👑 Admin" badge on tests page
- "Test Builder" link in navbar
- Access to `/admin/` portal

---

## User Experience Changes

### For Students (Regular Users)
- **Homepage (`/tests/`)**: Browse and attempt tests
- **Auth Banner**: Shows "📚 Student" role badge
- **Navbar**: Shows "My Profile" and "Logout" links
- **Test Builder Access**: Shows "Access Denied" error page
- **Admin Portal**: Cannot login (shows Django login error)

### For Admins
- **Homepage (`/tests/`)**: Shows "👑 Admin" role badge with crown icon
- **Navbar**: Shows "Test Builder" link (yellow/gold color)
- **Test Builder**: Full access to create/edit/manage tests
- **Admin Portal**: Full access to all system management
- **Auth Banner**: Option to go to "Test Builder" instead of just "My Profile"

---

## Database User Permissions

| Permission | Student | Admin |
|-----------|---------|-------|
| View tests | ✅ | ✅ |
| Attempt tests | ✅ | ✅ |
| View results | ✅ | ✅ |
| Review solutions | ✅ | ✅ |
| Create tests | ❌ | ✅ |
| Edit tests | ❌ | ✅ |
| Manage questions | ❌ | ✅ |
| Publish tests | ❌ | ✅ |
| Access admin portal | ❌ | ✅ |
| Manage users | ❌ | ✅ |

---

## Code Changes Made

### 1. **test_builder/views.py**
```python
# Added @admin_required decorator to all builder views
@admin_required
@login_required
def dashboard(request):
    # Only accessible to admins
```

### 2. **templates/tests_list.html**
```html
<!-- Shows admin badge and Test Builder link for admins -->
{% if user.is_staff and user.is_superuser %}
    <span class="badge bg-warning text-dark">👑 Admin</span>
    <a href="/builder/">Test Builder</a>
{% endif %}
```

### 3. **templates/test_builder/dashboard.html**
```html
<!-- Shows admin-only notification -->
<span class="badge bg-success">Admin Access Only</span>
```

---

## Testing Role-Based Access

### Test Student Access:
1. Register a new account at `/accounts/register/`
2. Try to access `/builder/` → Should see "Access Denied"
3. Try to access `/admin/` → Should see login error
4. Can view and attempt tests at `/tests/` ✅

### Test Admin Access:
1. Create admin account through Django admin
2. Login with admin account
3. Go to `/tests/` → See "👑 Admin" badge ✅
4. Access `/builder/` → See Test Builder dashboard ✅
5. Access `/admin/` → See Django admin panel ✅

---

## Future Enhancements

Possible improvements:
- Add role selection during registration
- Create teacher role (can view student results but not modify tests)
- Add analytics dashboard for admins
- Email notifications for test publishing
- Audit logs for admin actions
- Permission matrix for fine-grained access control

---

## Support

If a student accidentally tries to access admin features:
- They'll see "Access Denied" message
- They can contact admin to request feature access
- Admins should be the only ones creating accounts in Django Admin

For questions or issues, contact your system administrator.
