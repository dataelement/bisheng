import json
import os
import re
import time

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema import Document
from langchain_community.vectorstores import FAISS
from loguru import logger

os.environ['OPENAI_API_KEY'] = ''
os.environ['OPENAI_PROXY'] = ''


def transform2dt(inputs: dict) -> dict:
    tables_pattern = inputs['tables_pattern']
    dirty_patterns = inputs['dirty_patterns']
    patterns = inputs['patterns']
    comp_title_dict = inputs['comp_title_dict']

    # encode_kwargs = {'normalize_embeddings': inputs['ENCODER_NORMALIZE_EMBEDDINGS'], 'device': 'cuda'}
    #  encoder = HuggingFaceEmbeddings(model_name=inputs['ENCODER_MODEL_PATH'], encode_kwargs=encode_kwargs)
    encoder = OpenAIEmbeddings()

    def vector_search(docs, query, store_name, k=3, rel_thres=inputs['VECTOR_SEARCH_THRESHOLD_2']):
        start = time.time()
        store = build_vector_store([str(i) for i in docs], store_name)
        searched = store.similarity_search_with_relevance_scores(query, k=k)
        end = time.time()
        logger.info(f'向量搜索耗时 {end - start}')

        return [(docs[i[0].metadata['id']], i[1]) for i in searched]

    def build_vector_store(lines, idx_name, read_cache=True, engine=FAISS, encoder=encoder):
        documents = [
            Document(page_content=line, metadata={'id': id}) for id, line in enumerate(lines)
        ]
        store = engine.from_documents(documents, embedding=encoder)
        return store

    def is_number(string):
        return string in '1234567890' or re.fullmatch('-{0,1}[\d]+\.{0,1}[\d]+',
                                                      strip_comma(string)) != None

    def strip_comma(string):
        return string.replace(',', '')

    def bs_generator(items, bs):
        for i in range(0, len(items), bs):
            yield items[i:i + bs]

    def get_year_doc(comp_name, year):

        def year_add(year, delta):
            return str(int(year[:-1]) + delta) + '年'

        docs = comp_title_dict[comp_name]
        for doc in docs:
            if year in doc:
                return doc

        for doc in docs:
            if year_add(year, 1) in doc:
                return doc

        for doc in docs:
            if year_add(year, -1) in doc:
                return doc
        return docs[0] if docs else None

    def get_txt_path(pdf):
        return os.path.join(inputs['TXT_PATH'], pdf.replace('.pdf', '.txt'))

    """ utils.py"""

    def preprocess_key(cell):
        cell = re.sub('[(（].+[)）][.、 ]{0,1}', '', cell)
        cell = re.sub('[\d一二三四五六七八九十]+[.、 ]', '', cell)
        cell = re.sub('其中：|减：|加：|其中:|减:|加:|：|:', '', cell)
        return cell.strip()

    def is_dirty_cell(txt, is_fin_table):
        if txt == '':
            return True

        if is_fin_table:
            return not (is_number(txt) and abs(float(strip_comma(txt))) > 99)
        return False

    def my_groupby2(iterable):
        feature = 'text'
        items = []
        for i in iterable:
            if i['type'] == 'excel':
                if feature == 'excel':
                    items.append(i)
                else:
                    yield feature, items
                    items = [i]
                feature = 'excel'
            else:
                if feature == 'excel':
                    yield feature, items
                    items = [i]
                    feature = 'text'
                else:
                    items.append(i)
        yield feature, items

    def join_exccel_data(raw_part, is_fin_table, bs=5):
        try:
            part = [json.loads(i['inside'].replace("'", '"')) for i in raw_part]
            invalid_row_idxs = [
                j for j in range(1,
                                 len(part) - 1) if all([m == '' for m in part[j]])
            ]
            part = [row for i, row in enumerate(part) if i not in invalid_row_idxs]

            if not part:
                return []

            all_dics = []
            for rows in bs_generator(part, bs=bs):
                dic = {}
                for row in rows:
                    row = [preprocess_key(row[0])
                           ] + [cell for cell in row[1:] if not is_dirty_cell(cell, is_fin_table)]
                    if len(row) >= 2:
                        dic[row[0]] = row[1]
                    else:
                        dic[row[0]] = ''
                all_dics.append(json.dumps(dic, ensure_ascii=False))
            return all_dics
        except json.decoder.JSONDecodeError as e:
            return []

    class DocTreeNode:

        def __init__(self, content, parent=None, is_leaf=False, type_=-1, is_excel=False):
            # -2: 过滤的内容
            # -1: 普通的文本内容
            # 0123分别为四级标题
            self.type_ = type_
            self.is_excel = is_excel
            self.content = content
            self.children = []
            self.parent = parent
            # 传递根路径
            if self.parent != None:
                self.path = self.parent.path

        def __str__(self):
            return self.content

        def get_dep_str(self, hop=1):
            res = str(self)
            ptr = self
            for _ in range(hop):
                if ptr.parent == None:
                    return res
                ptr = ptr.parent
                res = str(ptr) + '\n' + res
            return res

        def print_children(self):
            for i, child in enumerate(self.children):
                print(f'#{i}-is_excel:{child.is_excel}', child)

        def get_all_leaves(self, keyword, only_excel_node=True, include_node=True):
            leaves = []
            for child in self.children:
                if child.type_ == -1:
                    leaves.append(child)
                    continue

                if include_node:
                    leaves.append(child)

                if keyword in str(child):
                    leaves += child.get_all_leaves(keyword, only_excel_node=only_excel_node)
            if only_excel_node:
                leaves = [i for i in leaves if i.is_excel]
            return leaves

        def search_children(self, query):
            res = []
            for child in self.children:
                if child.type_ == -1:
                    if len(re.findall('[^\u4e00-\u9fa5]' + query + '[^\u4e00-\u9fa5]',
                                      str(child))) > 0:
                        res.append(child)
                else:
                    res += child.search_children(query)
            return res

        def vector_search_children(self, query, k=3):
            all_children = self.get_all_leaves('', only_excel_node=False)
            return vector_search(all_children, query, self.path + '-' + str(self), k=k)

    class DocTree:
        """ Doc Tree path 是txt文件，命名格式固定 """

        def __init__(self, txt_path=None, read_cache=True, json_lines=[]):
            self.path = txt_path
            if txt_path != None:
                self.lines = open(txt_path, encoding='utf-8').read().split('\n')
            else:
                self.lines = json_lines
            self.json_lines = []
            self.json_loads()
            self.mid_nodes = []
            self.leaves = []
            self.root = DocTreeNode('@root', type_=-1)
            self.root.path = self.path
            self.build_tree()

        def json_loads(self):
            for line in self.lines:
                try:
                    line = json.loads(line)
                    self.json_lines.append(line)
                except Exception as e:
                    # print(e)
                    # print(line)
                    pass

        @classmethod
        def find_pattern(cls, text):
            ' 正则匹配，确定Node_type '
            if is_number(text):
                return -2, ''

            find = re.findall(tables_pattern, text)
            if len(find) > 0:
                return 6, find[0]

            for j, dpat in enumerate(dirty_patterns):
                find = re.findall(dpat, text)
                if len(find) >= 1:
                    return -2, find[0]

            for i, pat in enumerate(patterns):
                find = re.findall(pat, text)
                if len(find) == 1 and (text.startswith(find[0]) or
                                       (i == 6 and text.endswith(find[0]))):

                    if (i == 0 and text == find[0]) or i != 0:
                        return i, find[0]
            return -1, ''

        def group_leave_nodes(self, leave_lines, is_fin_table):
            all_docs = []
            is_excels = []

            for key, part in my_groupby2(leave_lines):
                if not part:
                    continue

                if key == 'excel':
                    part_texts = join_exccel_data(part, is_fin_table)
                    all_docs += part_texts
                    is_excels += [True] * len(part_texts)
                else:
                    part_text = '\n'.join([i['inside'] for i in part])
                    all_docs.append(part_text)
                    is_excels.append(False)
            return all_docs, is_excels

        def build_tree(self):
            last_parent = self.root
            last_leaves = []
            for line in self.json_lines:
                text = line.get('inside', '')
                text_type = line.get('type', -2)

                if text_type in ('页眉', '页脚') or text == '':
                    continue

                # 表格直接加到last_leaves
                if text_type == 'excel':
                    last_leaves.append(line)
                    continue

                type_, pat = self.find_pattern(text)

                # 过滤的内容
                if type_ == -2:
                    continue

                if type_ == -1:
                    last_leaves.append(line)
                else:
                    # 检测到新标题，首先把之前的叶节点内容归档
                    if len(last_leaves) > 0:
                        node_texts, is_excels = self.group_leave_nodes(
                            last_leaves, last_parent.type_ == 6)
                        for node_text, is_excel in zip(node_texts, is_excels):
                            new_node = DocTreeNode(node_text,
                                                   type_=-1,
                                                   parent=last_parent,
                                                   is_leaf=True,
                                                   is_excel=is_excel)
                            last_parent.children.append(new_node)
                            self.leaves.append(new_node)
                        last_leaves = []

                    # 判断新标题与目前parent层级的关系
                    if type_ > last_parent.type_:
                        # 1. 检测出来的层级低于目前层级
                        new_node = DocTreeNode(text, type_=type_, parent=last_parent)
                        last_parent.children.append(new_node)
                        last_parent = new_node
                    else:
                        while type_ <= last_parent.type_:
                            last_parent = last_parent.parent
                        new_node = DocTreeNode(text, type_=type_, parent=last_parent)
                        last_parent.children.append(new_node)
                        last_parent = new_node
                    self.mid_nodes.append(new_node)

                    # for debug
                    # print(f"#{type_}#", text)

        def search_leaf(self, query, k=1, only_excel_node=True):
            query_words = query.split(' ')
            nodes = []
            hit_lens = []
            for node in self.leaves:
                if only_excel_node and not node.is_excel:
                    continue

                nodes.append(node)
                hit_len = 0
                for word in query_words:
                    if word in str(node):
                        hit_len += len(word)

                hit_lens.append(hit_len)
            node_hit_zips = [(n, h) for n, h in zip(nodes, hit_lens)]
            sorted_node_hit_zips = sorted(node_hit_zips, key=lambda x: x[1], reverse=True)
            return [i[0] for i in sorted_node_hit_zips[:k] if i[1] > 0]

        def regular_search(self, query, k=1, only_excel_node=True):
            query_words = query.split(' ')
            print('#regular search', query_words)
            nodes = []
            hit_lens = []
            for node in self.leaves:
                if only_excel_node and not node.is_excel:
                    continue

                nodes.append(node)
                hit_len = 0
                for word in query_words:
                    if word in str(node):
                        hit_len += len(word)

                hit_lens.append(hit_len)
            node_hit_zips = [(n, h) for n, h in zip(nodes, hit_lens)]
            sorted_node_hit_zips = sorted(node_hit_zips, key=lambda x: x[1], reverse=True)
            return [str(i[0]) for i in sorted_node_hit_zips[:k] if i[1] > 0]

        def search_node(self, query):
            nodes = []
            for node in self.mid_nodes:
                if query in str(node):
                    nodes.append(node)
            return nodes

        def vector_search_node(self, query, k=1):
            return vector_search(self.mid_nodes, query, self.path + '-node', k=k)

    result = inputs['query_analyze_result']
    comp_name = result['comps'][0]
    year = result['years'][0]
    pdf = get_year_doc(comp_name, year)
    if pdf == None:
        path = None
    path = get_txt_path(pdf)
    dt = DocTree(path)
    return {'doc_tree': dt}
