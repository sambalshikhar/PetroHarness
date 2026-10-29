"""The web UI (`petroharness ui`): ask a question about a LAS file in the browser, follow the investigation as it
happens, and keep, rate and replay the runs. server.py serves the page and its API; adapter.py turns the page's
inputs into petroharness.ask's arguments and runs a question; progress.py reports each model call; store.py keeps the
runs."""
