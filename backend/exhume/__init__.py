"""Exhume (spec ``scan-backend``): GitHub-side input handling for a scan.

``validate`` and ``select`` are pure. ``github_app`` and ``trees`` take an ``httpx.Client`` from
the caller and read no environment variable.
"""
