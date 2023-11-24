# import base64
import copy
import base64
import requests
from typing import Any, Iterator, List, Mapping, Optional, Union


class ELLMClient(object):
    def __init__(self,
                 api_base_url: Optional[str] = None):
        self.ep = api_base_url
        self.client = requests.Session()
        self.timeout = 10000
        self.params = {
            'sort_filter_boxes': True,
            'enable_huarong_box_adjust': True,
            'support_long_image_segment': True,
            'checkbox': ['std_checkbox'],
            'rotateupright': True
        }

        self.scene_mapping = {
            'doc': {
                'det': 'general_text_det_mrcnn_v1.0',
                'recog': 'transformer-v2.8-gamma-faster',
                'ellm': 'ELLM'
            },
            'form': {
                'det': 'mrcnn-v5.1',
                'recog': 'transformer-v2.8-gamma-faster',
                'ellm': 'ELLM'
            },
            'hand': {
                'det': 'mrcnn-v5.1',
                'recog': 'transformer-hand-v1.16-faster',
                'ellm': 'ELLM'
            }
        }

    def predict(self, inp):
        scene = inp.pop('scene', 'form')
        b64_image = inp.pop('b64_image')
        ellm_schema = inp.pop('keys')
        params = copy.deepcopy(self.params)
        params.update(self.scene_mapping[scene])
        params.update({'ellm_schema': ellm_schema})

        req_data = {'data': [b64_image], 'param': params}

        try:
            r = self.client.post(url=self.ep,
                                 json=req_data,
                                 timeout=self.timeout)
            return r.json()
        except Exception as e:
            return {'status_code': 400, 'status_message': str(e)}
