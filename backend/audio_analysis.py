"""Command-line entry point for audio transcription."""

if __package__:
    from .analysis.audio_analysis import main
else:
    from analysis.audio_analysis import main

if __name__ == "__main__":
    main()
