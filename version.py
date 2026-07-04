"""Single source of truth for the report version.

Bump REPORT_VERSION on every git commit that changes report output, and add a
matching line to CHANGELOG.md.  The version + build date are stamped in the
top-right corner of the report's front page.
"""
REPORT_VERSION = "1.2"
