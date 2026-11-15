"""Compatibility import for the current tab-based View-menu acceptance driver."""
from view_menu_checks import run as current_view_checks


def run(c, wait_for, out, root):
    return current_view_checks(c, wait_for, out)
