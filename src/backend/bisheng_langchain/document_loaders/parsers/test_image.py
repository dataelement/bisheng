# flake8: noqa
import io
import json
import logging
import os
import random
import tempfile
import time
from abc import ABC
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Union
from urllib.parse import urlparse

import cv2
import fitz
import numpy as np
import pypdfium2
import requests
from image import LayoutParser
from langchain.document_loaders.blob_loaders import Blob


def norm_rect(bbox):
    x0 = np.min([bbox[0], bbox[2]])
    x1 = np.max([bbox[0], bbox[2]])
    y0 = np.min([bbox[1], bbox[3]])
    y1 = np.max([bbox[1], bbox[3]])
    return np.asarray([x0, y0, x1, y1])


def merge_rects(bboxes):
    x0 = np.min(bboxes[:, 0])
    y0 = np.min(bboxes[:, 1])
    x1 = np.max(bboxes[:, 2])
    y1 = np.max(bboxes[:, 3])
    return [x0, y0, x1, y1]


def get_image_blobs(pages, pdf_reader, n, start=0):
    blobs = []
    for pg in range(start, start + n):
        bytes_img = None
        page = pages.load_page(pg)
        mat = fitz.Matrix(1, 1)
        try:
            pm = page.get_pixmap(matrix=mat, alpha=False)
            bytes_img = pm.getPNGData()
        except Exception:
            # some pdf input cannot get render image from fitz
            page = pdf_reader.get_page(pg)
            pil_image = page.render().to_pil()
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            bytes_img = img_byte_arr.getvalue()

            blobs.append(Blob(data=bytes_img))
    return blobs


def test():
    file_path = './data/达梦数据库招股说明书_test_v1.pdf'
    blob = Blob.from_path(file_path)
    pages = None
    image_blobs = []
    with blob.as_bytes_io() as file_path:
        pages = fitz.open(file_path)
        pdf_reader = pypdfium2.PdfDocument(file_path, autoclose=True)
        image_blobs = get_image_blobs(pages, pdf_reader)

    assert len(image_blobs) == pages.page_count
    layout = LayoutParser()
    res = layout.parse(image_blobs[0])


def draw_polygon(image, bbox, text=None, color=(255, 0, 0), thickness=1):
    bbox = bbox.astype(np.int32)
    is_rect = bbox.shape[0] == 4
    if is_rect:
        start_point = (bbox[0], bbox[1])
        end_point = (bbox[2], bbox[3])
        image = cv2.rectangle(image, start_point, end_point, color, thickness)
    else:
        polys = [bbox.astype(np.int32).reshape((-1, 1, 2))]
        cv2.polylines(image, polys, True, color=color, thickness=thickness)
        start_point = (polys[0][0, 0, 0], polys[0][0, 0, 1])

    if text:
        fontFace = cv2.FONT_HERSHEY_SIMPLEX
        fontScale = 0.5
        color = (0, 0, 255)
        image = cv2.putText(image, text, start_point, fontFace, fontScale,
                            color, 1)

    return image


def test_vis():
    # file_path = './data/达梦数据库招股说明书_test_v1.pdf'
    file_path = './data/pdf_input/《中国药典》2020年版 一部.pdf'
    output_prefix = 'zhongguoyaodian_2020_v1'
    start, end, n = 70, 80, 10
    blob = Blob.from_path(file_path)
    pages = None
    image_blobs = []
    with blob.as_bytes_io() as file_path:
        pages = fitz.open(file_path)
        pdf_reader = pypdfium2.PdfDocument(file_path, autoclose=True)
        image_blobs = get_image_blobs(pages, pdf_reader, n, start)

    assert len(image_blobs) == n

    for i, blob in enumerate(image_blobs):
        idx = i + start
        # blob = image_blobs[2]
        layout = LayoutParser()
        out = layout.parse(blob)
        res = json.loads(out[0].page_content)
        bboxes = []
        labels = []
        for r in res:
            bboxes.append(r['bbox'])
            labels.append(str(r['category_id']))

        bboxes = np.asarray(bboxes)

        bytes_arr = np.frombuffer(blob.as_bytes(), dtype=np.uint8)
        image = cv2.imdecode(bytes_arr, flags=1)
        for bbox, text in zip(bboxes, labels):
            image = draw_polygon(image, bbox, text)

        outf = f'./data/{output_prefix}_layout_p{idx+1}_vis.png'
        cv2.imwrite(outf, image)


def order_by_tbyx(block_info, th=10):
    """
      block_info: [(b0, b1, b2, b3, text, x, y)+]
      th: threshold of the position threshold
    """
    # sort using y1 first and then x1
    res = sorted(block_info, key=lambda b: (b[1], b[0]))
    for i in range(len(res) - 1):
        for j in range(i, 0, -1):
            # restore the order using the
            if (abs(res[j + 1][1] - res[j][1]) < th
                    and (res[j + 1][0] < res[j][0])):
                tmp = deepcopy(res[j])
                res[j] = deepcopy(res[j + 1])
                res[j + 1] = deepcopy(tmp)
            else:
                break
    return res


def test_vis2():
    # file_path = './data/达梦数据库招股说明书_test_v1.pdf'
    file_path = './data/pdf_input/达梦数据库招股说明书.pdf'
    output_prefix = 'dameng_pageblock'

    start = 0
    end = 10
    n = end - start
    blob = Blob.from_path(file_path)
    pages = None
    image_blobs = []
    with blob.as_bytes_io() as file_path:
        pages = fitz.open(file_path)
        pdf_reader = pypdfium2.PdfDocument(file_path, autoclose=True)
        image_blobs = get_image_blobs(pages, pdf_reader, n, start)

    assert len(image_blobs) == pages.page_count

    for i, blob in enumerate(image_blobs):
        idx = i + start
        page = pages.load_page(idx)

        rect = page.rect
        print('rect', rect)
        o = 10
        b0 = np.asarray([rect.x0 + o, rect.y0 + o, rect.x1 - o, rect.y1 - o])

        bytes_arr = np.frombuffer(blob.as_bytes(), dtype=np.uint8)
        image = cv2.imdecode(bytes_arr, flags=1)

        image = draw_polygon(image, b0, '0.0')

        textpage = page.get_textpage()
        blocks = textpage.extractBLOCKS()
        IMG_BLOCK_TYPE = 1

        # blocks = order_by_tbyx(blocks)
        bboxes = []
        for off, b in enumerate(blocks):
            label = 'text' if b[-1] != IMG_BLOCK_TYPE else 'image'
            label = f'{label}-{off}'
            print('block', b, label)
            bbox = np.asarray([b[0], b[1], b[2], b[3]])
            bboxes.append(bbox)

            image = draw_polygon(image, bbox, label)

        if bboxes:
            b1 = merge_rects(np.asarray(bboxes))
            b1 = np.asarray(b1)
            image = draw_polygon(image, b1, '0.1')

        outf = f'./data/{output_prefix}_p{idx}_vis.png'
        cv2.imwrite(outf, image)


def test_vis3():
    file_path = './data/pdf_input/《中国药典》2020年版 一部.pdf'

    start = 50
    end = 60
    n = end - start
    output_prefix = 'zhongguoyaodian_2020_v1'

    blob = Blob.from_path(file_path)
    pages = None
    image_blobs = []
    with blob.as_bytes_io() as file_path:
        pages = fitz.open(file_path)
        pdf_reader = pypdfium2.PdfDocument(file_path, autoclose=True)
        image_blobs = get_image_blobs(pages, pdf_reader, n, start=50)

    assert len(image_blobs) == n

    for i, blob in enumerate(image_blobs):
        idx = i + start
        page = pages.load_page(idx)

        rect = page.rect
        print('rect', rect)
        o = 10
        b0 = np.asarray([rect.x0 + o, rect.y0 + o, rect.x1 - o, rect.y1 - o])

        bytes_arr = np.frombuffer(blob.as_bytes(), dtype=np.uint8)
        image = cv2.imdecode(bytes_arr, flags=1)

        image = draw_polygon(image, b0, '0.0')

        rotation_matrix = np.asarray(page.rotation_matrix).reshape((3, 2))
        c1 = (rotation_matrix[0, 0] - 1) <= 1e-6
        c2 = (rotation_matrix[1, 1] - 1) <= 1e-6
        is_rotated = c1 and c2

        textpage = page.get_textpage()
        blocks = textpage.extractBLOCKS()
        IMG_BLOCK_TYPE = 1

        # blocks = order_by_tbyx(blocks)
        bboxes = []
        for off, b in enumerate(blocks):
            label = 'text' if b[-1] != IMG_BLOCK_TYPE else 'image'
            label = f'{label}-{off}'
            print('block', b, label)
            bbox = np.asarray([b[0], b[1], b[2], b[3]])

            aug_bbox = bbox.reshape((-1, 2))
            padding = np.ones((len(aug_bbox), 1))
            aug_bbox = np.hstack([aug_bbox, padding])
            new_bbox = np.dot(aug_bbox, rotation_matrix).reshape(-1)

            new_bbox = norm_rect(new_bbox)

            print('new_bboxes', new_bbox)
            bboxes.append(new_bbox)

            image = draw_polygon(image, new_bbox, label)

        print(bboxes)
        if bboxes:
            b1 = merge_rects(np.asarray(bboxes))
            b1 = np.asarray(b1)
            image = draw_polygon(image, b1, '0.1')

        outf = f'./data/{output_prefix}_p{idx}_vis.png'
        cv2.imwrite(outf, image)


# test_vis3()
# test_vis2()
test_vis()
# test()
