#!/usr/bin/env python3
"""NutriLog startup script"""
import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 50)
print("  NutriLog - Food Intake Tracker")
print("=" * 50)
print()
print("  📋 Food Log:   http://localhost:5000")
print("  ⚙️  Admin:      http://localhost:5000/admin")
print("  📊 Export API: http://localhost:5000/api/export")
print()
print("  Press Ctrl+C to stop")
print("=" * 50)

subprocess.run([sys.executable, "app.py"])
