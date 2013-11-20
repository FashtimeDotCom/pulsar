'''\
Pulsar key-value store server. To run the server type::

    python manage.py

Open a new shell and launch python and type::

    >>> from pulsar.apps.data import create_store
    >>> store = create_store('pulsar://localhost:6410', force_sync=True)
    >>> client = store.client()
    >>> client.ping()
    True
    >>> client.echo('Hello!')
    b'Hello!'
    >>> client.set('bla', 'foo')
    True
    >>> client.get('bla')
    b'foo'
    >>> client.dbsize()
    1

The ``force_sync`` keyword is used here to force the client to
wait for a full response rather than returning a :class:`.Deferred`.
Check the :ref:`creating synchronous clients <tutorials-synchronous>` tutorial.
'''
try:
    import pulsar
except ImportError:  # pragma nocover
    import sys
    sys.path.append('../../')

from pulsar.apps.data import KeyValueStore


if __name__ == '__main__':  # pragma nocover
    KeyValueStore().start()