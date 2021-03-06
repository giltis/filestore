from __future__ import absolute_import, division, print_function
import six
from mongoengine import (Document, StringField, DictField, ReferenceField,
                         DENY)

import logging
import json
from pkg_resources import resource_filename

logger = logging.getLogger(__name__)

# module-level global dict to store the schema for know file formats (spec)
known_spec = dict()

# load the built-in schema
for spec_name in ['AD_HDF5', 'AD_SPE']:
    tmp_dict = {}
    resource_name = 'json/{}_resource.json'.format(spec_name)
    datum_name = 'json/{}_datum.json'.format(spec_name)
    with open(resource_filename('filestore', resource_name), 'r') as fin:
        tmp_dict['resource'] = json.load(fin)
    with open(resource_filename('filestore', datum_name), 'r') as fin:
        tmp_dict['datum'] = json.load(fin)
    known_spec[spec_name] = tmp_dict

ALIAS = 'fs'


class Resource(Document):
    """

    Parameters
    ----------

    spec : str
        spec used to determine what handler to use to open this
        resource.

    resource_path : str
        Url to the physical location of the resource

    resource_kwargs : dict
        name/value pairs of additional kwargs to be
        passed to the handler to open this resource.

    """

    spec = StringField(required=True, unique=False)
    resource_path = StringField(required=True, unique=False)
    resource_kwargs = DictField(required=False)
    meta = {'indexes': ['-_id'], 'db_alias': ALIAS}


class Datum(Document):
    """
    Document to represent a single datum in a resource.

    There is a many-to-one mapping between Datum and Resource

    Parameters
    ----------

    resource : Resource or Resource.id
        Resource object

    datum_id : str
        Unique identifier for this datum.  This is the value stored in
        metadatastore and is the value passed to `retrieve` to get
        the data back out.

    datum_kwargs : dict
        dict with any kwargs needed to retrieve this specific datum from the
        resource.

    """
    resource = ReferenceField(Resource,
                              reverse_delete_rule=DENY,
                              required=True)
    datum_id = StringField(required=True, unique=True)
    datum_kwargs = DictField(required=False)
    meta = {'indexes': ['-_id', '-datum_id'], 'db_alias': ALIAS}
