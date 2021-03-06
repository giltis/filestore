from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six
import logging
from contextlib import contextmanager
import boltons.cacheutils
from .odm_templates import Resource, Datum

logger = logging.getLogger(__name__)


def _resource_on_miss(k):
    res_col = Resource._get_collection()
    return res_col.find_one({'_id': k})

_DATUM_CACHE = boltons.cacheutils.LRU(max_size=1000000)
_HANDLER_CACHE = boltons.cacheutils.LRU()
_RESOURCE_CACHE = boltons.cacheutils.LRU(on_miss=_resource_on_miss)


class HandlerBase(object):
    """
    Base-class for Handlers to provide the boiler plate to
    make them usable in context managers by provding stubs of
    ``__enter__``, ``__exit__`` and ``close``
    """
    specs = set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        pass


class DuplicateHandler(RuntimeError):
    pass


class HandlerRegistry(dict):
    """
    Sub-class of dict to serve as a registry of available handlers.

    Doing this as a sub-class to give more readable API and to allow
    for more sophisticated validation on the way in later
    """
    def register_handler(self, key, handler, overwrite=False):
        """
        Register a new handler

        Parameters
        ----------
        key : str
            Name of the spec as it will appear in the FS documents

        handler : callable
            This needs to be a callable which when called with the
            free parameters from the FS documents

        overwrite : bool, optional
            If False, raise an exception when re-registering an
            existing key.  Default is False
        """
        if (not overwrite) and (key in self):
            if self[key] is handler:
                return
            raise DuplicateHandler(
                "You are trying to register a second handler "
                "for spec {}, {}".format(key, self))

        self[key] = handler

    def deregister_handler(self, key):
        """
        Remove a handler from the registry.  No-op to remove
        a non-existing key.

        Parameters
        ----------
        key : str
            The spec label to remove
        """
        return self.pop(key, None)

# singleton module-level registry, not 100% with
# this design choice
_h_registry = HandlerRegistry()


@contextmanager
def handler_context(temp_handlers):
    """
    Context manager for temporarily updating the global HandlerRegistry.
    This is an alternative to passing HandlerRegistry objects in
    as a kwarg.  The global registry is returned to it's prior state
    after the context manager exits.

    Parameters
    ----------
    temp_handlers : dict
        spec_name : HandlerClass pairs.

    Examples
    --------
    To use a different handler for a call to `retrieve` use
    the context manager to add (and possibly over-ride existing
    handlers) temporarily:

       with handler_context({'syn-spec', SynHandler}):
           FS.retrieve(EID)

    """
    remove_list = []
    replace_list = []
    for k, v in six.iteritems(temp_handlers):
        if k not in _h_registry:
            remove_list.append(k)
        else:
            old_h = _h_registry.pop(k)
            replace_list.append((k, old_h))
        register_handler(k, v)

    yield
    for k in remove_list:
        deregister_handler(k)
    for k, v in replace_list:
        deregister_handler(k)
        register_handler(k, v)


def register_handler(key, handler, overwrite=False):
    """
    Register a handler to be associated with a specific file
    specification key.  This controls the dispatch to the
    Handler classes based on the `spec` key of the `Resource`
    documents.

    Parameters
    ----------
    key : str
        Name of the spec as it will appear in the FS documents

    handler : callable
        This needs to be a callable which when called with the
        free parameters from the FS documents

    overwrite : bool, optional
        If False, raise an exception when re-registering an
        existing key.  Default is False

    See Also
    --------
    `deregister_handler`

    """
    try:
        _h_registry.register_handler(key, handler)
    except DuplicateHandler:
        if overwrite:
            deregister_handler(key)
            _h_registry.register_handler(key, handler)
        else:
            raise


def deregister_handler(key):
    """
    Remove handler to module-level handler

    Parameters
    ----------
    key : str
        The spec label to remove

    See Also
    --------
    `register_handler`

    """
    handler = _h_registry.deregister_handler(key)
    if handler is not None:
        name = handler.__name__
        for k in list(_HANDLER_CACHE):
            if k[1] == name:
                del _HANDLER_CACHE[k]


def get_spec_handler(resource, handle_registry=None):
    """
    Given a document from the base FS collection return
    the proper Handler

    This should get memozied or shoved into a class eventually
    to minimize open/close thrashing.

    Parameters
    ----------
    resource : ObjectId
        ObjectId of a resource document

    handle_registry : HandleRegistry or dict, optional
        Mapping between spec <-> handler classes, if None, use
        module-level registry

    Returns
    -------

    handler : callable
        An object that when called with the values in the event
        document returns the externally stored data

    """

    if handle_registry is None:
        handle_registry = _h_registry
    resource = _RESOURCE_CACHE[resource]

    spec = resource['spec']
    handler = handle_registry[spec]
    key = (str(resource['_id']), handler.__name__)
    if key in _HANDLER_CACHE:
        return _HANDLER_CACHE[key]
    kwargs = resource['resource_kwargs']
    rpath = resource['resource_path']
    ret = handler(rpath, **kwargs)
    _HANDLER_CACHE[key] = ret
    return ret


def get_data(eid, handle_registry=None):
    """
    Given a document from the events collection, get the externally
    stored data.

    This may get wrapped up in a class instance, not intended for public
    usage as-is

    Parameters
    ----------
    eid : str
        The resource ID (as stored in MDS)

    handle_registry : HandleRegistry or dict, optional
        Mapping between spec <-> handler classes, if None, use
        module-level registry

    Returns
    -------
    data : ndarray
        The data in ndarray form.
    """

    try:
        datum = _DATUM_CACHE[eid]
    except KeyError:
        keys = ['datum_kwargs', 'resource']
        d_objs = Datum._get_collection()
        # find the current document
        edoc = d_objs.find_one({'datum_id': eid})
        if edoc is None:
            raise Datum.DoesNotExist()
        # save it for later
        datum = {k: edoc[k] for k in keys}

        res = edoc['resource']
        count = 0
        for dd in d_objs.find({'resource': res}):
            count += 1
            d_id = dd['datum_id']
            if d_id not in _DATUM_CACHE:
                _DATUM_CACHE[d_id] = {k: dd[k] for k in keys}
        if count > _DATUM_CACHE.max_size:
            logger.warn("More datum in a resource than your "
                        "datum cache can hold.")

    handler = get_spec_handler(datum['resource'], handle_registry)
    return handler(**datum['datum_kwargs'])
