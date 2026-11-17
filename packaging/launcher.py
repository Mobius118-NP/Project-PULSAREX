"""PyInstaller entry: dispatch native audio workers before importing the server."""
if __name__ == "__main__":
    import multiprocessing
    import os
    import sys

    # Windowed builds have no standard streams. Uvicorn's logging must still have
    # valid file objects in the server worker and native microphone subprocesses.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == '--check-launcher':
        from pulsar.launcher_check import main
        main(sys.argv[2])
        raise SystemExit(0)
    if len(sys.argv) > 1 or 'Console' in os.path.basename(sys.executable):
        from pulsar.main import main
    else:
        from pulsar.launcher import main

    main()
