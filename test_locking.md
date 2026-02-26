# Draft Locking Mechanism - Testing Guide

## ✅ Implementation Complete!

### What Was Added:

1. **Database Fields** (in `TestDraft` model):
   - `locked_by` - Foreign key to User (who has the lock)
   - `locked_at` - Timestamp when lock was acquired

2. **Lock Management Methods**:
   - `is_locked()` - Check if draft is currently locked (with 30-min auto-expiry)
   - `can_edit(user)` - Check if a specific user can edit
   - `acquire_lock(user)` - Acquire lock for a user
   - `release_lock()` - Release the lock
   - `refresh_lock(user)` - Update timestamp to keep lock active

3. **Protected Views** (all have lock checking now):
   - ✅ `manage_sections` - Check lock before editing sections
   - ✅ `manage_questions` - Check lock before editing questions
   - ✅ `publish_test` - Check lock before publishing, release after success
   - ✅ `unpublish_test` - Check lock before unpublishing, release after success
   - ✅ `delete_draft` - Check lock before deletion, release before delete
   - ✅ `delete_published_test` - Check lock before deletion, release before delete

4. **Dashboard UI Updates**:
   - Shows lock status badges on draft cards
   - Blue badge: "You're editing" (for current user)
   - Red badge: "Locked by [username]" (for other admins)
   - Same for published tests section

---

## 🧪 How to Test:

### Test Scenario 1: Basic Locking
1. **Admin A** logs in and clicks "Continue Editing" on a draft
   - ✅ Lock is acquired automatically
   - ✅ Dashboard shows blue "You're editing" badge

2. **Admin B** logs in (different browser/incognito) and tries to edit the same draft
   - ✅ Gets error: "❌ This test is currently being edited by [Admin A username]..."
   - ✅ Redirected to dashboard
   - ✅ Dashboard shows red "Locked by Admin A" badge

3. **Admin A** publishes the test
   - ✅ Lock is automatically released
   - ✅ Admin B can now access it

### Test Scenario 2: Lock Auto-Expiry
1. **Admin A** starts editing a draft
2. Wait 30 minutes (or modify code to 1 minute for faster testing)
3. **Admin B** tries to edit
   - ✅ Lock has expired automatically
   - ✅ Admin B can now edit
   - ✅ New lock acquired for Admin B

### Test Scenario 3: Lock Refresh
1. **Admin A** starts editing sections
2. **Admin A** makes changes and saves
   - ✅ Lock timestamp is refreshed
   - ✅ Lock expiry extends by another 30 minutes

### Test Scenario 4: Delete While Locked
1. **Admin A** is editing a draft
2. **Admin B** tries to delete the same draft
   - ✅ Gets error: "❌ This test is currently being edited by [Admin A username]. Cannot delete while being edited."
   - ✅ Delete is prevented

### Test Scenario 5: Multiple Drafts
1. **Admin A** edits Draft X
2. **Admin B** edits Draft Y (different test)
   - ✅ Both succeed (no conflict)
   - ✅ Each has their own lock

---

## 🔧 Technical Details:

### Lock Expiration
- **Duration**: 30 minutes
- **Why**: Prevents locks from staying forever if admin closes browser
- **Location**: `test_builder/models.py` line ~30-35

### Error Messages
All lock errors show:
```
❌ This test is currently being edited by [username]. 
Please wait until they finish. Lock will auto-expire after 30 minutes of inactivity.
```

### When Locks Are Released:
- ✅ After successful publish
- ✅ After successful unpublish
- ✅ Before draft deletion
- ✅ Automatically after 30 minutes

### When Locks Are Refreshed:
- ✅ On every POST action in manage_sections
- ✅ On every POST action in manage_questions

---

## 🚀 Migration Applied:

```bash
✅ Migration: 0004_add_draft_locking
✅ Fields Added: locked_by, locked_at
✅ Status: Applied successfully
```

---

## 📝 User Flow Example:

**Admin A (John):**
1. Opens "JEE Main Physics" draft at 2:00 PM
2. Lock acquired: `locked_by=John, locked_at=2:00 PM`
3. Edits sections for 10 minutes
4. Publishes at 2:10 PM
5. Lock released: `locked_by=None, locked_at=None`

**Admin B (Sarah):**
1. Tries to open same draft at 2:05 PM (while John is editing)
2. Sees error: "This test is currently being edited by john..."
3. Dashboard shows red badge "Locked by john"
4. After John publishes (2:10 PM), Sarah can now edit

---

## 🎯 Key Benefits:

1. **Prevents Data Conflicts**: No more overwrites when 2 admins edit simultaneously
2. **Clear Communication**: Admin knows who has the lock and when it expires
3. **Automatic Expiry**: Abandoned locks don't block forever
4. **User-Friendly**: Shows visual indicators on dashboard
5. **First-Come-First-Served**: Whoever clicks first gets access

---

## 🔍 Code Locations:

- **Model**: `test_builder/models.py` (lines 20-50)
- **Views**: `test_builder/views.py` (multiple functions updated)
- **Template**: `templates/test_builder/dashboard.html` (lock badges)
- **Migration**: `test_builder/migrations/0004_add_draft_locking.py`

---

## ✨ Next Steps (Optional Enhancements):

1. **Force Unlock Button**: Allow admins to manually unlock if needed
2. **Real-time Notifications**: WebSocket alerts when lock is released
3. **Lock History**: Track who locked/unlocked and when
4. **Configurable Timeout**: Admin setting for lock duration (15/30/60 minutes)

---

## 🐛 Troubleshooting:

**Problem**: Locks not working
- **Solution**: Run `python manage.py migrate test_builder` to ensure migration is applied

**Problem**: Lock doesn't expire
- **Solution**: Check system timezone settings match Django `TIME_ZONE` in settings.py

**Problem**: Can't edit own draft
- **Solution**: Check `locked_by` field - should be your user. Can manually clear in Django admin if stuck.

---

**Implementation Status**: ✅ 100% Complete and Ready for Testing!
