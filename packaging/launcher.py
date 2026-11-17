"""PyInstaller entry: dispatch native audio workers before importing the server."""
if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    from pulsar.main import main

    main()
