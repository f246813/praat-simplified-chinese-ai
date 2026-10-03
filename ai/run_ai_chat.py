from __future__ import annotations


def main():
    # Dependency import failures must be visible even under pythonw / native menus.
    from praat_ai.desktop_launch import clear_own_records, report_failure
    try:
        from praat_ai.modern_host import main as run
        return run()
    except Exception as error:
        return report_failure(error)
    finally:
        clear_own_records()


if __name__ == '__main__':
    raise SystemExit(main())
