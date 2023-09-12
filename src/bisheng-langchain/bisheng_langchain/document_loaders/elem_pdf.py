# flake8: noqa
"""Loads PDF with semantic splilter."""
import io
import json
import logging
import os
import re
import tempfile
import time
from abc import ABC
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Union
from urllib.parse import urlparse

import fitz
import numpy as np
import pypdfium2
import requests
from bisheng_langchain.document_loaders.parsers import LayoutParser
from langchain.docstore.document import Document
from langchain.document_loaders.blob_loaders import Blob
from langchain.document_loaders.pdf import BasePDFLoader
from shapely import Polygon
from shapely import box as Rect

RE_MULTISPACE_INCLUDING_NEWLINES = re.compile(pattern=r'\s+', flags=re.DOTALL)


def merge_rects(bboxes):
    x0 = np.min(bboxes[:, 0])
    y0 = np.min(bboxes[:, 1])
    x1 = np.max(bboxes[:, 2])
    y1 = np.max(bboxes[:, 3])
    return [x0, y0, x1, y1]


def norm_rect(bbox):
    x0 = np.min([bbox[0], bbox[2]])
    x1 = np.max([bbox[0], bbox[2]])
    y0 = np.min([bbox[1], bbox[3]])
    y1 = np.max([bbox[1], bbox[3]])
    return np.asarray([x0, y0, x1, y1])


def find_max_continuous_seq(arr):
    n = len(arr)
    max_info = (0, 1)
    for i in range(n):
        m = 1
        for j in range(i + 1, n):
            if arr[j] - arr[j - 1] == 1:
                m += 1
            else:
                break

        if m > max_info[1]:
            max_info = (i, m)

    max_info = (max_info[0] + arr[0], max_info[1])
    return max_info


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


def join_lines(texts, is_table=False):
    if is_table:
        return '\n'.join(texts)

    flags = []
    PUNC_SET = set(['.', ',', ';', '?', '!'])
    for text in texts:
        flags.append(np.all([t.isalnum() for t in text.rsplit(' ', 5)]))

    if np.all(flags):
        t0 = texts[0]
        for t in texts[1:]:
            if t0[-1] == '-':
                t0 = t0[:-1] + t
            elif t0[-1].isalnum() and t[0].isalnum():
                t0 += ' ' + t
            elif t0[-1] in PUNC_SET or t[0] in PUNC_SET:
                t0 += ' ' + t
            else:
                t0 += t
        return t0
    else:
        return ''.join(texts)


class Segment:

    def __init__(self, seg):
        self.whole = seg
        self.segs = []

    @staticmethod
    def is_align(seg0, seg1, delta=5, mode=0):
        # mode=0 edge align
        # mode=1, edge align or center align
        res = Segment.contain(seg0, seg1)
        if not res:
            return False
        else:
            if mode == 1:
                r1 = seg1[0] - seg0[0] <= delta or seg0[1] - seg1[1] <= delta
                c0 = (seg0[0] + seg0[1]) / 2
                c1 = (seg1[0] + seg1[1]) / 2
                r2 = abs(c1 - c0) <= delta
                return r1 or r2
            else:
                return seg1[0] - seg0[0] <= delta or seg0[1] - seg1[1] <= delta

    @staticmethod
    def contain(seg0, seg1):
        return seg0[0] <= seg1[0] and seg0[1] >= seg1[0]

    @staticmethod
    def overlap(seg0, seg1):
        max_x0 = max(seg0[0], seg1[0])
        min_x1 = min(seg0[1], seg1[1])
        return max_x0 < min_x1

    def _merge(self, segs):
        x0s = [s[0] for s in segs]
        x1s = [s[1] for s in segs]
        return (np.min(x0s), np.max(x1s))

    def add(self, seg):
        if not self.segs:
            self.segs.append(seg)
        else:
            overlaps = []
            non_overlaps = []
            for seg0 in self.segs:
                if Segment.overlap(seg0, seg):
                    overlaps.append(seg0)
                else:
                    non_overlaps.append(seg0)

            if not overlaps:
                self.segs.append(seg)
            else:
                overlaps.append(seg)
                new_seg = self._merge(overlaps)
                non_overlaps.append(new_seg)
                self.segs = non_overlaps

    def get_free_segment(self, incr_margin=True, margin_threshold=10):
        sorted_segs = sorted(self.segs, key=lambda x: x[0])
        n = len(sorted_segs)
        free_segs = []
        if incr_margin:
            if n > 0:
                seg_1st = sorted_segs[0]
                if (seg_1st[0] - self.whole[0]) > margin_threshold:
                    free_segs.append((self.whole[0], seg_1st[0]))

                seg_last = sorted_segs[-1]
                if (self.whole[1] - seg_last[1]) > margin_threshold:
                    free_segs.append((seg_last[1], self.whole[1]))

        for i in range(n - 1):
            x0 = sorted_segs[i][1]
            x1 = sorted_segs[i + 1][0]
            free_segs.append((x0, x1))

        return free_segs


class PDFWithSemanticLoader(BasePDFLoader):
    """Loads a PDF with pypdf and chunks at character level.

    Loader also stores page numbers in metadata.
    """

    def __init__(self,
                 file_path: str,
                 password: Optional[Union[str, bytes]] = None,
                 layout_api_key: str = None,
                 layout_api_url: str = None,
                 is_join_table: bool = True,
                 with_columns: bool = False,
                 support_rotate: bool = False,
                 text_elem_sep: str = '\n',
                 start: int = 0,
                 n: int = None,
                 html_output_file: str = None,
                 verbose: bool = False) -> None:
        """Initialize with a file path."""
        self.layout_parser = LayoutParser(api_key=layout_api_key,
                                          api_base_url=layout_api_url)
        self.with_columns = with_columns
        self.is_join_table = is_join_table
        self.support_rotate = support_rotate
        self.start = start
        self.n = n
        self.html_output_file = html_output_file
        self.verbose = verbose
        self.text_elem_sep = text_elem_sep
        super().__init__(file_path)

    def _get_image_blobs(self, fitz_doc, pdf_reader, n=None, start=0):
        blobs = []
        pages = []
        if not n:
            n = fitz_doc.page_count
        for pg in range(start, start + n):
            bytes_img = None
            page = fitz_doc.load_page(pg)
            pages.append(page)
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
        return blobs, pages

    def _allocate_semantic(self, page, layout):
        class_name = ['印章', '图片', '标题', '段落', '表格', '页眉', '页码', '页脚']
        effective_class_inds = [3, 4, 5, 999]
        non_conti_class_ids = [6, 7, 8]
        TEXT_ID = 4
        TABLE_ID = 5

        textpage = page.get_textpage()
        blocks = textpage.extractBLOCKS()

        if self.support_rotate:
            rotation_matrix = np.asarray(page.rotation_matrix).reshape((3, 2))
            c1 = (rotation_matrix[0, 0] - 1) <= 1e-6
            c2 = (rotation_matrix[1, 1] - 1) <= 1e-6
            is_rotated = c1 and c2
            # print('c1/c2', c1, c2)
            if is_rotated:
                new_blocks = []
                for b in blocks:
                    bbox = np.asarray([b[0], b[1], b[2], b[3]])
                    aug_bbox = bbox.reshape((-1, 2))
                    padding = np.ones((len(aug_bbox), 1))
                    aug_bbox = np.hstack([aug_bbox, padding])
                    bb = np.dot(aug_bbox, rotation_matrix).reshape(-1)
                    bb = norm_rect(bb)
                    info = (bb[0], bb[1], bb[2], bb[3], b[4], b[5], b[6])
                    new_blocks.append(info)

                blocks = new_blocks

        if not self.with_columns:
            blocks = order_by_tbyx(blocks)

        # print('---ori blocks---')
        # for b in blocks:
        #     print(b)

        IMG_BLOCK_TYPE = 1
        text_ploys = []
        text_rects = []
        texts = []
        for b in blocks:
            if b[-1] != IMG_BLOCK_TYPE:
                text = re.sub(RE_MULTISPACE_INCLUDING_NEWLINES, ' ', b[4]
                              or '').strip()
                if text:
                    texts.append(text)
                    text_ploys.append(Rect(b[0], b[1], b[2], b[3]))
                    text_rects.append([b[0], b[1], b[2], b[3]])
        text_rects = np.asarray(text_rects)
        texts = np.asarray(texts)

        semantic_polys = []
        semantic_labels = []

        layout_info = json.loads(layout.page_content)
        for info in layout_info:
            bbs = info['bbox']
            coords = ((bbs[0], bbs[1]), (bbs[2], bbs[3]), (bbs[4], bbs[5]),
                      (bbs[6], bbs[7]))
            semantic_polys.append(Polygon(coords))
            semantic_labels.append(info['category_id'])

        # caculate containing overlap
        sem_cnt = len(semantic_polys)
        texts_cnt = len(text_ploys)
        contain_matrix = np.zeros((sem_cnt, texts_cnt))
        for i in range(sem_cnt):
            for j in range(texts_cnt):
                inter = semantic_polys[i].intersection(text_ploys[j]).area
                contain_matrix[i, j] = inter * 1.0 / text_ploys[j].area

        # print('----------------containing matrix--------')
        # for r in contain_matrix.tolist():
        #     print([round(r_, 2) for r_ in r])

        # print('---text---')
        # for t in texts:
        #     print(t)

        # merge continuous text block by the containing matrix
        CONTRAIN_THRESHOLD = 0.70
        contain_info = []
        for i in range(sem_cnt):
            ind = np.argwhere(contain_matrix[i, :] > CONTRAIN_THRESHOLD)[:, 0]
            if len(ind) == 0: continue
            label = semantic_labels[i]
            if label in non_conti_class_ids:
                n = len(ind)
                contain_info.append((None, None, n, label, ind))
            else:
                start, n = find_max_continuous_seq(ind)
                if n >= 1:
                    contain_info.append((start, start + n, n, label, None))

        contain_info = sorted(contain_info, key=lambda x: x[2], reverse=True)
        mask = np.zeros(texts_cnt)
        new_block_info = []
        for info in contain_info:
            start, end, n, label, ind = info
            if label in non_conti_class_ids and np.all(mask[ind] == 0):
                rect = merge_rects(text_rects[ind])
                ori_orders = [blocks[i][-2] for i in ind]
                ts = texts[ind]
                rs = text_rects[ind]
                ord_ind = np.min(ori_orders)
                mask[ind] = 1
                new_block_info.append(
                    (rect[0], rect[1], rect[2], rect[3], ts, rs, ord_ind))

            elif np.all(mask[start:end] == 0):
                rect = merge_rects(text_rects[start:end])
                ori_orders = [blocks[i][-2] for i in range(start, end)]
                arg_ind = np.argsort(ori_orders)
                # print('ori_orders', ori_orders, arg_ind)
                ord_ind = np.min(ori_orders)

                ts = texts[start:end]
                rs = text_rects[start:end]
                if label == TABLE_ID:
                    ts = ts[arg_ind]
                    rs = rs[arg_ind]

                mask[start:end] = 1
                new_block_info.append(
                    (rect[0], rect[1], rect[2], rect[3], ts, rs, ord_ind))

        for i in range(texts_cnt):
            if mask[i] == 0:
                b = blocks[i]
                r = np.asarray([b[0], b[1], b[2], b[3]])
                ord_ind = b[-2]
                new_block_info.append(
                    (b[0], b[1], b[2], b[3], [texts[i]], [r], ord_ind))

        if self.with_columns:
            new_blocks = sorted(new_block_info, key=lambda x: x[-1])
        else:
            new_blocks = order_by_tbyx(new_block_info)

        # print('\n\n---new blocks---')
        # for idx, b in enumerate(new_blocks):
        #     print(idx, b)

        text_ploys = []
        texts = []
        for b in new_blocks:
            texts.append(b[4])
            text_ploys.append(Rect(b[0], b[1], b[2], b[3]))

        # caculate overlap
        sem_cnt = len(semantic_polys)
        texts_cnt = len(text_ploys)
        overlap_matrix = np.zeros((sem_cnt, texts_cnt))
        for i in range(sem_cnt):
            for j in range(texts_cnt):
                inter = semantic_polys[i].intersection(text_ploys[j]).area
                union = semantic_polys[i].union(text_ploys[j]).area
                overlap_matrix[i, j] = (inter * 1.0) / union

        # print('---overlap_matrix---')
        # for r in overlap_matrix:
        #     print([round(r_, 3) for r_ in r])

        # allocate label
        OVERLAP_THRESHOLD = 0.2
        texts_labels = []
        DEF_SEM_LABEL = 999
        for j in range(texts_cnt):
            ind = np.argwhere(overlap_matrix[:, j] > OVERLAP_THRESHOLD)[:, 0]
            if len(ind) == 0:
                sem_label = DEF_SEM_LABEL
            else:
                c = Counter([semantic_labels[i] for i in ind])
                items = c.most_common()
                sem_label = items[0][0]
                if len(items) > 1 and TEXT_ID in dict(items):
                    sem_label = TEXT_ID

            texts_labels.append(sem_label)

        # print(texts_labels)
        # filter the unused element
        filtered_blocks = []
        for label, b in zip(texts_labels, new_blocks):
            if label in effective_class_inds:
                text = join_lines(b[4], label == TABLE_ID)
                filtered_blocks.append(
                    (b[0], b[1], b[2], b[3], text, b[5], label))

        # print('---filtered_blocks---')
        # for b in filtered_blocks:
        #     print(b)

        return filtered_blocks

    def _divide_blocks_into_groups(self, blocks):
        # support only pure two columns layout, each has same width
        rects = np.asarray([[b[0], b[1], b[2], b[3]] for b in blocks])
        min_x0 = np.min(rects[:, 0])
        max_x1 = np.max(rects[:, 2])
        root_seg = (min_x0, max_x1)
        root_pc = (min_x0 + max_x1) / 2
        root_offset = 20
        center_seg = (root_pc - root_offset, root_pc + root_offset)

        segment = Segment(root_seg)
        for r in rects:
            segment.add((r[0], r[2]))

        COLUMN_THRESHOLD = 0.90
        CENTER_GAP_THRESHOLD = 0.90
        free_segs = segment.get_free_segment()
        columns = []
        if len(free_segs) == 1 and len(segment.segs) == 2:
            free_seg = free_segs[0]
            seg0 = segment.segs[0]
            seg1 = segment.segs[1]
            cover = seg0[1] - seg0[0] + seg1[1] - seg1[0]
            c0 = cover / (root_seg[1] - root_seg[0])
            c1 = Segment.contain(center_seg, free_seg)
            if c0 > COLUMN_THRESHOLD and c1:
                # two columns
                columns.extend([seg0, seg1])

        groups = [blocks]
        if columns:
            groups = [[] for _ in columns]
            for b, r in zip(blocks, rects):
                column_ind = 0
                cand_seg = (r[0], r[2])
                for i, seg in enumerate(columns):
                    if Segment.contain(seg, cand_seg):
                        column_ind = i
                        break
                groups[i].append(b)

        return groups

    def _allocate_continuous(self, groups):
        g_bound = []
        groups = [g for g in groups if g]
        for blocks in groups:
            arr = [[b[0], b[1], b[2], b[3]] for b in blocks]
            bboxes = np.asarray(arr)
            g_bound.append(np.asarray(merge_rects(bboxes)))

        LINE_FULL_THRESHOLD = 0.80
        START_THRESHOLD = 0.8
        SIMI_HEIGHT_THRESHOLD = 0.3
        SIMI_WIDTH_THRESHOLD = 0.3

        TEXT_ID = 4
        TABLE_ID = 5

        def _get_elem(blocks, is_first=True):
            if not blocks:
                return (None, None, None, None, None)
            if is_first:
                b1 = blocks[0]
                b1_label = b1[-1]
                r1 = b1[5][0]
                r1_w = r1[2] - r1[0]
                r1_h = r1[3] - r1[1]
                return (b1, b1_label, r1, r1_w, r1_h)
            else:
                b0 = blocks[-1]
                b0_label = b0[-1]
                r0 = b0[5][-1]
                r0_w = r0[2] - r0[0]
                r0_h = r0[3] - r0[1]
                return (b0, b0_label, r0, r0_w, r0_h)

        b0, b0_label, r0, r0_w, r0_h = _get_elem(groups[0], False)
        g0 = g_bound[0]

        for i in range(1, len(groups)):
            b1, b1_label, r1, r1_w, r1_h = _get_elem(groups[i], True)
            g1 = g_bound[i]

            # print('\n_allocate_continuous:')
            # print(b0, b0_label, b1, b1_label)

            if b0_label and b0_label == b1_label and b0_label == TEXT_ID:
                c0 = r0_w / (g0[2] - g0[0])
                c1 = (r1[0] - g1[0]) / r1_h
                c2 = np.abs(r0_h - r1_h) / r1_h

                # print('\n\n---conti texts---')
                # print(b0_label, c0, c1, c2,
                #       b0, b0_label, r0, r0_w, r0_h,
                #       b1, b1_label, r1, r1_w, r1_h)

                if (c0 > LINE_FULL_THRESHOLD and c1 < START_THRESHOLD
                        and c2 < SIMI_HEIGHT_THRESHOLD):
                    new_text = join_lines([b0[4], b1[4]])
                    new_block = (b0[0], b0[1], b0[2], b0[3], new_text, b0[5],
                                 b0[6])
                    groups[i - 1][-1] = new_block
                    groups[i].pop(0)

            elif (self.is_join_table and b0_label and b0_label == b1_label
                  and b0_label == TABLE_ID):
                c0 = (r1_w - r0_w) / r1_h
                if c0 < SIMI_WIDTH_THRESHOLD:
                    new_text = join_lines([b0[4], b1[4]], True)
                    new_block = (b0[0], b0[1], b0[2], b0[3], new_text, b0[5],
                                 b0[6])
                    groups[i - 1][-1] = new_block
                    groups[i].pop(0)

            b0, b0_label, r0, r0_w, r0_h = _get_elem(groups[i], False)

        return groups

    def save_to_html(self, groups, output_file):
        styles = [
            'style="background-color: #EBEBEB;"',
            'style="background-color: #ABBAEA;"'
        ]
        idx = 0
        table_style = 'style="border:1px solid black;"'

        with open(output_file, 'w') as fout:
            for blocks in groups:
                for b in blocks:
                    if b[-1] == 3:
                        text = f'<h1>{b[4]}</h1>'
                    elif b[-1] == 4:
                        text = f'<p {styles[idx % 2]}>{b[4]}</p>'
                        idx += 1
                    elif b[-1] == 5:
                        rows = b[4].split('\n')
                        content = []
                        for r in rows:
                            content.append(
                                f'<tr><td {table_style}>{r}</td></tr>')
                        elem_text = '\n'.join(content)
                        text = f'<table {table_style}>{elem_text}</table>'
                    else:
                        text = f'<p {styles[idx % 2]}>{b[4]}</p>'
                        idx += 1

                    fout.write(text + '\n')

    def _save_to_document(self, groups):
        TITLE_ID = 3
        TEXT_ID = 4
        TABLE_ID = 5
        content_page = []
        is_first_elem = True
        for blocks in groups:
            for b in blocks:
                if is_first_elem:
                    content_page.append(b[4])
                    is_first_elem = False
                else:
                    label, text = b[-1], b[4]
                    if label == TITLE_ID:
                        content_page.append('\n\n' + text)
                    else:
                        content_page.append(self.text_elem_sep + text)

        return ''.join(content_page)

    def load(self) -> List[Document]:
        """Load given path as pages."""
        blob = Blob.from_path(self.file_path)
        start = self.start
        groups = []
        with blob.as_bytes_io() as file_path:
            fitz_doc = fitz.open(file_path)
            pdf_doc = pypdfium2.PdfDocument(file_path, autoclose=True)
            max_page = fitz_doc.page_count - start
            n = self.n if self.n else max_page
            n = min(n, max_page)

            tic = time.time()
            if self.verbose:
                print(f'{n} pages need be processed...')

            for idx in range(start, start + n):
                blobs, pages = self._get_image_blobs(fitz_doc, pdf_doc, 1, idx)
                layout = self.layout_parser.parse(blobs[0])[0]
                blocks = self._allocate_semantic(pages[0], layout)
                if not blocks: continue

                if self.with_columns:
                    sub_groups = self._divide_blocks_into_groups(blocks)
                    groups.extend(sub_groups)
                else:
                    groups.append(blocks)

                if self.verbose:
                    count = idx - start + 1
                    if count % 50 == 0:
                        elapse = round(time.time() - tic, 2)
                        tic = time.time()
                        print(f'process {count} pages used {elapse}sec...')

        groups = self._allocate_continuous(groups)

        if self.html_output_file:
            self.save_to_html(groups, self.html_output_file)
            return []

        page_content = self._save_to_document(groups)
        meta = {'source': os.path.basename(self.file_path)}
        doc = Document(page_content=page_content, metadata=meta)
        return [doc]
