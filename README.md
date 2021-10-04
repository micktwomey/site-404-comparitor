# Site 404 Comparitor

Goal: Walk site a, build up a list of paths and then compare to site b. Aim is to aid migration from one site implementation to another with minimal broken links.

Usage:

1. `poetry install`
2. `poetry run site-404-comparitor https://site1.example.com https://site2.example.com > 404s.csv
3. Use a tool like `visidata` or `excel` to view the 404s.csv

This will cache pages in `/tmp/site_404_comparitor_cache/` by default, second runs should be faster.
