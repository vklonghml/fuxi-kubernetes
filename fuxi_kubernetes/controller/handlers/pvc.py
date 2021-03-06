# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy

from oslo_log import log as logging

from fuxi_kubernetes import clients
from fuxi_kubernetes import config
from fuxi_kubernetes import constants
from fuxi_kubernetes import exceptions as exc
from fuxi_kubernetes.handlers import k8s_base

LOG = logging.getLogger(__name__)

PV_TEMPLATE = {
    'kind': 'PersistentVolume',
    'spec': {
        'claimRef': {
            'namespace': 'default',
            'name': 'template',
        },
        'accessModes': ['ReadWriteMany'],
        'hostPath': {
            'path': '/tmp'
        },
        'capacity': {
            'storage': '1Gi'
        }
    },
    'apiVersion': 'v1',
    'metadata': {
        'name': 'pv0001',
        'annotations': {
            constants.FUXI_STORAGE_PREFIX: 'fuxi-kubernetes'
        }
    }
}


class PVCHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_PVC

    def __init__(self):
        pass

    def on_present(self, pvc):
        LOG.debug("on_present watch pvc: %s", pvc)
        if not self._is_fuxi_kubernetes(pvc):
            return
        if pvc['status']['phase'] != 'Bound':
            fuxi = clients.get_fuxi_client()
            data = {'Name': pvc['metadata']['name']}
            size = self._get_size(pvc)
            if size is not None:
                data.update({'Opts': {'size': size.strip('Gi')}})
            try:
                fuxi.create(data)
            except exc.FuxiClientException as e:
                LOG.error("fuxi create volume failed with error: %s", e)
                raise
            k8s = clients.get_kubernetes_client()
            try:
                pv_temp = self._generate_pv_template(pvc)
                pv_url = constants.K8S_API_BASE + '/persistentvolumes'
                k8s.post(pv_url, pv_temp)
            except exc.K8sClientException as e:
                LOG.error("create pvc failed with error: %s", e)
                fuxi.delete(data)
                raise

    def on_deleted(self, pvc):
        LOG.debug("on_deleted watch pvc: %s", pvc)
        if not self._is_fuxi_kubernetes(pvc):
            return
        if pvc['status']['phase'] == 'Bound':
            k8s = clients.get_kubernetes_client()
            pv_path = constants.K8S_API_BASE + "/persistentvolumes/" + \
                pvc['spec']['volumeName']
            try:
                pv_status = k8s.get(pv_path)
            except exc.K8sClientException as e:
                LOG.error("get pvc failed with error: %s", e)
                raise
            # if pv_status['metadata']['annotations'][constants.
            # FUXI_ANNOTATION_PREFIX] == 'fuxi-kubernetes'\
            if pv_status['spec']['claimRef']['name'] == \
                    pvc['metadata']['name']:
                try:
                    fuxi = clients.get_fuxi_client()
                    data = {'Name': pvc['spec']['volumeName']}
                    fuxi.delete(data)
                except exc.FuxiClientException as e:
                    LOG.error("fuxi delete volume failed with error: %s", e)
                    raise
                try:
                    pv_path = constants.K8S_API_BASE + "/persistentvolumes/" + \
                        pvc['spec']['volumeName']
                    k8s.delete(pv_path)
                except exc.K8sClientException as e:
                    LOG.error("delete pvc failed with error: %s", e)
                    raise

    def _get_size(self, pvc):
        try:
            return pvc['spec']['resources']['requests']['storage']
        except KeyError:
            return None

    def _generate_pv_template(self, pvc):
        pv_temp = copy.deepcopy(PV_TEMPLATE)
        pv_temp['spec']['claimRef']['name'] = pvc['metadata']['name']
        pv_temp['spec']['claimRef']['namespace'] = \
            pvc['metadata']['namespace']
        pv_temp['spec']['accessModes'] = pvc['spec']['accessModes']
        pv_temp['spec']['hostPath']['path'] = \
            config.CONF.kubernetes.volume_mount + pvc['metadata']['uid']
        pv_temp['spec']['capacity']['storage'] = \
            pvc['spec']['resources']['requests']['storage']
        pv_temp['metadata']['name'] = pvc['metadata']['name']
        return pv_temp

    def _is_fuxi_kubernetes(self, pvc):
        try:
            return (pvc['metadata']['annotations']
                    [constants.FUXI_STORAGE_PREFIX] == 'fuxi-kubernetes')
        except KeyError:
            return False
