from django import template

register = template.Library()

@register.filter
def divide(value, arg):
    """Divide value by arg"""
    try:
        return int(value) / int(arg)
    except (ValueError, ZeroDivisionError):
        return 0
