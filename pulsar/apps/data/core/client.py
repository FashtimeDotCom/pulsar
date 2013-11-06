from pulsar import get_event_loop, ImproperlyConfigured
from pulsar.utils.importer import module_attribute
from pulsar.utils.httpurl import urlsplit, parse_qsl, urlunparse, urlencode

from .pool import Pool


_stores = {}


class Compiler(object):
    '''Interface for :class:`Store` compilers.
    '''
    def __init__(self, store):
        self.store = store

    def compile_query(self, query):
        raise NotImplementedError

    def create_table(self, model_class):
        raise NotImplementedError


class Store(object):
    '''Base class for an asynchronous :ref:`data stores <data-stores>`.
    '''
    compiler_class = None
    default_manager = None

    def __init__(self, name, host, loop, database=None,
                 user=None, password=None, encoding=None, **kw):
        self._name = name
        self._host = host
        self._loop = loop
        self._encoding = encoding or 'utf-8'
        self._database = database
        self._user = user
        self._password = password
        self._urlparams = {}
        self._init(**kw)
        self._dns = self._buildurl()

    @property
    def name(self):
        '''Store name'''
        return self._name

    @property
    def database(self):
        '''Database name associated with this store.'''
        return self._database

    @property
    def encoding(self):
        '''Store encoding.'''
        return self._encoding

    @property
    def dns(self):
        '''Domain name server'''
        return self._dns

    @property
    def key(self):
        return (self._dns, self._encoding)

    def __repr__(self):
        return 'Store(dns="%s")' % self._dns
    __str__ = __repr__

    def client(self):
        '''Get a client for the Store'''
        raise NotImplementedError

    def compiler(self):
        '''Create the command :class:`Compiler` for this :class:`Store`

        Must be implemented by subclasses.
        '''
        raise NotImplementedError

    def create_database(self, dbname, **kw):
        '''Create a new database in this store.

        This is a pure virtual method and therefore only some :class:`Store`
        implementation expose it.
        '''
        raise NotImplementedError

    def create_table(self, model_class):
        '''Create the table for ``model_class``.

        This method is supported by sql :class:`.SqlDB`.
        '''
        pass

    def router(self):
        '''Create a :class:`.Router` with this :class:`.Store` as
        default store.
        '''
        from asyncstore import odm
        return odm.Router(self)

    def _init(self, **kw):  # pragma    nocover
        pass

    def _buildurl(self):
        pre = ''
        if self._user:
            if not self._password:
                raise ImproperlyConfigured('user but not password')
            pre = '%s:%s@' % (self._user, self._password)
        elif self._password:
            raise ImproperlyConfigured('password but not user')
            assert self._password
        host = self._host
        if isinstance(host, tuple):
            host = '%s:%s' % host
        path = '/%s' % self._database if self._database else ''
        query = urlencode(self._urlparams)
        return urlunparse((self._name, host, path, '', query, ''))

    def _build_pool(self):
        return Pool


def parse_store_url(url):
    scheme, host, path, query, fr = urlsplit(url)
    assert not fr, 'store url must not have fragment, found %s' % fr
    assert scheme, 'Scheme not provided'
    bits = host.split('@')
    assert len(bits) <= 2, 'Too many @ in %s' % url
    params = dict(parse_qsl(query))
    if path:
        database = path[1:]
        assert '/' not in database, 'Unsupported database %s' % database
        params['database'] = database
    if len(bits) == 2:
        userpass, host = bits
        userpass = userpass.split(':')
        assert len(userpass) == 2,\
            'User and password not in user:password format'
        params['user'] = userpass[0]
        params['password'] = userpass[1]
    else:
        user, password = None, None
    if ':' in host:
        host = tuple(host.split(':'))
    return scheme, host, params


def create_store(url, loop=None, **kw):
    '''Create a new :class:`Store` for a valid ``url``.

    A valid ``url`` taks the following forms::

        postgresql://user:password@127.0.0.1:6500/testdb
        redis://user:password@127.0.0.1:6500/11?namespace=testdb.
        couchdb://user:password@127.0.0.1:6500/testdb

    :param loop: optional event loop, if not provided it is obtained
        via the ``get_event_loop`` method.
    :param kw: additional key-valued parameters to pass to the :class:`Store`
        initialisation method.
    :return: a :class:`Store`.
    '''
    if isinstance(url, Store):
        return url
    loop = loop or get_event_loop()
    scheme, address, params = parse_store_url(url)
    dotted_path = _stores.get(scheme)
    if not dotted_path:
        raise ImproperlyConfigured('%s store not available' % scheme)
    store_class = module_attribute(dotted_path)
    params.update(kw)
    return store_class(scheme, address, loop, **params)


def register_store(name, dotted_path):
    _stores[name] = dotted_path