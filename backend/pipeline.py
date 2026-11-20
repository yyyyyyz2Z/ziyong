"""Command-line entry point for the fingering pipeline."""

if __package__:
    from .analysis.pipeline import main
else:
    from analysis.pipeline import main

if __name__ == "__main__":
    main()
