# import base64
import copy
import base64
import requests
import fitz
import numpy as np
import cv2
import filetype
from collections import defaultdict
from PIL import Image
from typing import Any, Iterator, List, Mapping, Optional, Union
from llm_extract import init_logger


logger = init_logger(__name__)


def convert_base64(image):
    image_binary = cv2.imencode('.jpg', image)[1].tobytes()
    x = base64.b64encode(image_binary)
    return x.decode('ascii').replace('\n', '')


def transpdf2png(pdf_file):
    pdf_bytes = open(pdf_file, 'rb').read()
    pdf = fitz.Document(stream=pdf_bytes, filetype='pdf')
    dpis = [72, 144, 200]

    pdf_images = dict()
    for page in pdf:
        pix = None
        for dpi in dpis:
            pix = page.get_pixmap(dpi=dpi)
            if min(pix.width, pix.height) >= 2560: break

        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        # RGB to BGR
        img = np.array(img)[:, :, ::-1]
        img_name = "page_{:03d}".format(page.number)
        pdf_images[img_name] = img

    return pdf_images


class EllmExtract(object):
    def __init__(self, api_base_url: str = 'http://192.168.106.20:3502/v2/idp/idp_app/infer'):
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
                'det': 'general_text_det_v2',
                'recog': 'transformer-v2.8-gamma-faster',
                'ellm': 'ELLM'
            }
        }

    def predict_single_img(self, inp):
        """
        single image
        """
        scene = inp.pop('scene', 'doc')
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

    def predict(self, file_path, schema):
        """
        pdf
        """
        logger.info('ellm extract phase1: ellm extract')
        mime_type = filetype.guess(file_path).mime
        if mime_type.endswith('pdf'):
            file_type = 'pdf'
        elif mime_type.startswith('image'):
            file_type = 'img'
        else:
            raise ValueError(f"file type {file_type} is not support.")

        if file_type == 'img':
            kv_results = defaultdict(list)
            bytes_data = open(file_path, 'rb').read()
            b64data = base64.b64encode(bytes_data).decode()
            payload = {'b64_image': b64data, 'keys': schema}
            resp = self.predict_single_img(payload)

            if 'code' in resp and resp['code'] == 200:
                key_values = resp['result']['ellm_result']
            else:
                raise ValueError(f"ellm kv extract failed: {resp}")

            for key, value in key_values.items():
                kv_results[key] = value['text']

        elif file_type == 'pdf':
            pdf_images = transpdf2png(file_path)
            kv_results = defaultdict(list)
            for pdf_name in pdf_images:
                page = int(pdf_name.split('page_')[-1])

                b64data = convert_base64(pdf_images[pdf_name])
                payload = {'b64_image': b64data, 'keys': schema}
                resp = self.predict_single_img(payload)

                if 'code' in resp and resp['code'] == 200:
                    key_values = resp['result']['ellm_result']
                else:
                    raise ValueError(f"ellm kv extract failed: {resp}")

                for key, value in key_values.items():
                    # text_info = [{'value': text, 'page': int(page)} for text in value['text']]
                    # kv_results[key].extend(text_info)

                    for text in value['text']:
                        if text not in kv_results[key]:
                            kv_results[key].append(text)

        logger.info(f'ellm kv results: {kv_results}')
        return kv_results


if __name__ == '__main__':
    ellm_client = EllmExtract(api_base_url='http://192.168.106.20:3502/v2/idp/idp_app/infer')
    pdf_path = '/home/gulixin/workspace/datasets/huatai/流动资金借款合同_pdf/流动资金借款合同1.pdf'
    schema = '合同标题|合同编号|借款人|贷款人|借款金额'
    ellm_client.predict(pdf_path, schema)


