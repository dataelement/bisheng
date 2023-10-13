# import base64
import copy
import requests
import base64
from typing import Any, Iterator, List, Mapping, Optional, Union


class OCRClient(object):
    def __init__(self,
                 api_base_url: Optional[str] = None):
        # http://192.168.106.12:36001/v2/idp/idp_app/infer
        self.ep = api_base_url
        self.client = requests.Session()
        self.timeout = 10000
        self.params = {
            'sort_filter_boxes': True,
            'enable_huarong_box_adjust': True,
            'support_long_image_segment': True,
            'rotateupright': False,
        }

        self.scene_mapping = {
            'doc': {
                'det': 'general_text_det_mrcnn_v1.0',
                'recog': 'transformer-v2.8-gamma-faster'
            },
            'form': {
                'det': 'mrcnn-v5.1',
                'recog': 'transformer-v2.8-gamma-faster'
            },
            'hand': {
                'det': 'mrcnn-v5.1',
                'recog': 'transformer-hand-v1.16-faster'
            }
        }

    def predict(self, inp):
        scene = inp.pop('scene', 'form')
        b64_image = inp.pop('b64_image')
        params = copy.deepcopy(self.params)
        params.update(self.scene_mapping[scene])
        params.update(inp)

        req_data = {'data': [b64_image], 'param': params}

        try:
            r = self.client.post(url=self.ep,
                             json=req_data,
                             timeout=self.timeout)
            return r.json()
        except Exception as e:
            return {'status_code': 400, 'status_message': str(e)}

