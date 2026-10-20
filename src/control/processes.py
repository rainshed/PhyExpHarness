"""Reap owned children independently of persisted experiment completion."""


def reap_children(children, store, table, terminal_states):
    for id, process in list(children.items()):
        # poll() is non-blocking and reaps exited children, caching their exit code.
        # Keep the handle until collection succeeds so retries still see that code.
        if process.poll() is not None and store.get(table, id)['state'] in terminal_states:
            del children[id]
