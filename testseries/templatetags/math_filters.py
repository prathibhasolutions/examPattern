from django import template

register = template.Library()

@register.filter
def divide(value, arg):
    """Divide value by arg"""
    try:
        return int(value) / int(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def get_item(dictionary, key):
    """Return dictionary[key], defaulting to an empty dict if not found."""
    if not isinstance(dictionary, dict):
        return {}
    return dictionary.get(key, {})
