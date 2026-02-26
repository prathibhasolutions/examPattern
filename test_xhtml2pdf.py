#!/usr/bin/env python
import sys
print(f"Python executable: {sys.executable}")
print(f"Python path: {sys.path}")

try:
    import xhtml2pdf
    print(f"✓ xhtml2pdf imported successfully from: {xhtml2pdf.__file__}")
    from xhtml2pdf import pisa
    print(f"✓ pisa imported successfully")
except ImportError as e:
    print(f"✗ ImportError: {e}")
except Exception as e:
    print(f"✗ Exception: {type(e).__name__}: {e}")
