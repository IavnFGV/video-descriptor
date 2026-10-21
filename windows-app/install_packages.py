"""Run pip with canonical Windows RECORD lookup paths, including long paths.

pip 25 rehashes a rewritten script using ``site-packages/../../Scripts``.
The extended Windows prefix deliberately disables OS path normalization, so the
lookup must be normalized before hashing the installed script for RECORD.
This process-local adapter does not modify pip files or Windows policy.
"""
import ntpath
import os
import sys


def normalize_record_path(path):
    return ntpath.normpath(path)


def main(arguments=None):
    if os.name == 'nt':
        from pip._internal.operations.install import wheel
        original = wheel._record_to_fs_path

        def record_to_fs_path(*args, **kwargs):
            return normalize_record_path(original(*args, **kwargs))

        wheel._record_to_fs_path = record_to_fs_path
    from pip._internal.cli.main import main as pip_main
    return pip_main(sys.argv[1:] if arguments is None else arguments)


if __name__ == '__main__':
    raise SystemExit(main())
