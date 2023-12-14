# import os
# import tempfile
# from pathlib import Path
# from urllib.parse import unquote, urlparse

# import requests
# from bisheng.utils.minio_client import mino_client
# from bisheng.utils.util import _is_valid_url
# from docx import Document


# def find_lcs(str1, str2):
#     lstr1 = len(str1)
#     lstr2 = len(str2)
#     record = [[0 for i in range(lstr2 + 1)] for j in range(lstr1 + 1)]  # 多一位
#     maxNum = 0
#     p = 0
#     for i in range(lstr1):
#         for j in range(lstr2):
#             if str1[i] == str2[j]:
#                 record[i + 1][j + 1] = record[i][j] + 1
#                 if record[i + 1][j + 1] > maxNum:
#                     maxNum = record[i + 1][j + 1]
#                     p = i + 1

#     return str1[p - maxNum: p], maxNum


# class DocxTemplateRender(object):
#     def __init__(self, filepath):
#         self.filepath = filepath

#     def find_all_positions(text, key_start, key_end):
#         start = 0
#         while start < len(text):
#             start_position = text.find(key_start, start)
#             if start_position == -1:  # sub not found anymore
#                 return
#             else:
#                 end_position = text.find(key_end, start_position+2)
#                 if end_position == -1:   # sub not end
#                     return [start_position, end_position]
#             yield [start_position, end_position]
#             start = end_position + 2  # move to next position

#     def render(self, template_def):
#         doc = Document(self.filepath)
#         # Logics:
#         # key_text: "yy{{请输入公司1的完整名称}}xxx""
#         # key_runs: [yy{{, 请输入公司, 1, 的完整名称, }}xxx]
#         # src_text: ['aaayyy{{', 请输入公司, 1, 的完整名称, }}xxxbbbb]
#         # tgt_rext options:
#         #  option 1: ['aaa', 北京数据项素，'', 智能科技有限公司, bbbb]
#         #  option 2: ['aaa', 北京数据项素智能科技有限公司, '', '', bbbb]
#         # allocate replace mapping

#         for replace_info in template_def:
#             k1 = replace_info[0]
#             v1 = replace_info[1]
#             for table in doc.tables:
#                 for i, row in enumerate(table.rows):
#                     for j, cell in enumerate(row.cells):
#                         if k1 in cell.text:
#                             table.rows[i].cells[j].text = cell.text.replace("{{" + k1 + "}}", v1)

#         # 从段落里找key
#         for p in doc.paragraphs:
#             if "{{" in p.text:
#                 runs_cnt = len(p.runs)
#                 for r in range(0, runs_cnt):
#                     text = r.text


#         # 从段落里找key
#         for p in doc.paragraphs:
#             if "{{" in p.text:
#                 runs_cnt = len(p.runs)
#                 s, e = 0, 0
#                 for i in range(0, runs_cnt):
#                     for j in range(i + 1, runs_cnt + 1):
#                         part_text = ''.join([r.text for r in p.runs[i:j]])
#                         if k1 in part_text:
#                             s, e = i, j
#                             break

#                 assert e > 0, [r.text for r in p.runs]
#                 # tgt_text = [r.text for r in p.runs[s:e]]
#                 if e - s == 1:
#                     replace_mapping = [(k1, v1)]
#                 elif e - s == 2:
#                     s_tgt_text = p.runs[s].text
#                     comm_str, max_num = find_lcs(k1, s_tgt_text)
#                     assert k1.startswith(comm_str)
#                     p1 = comm_str
#                     p2 = k1[max_num:]
#                     n = len(v1)
#                     sub_n1 = int(1.0 * p1 / (p1 + p2) * n)
#                     # sub_n2 = n - sub_n1
#                     replace_mapping = [(p1, v1[:sub_n1]), (p2, v1[sub_n1:])]
#                 elif e - s == 3:
#                     m_text = p.runs[s + 1].text
#                     head_tail = k1.split(m_text, 1)
#                     assert len(head_tail) == 2
#                     h_text = head_tail[0]
#                     t_text = head_tail[1]
#                     replace_mapping = [(h_text, ''), (m_text, v1), (t_text, '')]
#                 else:
#                     m_texts = [p.runs[i].text for i in range(s + 1, e - 1)]
#                     m_text = ''.join(m_texts)
#                     head_tail = k1.split(m_text, 1)
#                     assert len(head_tail) == 2
#                     h_text = head_tail[0]
#                     t_text = head_tail[1]
#                     replace_mapping = [(h_text, '')]
#                     replace_mapping.append((m_texts[0], v1))
#                     for text in m_texts[1:]:
#                         replace_mapping.append((text, ''))

#                     replace_mapping.append((t_text, ''))

#                 for i in range(s, e):
#                     _k, _v = replace_mapping[i - s]
#                     p.runs[i].text = p.runs[i].text.replace(_k, _v)

#                 print('new paras:', [p.text])
#                 print('<<<<<<<<<<<<<<<<\n\n')

#         return doc

# def test_replace_string(template_file, kv_dict: dict, file_name: str):
#     # If the file is a web path, download it to a temporary file, and use that
#     if not os.path.isfile(template_file) and _is_valid_url(template_file):
#         r = requests.get(template_file)

#         if r.status_code != 200:
#             raise ValueError(
#                 'Check the url of your file; returned status code %s'
#                 % r.status_code
#             )

#         temp_dir = tempfile.TemporaryDirectory()
#         temp_file = Path(temp_dir.name) / unquote(urlparse(template_file
#                                                            ).path.split('/')[-1])
#         with open(temp_file, mode='wb') as f:
#             f.write(r.content)

#         template_file = temp_file
#     elif not os.path.isfile(template_file):
#         raise ValueError('File path %s is not a valid file or url' % template_file)

#     template_dict = []
#     for k, v in kv_dict.items():
#         template_dict.append([k, v])

#     doc = DocxTemplateRender(str(template_file))
#     output = doc.render(template_dict)

#     temp_dir = tempfile.TemporaryDirectory()
#     temp_file = Path(temp_dir.name) / 'report.docx'
#     output.save(temp_file)
#     mino_client.upload_minio(file_name, temp_file)

#     return file_name

import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.util import _is_valid_url
from docx import Document


def find_lcs(str1, str2):
    lstr1 = len(str1)
    lstr2 = len(str2)
    record = [[0 for i in range(lstr2 + 1)] for j in range(lstr1 + 1)]  # 多一位
    maxNum = 0
    p = 0
    for i in range(lstr1):
        for j in range(lstr2):
            if str1[i] == str2[j]:
                record[i + 1][j + 1] = record[i][j] + 1
                if record[i + 1][j + 1] > maxNum:
                    maxNum = record[i + 1][j + 1]
                    p = i + 1

    return str1[p - maxNum: p], maxNum


class DocxTemplateRender(object):
    def __init__(self, filepath):
        self.filepath = filepath

    def render(self, template_def):
        doc = Document(self.filepath)
        # Logics:
        # key_text: "yy{{请输入公司1的完整名称}}xxx""
        # key_runs: [yy{{, 请输入公司, 1, 的完整名称, }}xxx]
        # src_text: ['aaayyy{{', 请输入公司, 1, 的完整名称, }}xxxbbbb]
        # tgt_rext options:
        #  option 1: ['aaa', 北京数据项素，'', 智能科技有限公司, bbbb]
        #  option 2: ['aaa', 北京数据项素智能科技有限公司, '', '', bbbb]
        # allocate replace mapping

        # 采用找key 方式
        for replace_info in template_def:
            k1 = replace_info[0]
            v1 = replace_info[1]
            for table in doc.tables:
                for i, row in enumerate(table.rows):
                    for j, cell in enumerate(row.cells):
                        if k1 in cell.text:
                            table.rows[i].cells[j].text = cell.text.replace(k1, v1)

            for p in doc.paragraphs:
                if k1 in p.text:
                    runs_cnt = len(p.runs)
                    s, e = 0, 0
                    for i in range(0, runs_cnt):
                        for j in range(i + 1, runs_cnt + 1):
                            part_text = ''.join([r.text for r in p.runs[i:j]])
                            if k1 in part_text:
                                s, e = i, j
                                break

                    assert e > 0, [r.text for r in p.runs]
                    # tgt_text = [r.text for r in p.runs[s:e]]
                    if e - s == 1:
                        replace_mapping = [(k1, v1)]
                    elif e - s == 2:
                        s_tgt_text = p.runs[s].text
                        comm_str, max_num = find_lcs(k1, s_tgt_text)
                        assert k1.startswith(comm_str)
                        p1 = comm_str
                        p2 = k1[max_num:]
                        n = len(v1)
                        sub_n1 = int(1.0 * p1 / (p1 + p2) * n)
                        # sub_n2 = n - sub_n1
                        replace_mapping = [(p1, v1[:sub_n1]), (p2, v1[sub_n1:])]
                    elif e - s == 3:
                        m_text = p.runs[s + 1].text
                        head_tail = k1.split(m_text, 1)
                        assert len(head_tail) == 2
                        h_text = head_tail[0]
                        t_text = head_tail[1]
                        replace_mapping = [(h_text, ''), (m_text, v1), (t_text, '')]
                    else:
                        m_texts = [p.runs[i].text for i in range(s + 1, e - 1)]
                        m_text = ''.join(m_texts)
                        head_tail = k1.split(m_text, 1)
                        assert len(head_tail) == 2
                        h_text = head_tail[0]
                        t_text = head_tail[1]
                        replace_mapping = [(h_text, '')]
                        replace_mapping.append((m_texts[0], v1))
                        for text in m_texts[1:]:
                            replace_mapping.append((text, ''))

                        replace_mapping.append((t_text, ''))

                    for i in range(s, e):
                        _k, _v = replace_mapping[i - s]
                        p.runs[i].text = p.runs[i].text.replace(_k, _v)

                    print('new paras:', [p.text])
                    print('<<<<<<<<<<<<<<<<\n\n')

        return doc


def test_replace_string(template_file, kv_dict: dict, file_name: str):
    # If the file is a web path, download it to a temporary file, and use that
    if not os.path.isfile(template_file) and _is_valid_url(template_file):
        r = requests.get(template_file)

        if r.status_code != 200:
            raise ValueError(
                'Check the url of your file; returned status code %s'
                % r.status_code
            )

        temp_dir = tempfile.TemporaryDirectory()
        temp_file = Path(temp_dir.name) / unquote(urlparse(template_file
                                                           ).path.split('/')[-1])
        with open(temp_file, mode='wb') as f:
            f.write(r.content)

        template_file = temp_file
    elif not os.path.isfile(template_file):
        raise ValueError('File path %s is not a valid file or url' % template_file)

    template_dict = []
    for k, v in kv_dict.items():
        template_dict.append(['{{'+k+'}}', v])

    doc = DocxTemplateRender(str(template_file))
    output = doc.render(template_dict)

    temp_dir = tempfile.TemporaryDirectory()
    temp_file = Path(temp_dir.name) / file_name
    output.save(temp_file)
    MinioClient().upload_minio(file_name, temp_file)

    return file_name
