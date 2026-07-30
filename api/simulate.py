"""Vercel Python Function: thin HTTP adapter over the `solver` package.

Keep this file free of physics/numerics — it only translates the HTTP request into
calls against `solver`, so `solver` stays independently importable and testable.
"""
