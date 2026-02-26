from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    """Custom admin for CustomUser model"""
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'mobile', 'photo')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Verification', {'fields': ('is_verified', 'created_at', 'updated_at')}),
    )
    
    list_display = ('username', 'email', 'mobile', 'is_verified', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_verified', 'is_staff', 'created_at')
    search_fields = ('username', 'email', 'mobile', 'first_name', 'last_name')
    readonly_fields = ('created_at', 'updated_at', 'date_joined', 'last_login')

