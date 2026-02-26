# Publish/Unpublish Toggle Feature

## Overview
Admins can now toggle tests between published (visible to students) and unpublished (hidden from students) states without requiring any editing. This allows temporary hiding of tests while preserving all data and student attempts.

## What Changed

### 1. Backend - New View & URL
**File**: `test_builder/views.py`
- **New View**: `toggle_test_active(request, draft_id)`
  - Toggles the `is_active` field of a published test
  - Requires admin login
  - Returns JSON response with success status
  - Accepts POST requests only

**File**: `test_builder/urls.py`
- **New URL**: `path('<int:draft_id>/toggle-active/', views.toggle_test_active, name='builder_toggle_active')`

### 2. Frontend - Dashboard Update
**File**: `templates/test_builder/dashboard.html`
- **New UI Elements** in Published Tests section:
  - Toggle switch (checkbox styled as switch)
  - Descriptive text: "Toggle to show/hide from students. Data remains safe."
  - Confirmation dialog before toggling

### 3. JavaScript Functionality
- On toggle change:
  1. Shows confirmation dialog
  2. On confirm, sends AJAX POST to backend
  3. Toggles the is_active status
  4. Shows success message
  5. Updates UI in real-time
- On cancel, reverts toggle state

## How It Works

### User Flow
1. **Admin** opens Dashboard → Published Tests section
2. **Admin** sees toggle switch next to each published test
3. **Admin** clicks toggle to turn OFF (unpublish)
4. **Confirmation dialog** appears:
   - "Are you sure you want to unpublish this test? Students won't be able to take it, but their previous attempts will remain safe."
5. **Admin** confirms
6. **Test** becomes unpublished:
   - `is_active = False`
   - Disappears from student search
   - Disappears from students' test list
   - Previous attempts remain safe
7. **Success message** shows: "Test 'Name' has been unpublished."

### Toggling Back ON
1. **Admin** clicks toggle again to turn ON (publish)
2. **Confirmation dialog**:
   - "Are you sure you want to publish this test? It will be visible to students."
3. **Admin** confirms
4. **Test** becomes published:
   - `is_active = True`
   - Reappears in student search
   - Reappears in students' test list
5. **Success message** shows: "Test 'Name' has been published."

## Data Safety

### What is Preserved:
✅ All student attempts remain safe
✅ All test data (questions, options, sections) remains
✅ Test can be republished anytime
✅ Student attempt history is not affected

### What Happens When Unpublished:
❌ Test disappears from student view
❌ Students cannot take the test
❌ Test doesn't appear in search results
⚠️ Existing attempts remain (read-only)

### Deletion vs Unpublishing:
- **Unpublish** (Toggle OFF): Test hidden but data preserved
- **Delete**: Test and all data permanently removed

## Key Features

1. **No Editing Required**
   - Simple toggle, no need to go through edit workflow
   - Instant on/off without modifying test content

2. **Access Control**
   - Only admins can toggle
   - Any admin can toggle any test (not just creator)

3. **User Feedback**
   - Confirmation dialog prevents accidental toggles
   - Success messages show action completed
   - Toggle state syncs in real-time

4. **Data Integrity**
   - Toggle only changes `is_active` field
   - No data loss or modification
   - Student attempts remain accessible

## Database Impact

**Modified Field**: `Test.is_active`
- `True` = Published/Visible to students
- `False` = Unpublished/Hidden from students

**No new tables or migrations required** - uses existing `is_active` field.

## Use Cases

1. **Temporary Hiding**
   - Admin hides a test during technical issues
   - Hides it again later without recreating

2. **Maintenance**
   - Admin unpublishes test for review
   - Publishes again after quality check

3. **Seasonal Tests**
   - Test created for specific period
   - Hidden after date passes
   - Republished next year

4. **Multi-Admin Workflow**
   - Admin1 publishes test
   - Admin2 temporarily hides it
   - Admin1 republishes it later

## Testing Checklist

✅ Admin logs in to dashboard
✅ Toggle appears on published tests
✅ Clicking toggle shows confirmation dialog
✅ Canceling confirmation reverts toggle
✅ Confirming toggle changes test state
✅ Success message appears
✅ Test disappears from student search after unpublish
✅ Test reappears after republish
✅ Student attempts remain safe
✅ Toggle state reflects in dashboard after refresh

## Technical Details

### API Endpoint
```
POST /builder/<draft_id>/toggle-active/
Headers: X-CSRFToken, Content-Type: application/json
Response: {"success": true, "is_active": true, "status_text": "...", "message": "..."}
```

### JavaScript Handling
- Fetches CSRF token from form or cookies
- Sends AJAX POST with credentials
- Handles errors gracefully
- Reverts UI state on error

### CSRF Protection
- Uses Django CSRF protection
- Token extracted from:
  1. Hidden form field `csrfmiddlewaretoken`
  2. Cookie `csrftoken` (fallback)

## Future Enhancements (Optional)

1. **Bulk Toggle** - Toggle multiple tests at once
2. **Auto-expire** - Automatically unpublish on specific date
3. **History** - Track when tests were toggled and by whom
4. **Notifications** - Alert students when test becomes available/unavailable
5. **Scheduled Publishing** - Set test to auto-publish on specific date/time

## Status
✅ **Implementation Complete and Tested**
