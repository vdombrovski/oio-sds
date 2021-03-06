# Copyright (C) 2015-2017 OpenIO SAS, as part of OpenIO SDS
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 3.0 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library.

from oio.common.exceptions import ContentNotFound
from oio.common.exceptions import NotFound
from oio.common.utils import GeneratorIO
from oio.common.logger import get_logger
from oio.container.client import ContainerClient
from oio.content.plain import PlainContent
from oio.content.ec import ECContent
from oio.common.storage_method import STORAGE_METHODS


class ContentFactory(object):
    DEFAULT_DATASEC = "plain", {"nb_copy": "1", "distance": "0"}

    def __init__(self, conf, container_client=None, **kwargs):
        self.conf = conf
        self.logger = get_logger(conf)
        self.container_client = container_client or \
            ContainerClient(conf, logger=self.logger, **kwargs)

    def get(self, container_id, content_id, account=None,
            container_name=None):
        try:
            meta, chunks = self.container_client.content_locate(
                cid=container_id, content=content_id)
        except NotFound:
            raise ContentNotFound("Content %s/%s not found" % (container_id,
                                  content_id))

        chunk_method = meta['chunk_method']
        storage_method = STORAGE_METHODS.load(chunk_method)
        if not account or not container_name:
            container_info = self.container_client.container_get_properties(
                cid=container_id)['system']
            if not account:
                account = container_info['sys.account']
            if not container_name:
                container_name = container_info['sys.user.name']
        cls = ECContent if storage_method.ec else PlainContent
        return cls(self.conf, container_id, meta, chunks, storage_method,
                   account,
                   container_name,
                   container_client=self.container_client)

    def new(self, container_id, path, size, policy, account=None,
            container_name=None):
        meta, chunks = self.container_client.content_prepare(
            cid=container_id, path=path, size=size, stgpol=policy)

        chunk_method = meta['chunk_method']
        storage_method = STORAGE_METHODS.load(chunk_method)
        if not account or not container_name:
            container_info = self.container_client.container_get_properties(
                cid=container_id)['system']
            if not account:
                account = container_info['sys.account']
            if not container_name:
                container_name = container_info['sys.user.name']
        cls = ECContent if storage_method.ec else PlainContent
        return cls(self.conf, container_id, meta, chunks, storage_method,
                   account, container_name)

    def copy(self, origin, policy=None):
        if not policy:
            policy = origin.policy
        metadata = origin.metadata.copy()
        new_metadata, chunks = self.container_client.content_prepare(
            cid=origin.container_id,
            path=metadata['name'],
            size=metadata['length'],
            stgpol=policy)

        metadata['chunk_method'] = new_metadata['chunk_method']
        metadata['chunk_size'] = new_metadata['chunk_size']
        # We must use a new content_id since we change the data
        metadata['id'] = new_metadata['id']
        # We may want to keep the same version, but it is denied by meta2
        metadata['version'] = int(metadata['version']) + 1
        metadata['policy'] = new_metadata['policy']
        # FIXME: meta2 does not allow us to set ctime
        # and thus the object will appear as new.
        storage_method = STORAGE_METHODS.load(metadata['chunk_method'])

        cls = ECContent if storage_method.ec else PlainContent
        return cls(self.conf, origin.container_id,
                   metadata, chunks, storage_method,
                   origin.account, origin.container_name)

    def change_policy(self, container_id, content_id, new_policy):
        old_content = self.get(container_id, content_id)
        if old_content.policy == new_policy:
            return old_content

        new_content = self.copy(old_content, policy=new_policy)

        stream = old_content.fetch()
        new_content.create(GeneratorIO(stream))
        # the old content is automatically deleted because the new content has
        # the same name (but not the same id)
        return new_content
