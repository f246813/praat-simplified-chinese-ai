if __name__ == '__main__':
    import sys
    from pathlib import Path
    try:
        from praat_ai.frontend_status import main
        raise SystemExit(main())
    except Exception as error:
        (Path(__file__).parent/'runtime'/'frontend-menu-error.txt').write_text(
            type(error).__name__+': '+str(error), encoding='utf8')
        raise
