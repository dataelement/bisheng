# Copyright 2024 Liu Siyao
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from pptx import Presentation

logger = logging.getLogger(__name__)


def fix_null_rels(file_path):
    temp_dir_name = tempfile.mkdtemp()
    shutil.unpack_archive(file_path, temp_dir_name, 'zip')
    rels = [
        os.path.join(dp, f)
        for dp, dn, filenames in os.walk(temp_dir_name)
        for f in filenames
        if os.path.splitext(f)[1] == '.rels'
    ]
    pat = re.compile(r'<\S*Relationship[^>]+Target\S*=\S*"NULL"[^>]*/>', re.I)
    for fn in rels:
        f = open(fn, 'r+')
        content = f.read()
        res = pat.search(content)
        if res is not None:
            content = pat.sub('', content)
            f.seek(0)
            f.truncate()
            f.write(content)
        f.close()
    tfn = uuid.uuid4().hex
    shutil.make_archive(tfn, 'zip', temp_dir_name)
    shutil.rmtree(temp_dir_name)
    tgt = f'{file_path[:-5]}_purged.pptx'
    shutil.move(f'{tfn}.zip', tgt)
    return tgt


def load_pptx(file_path: str) -> Presentation:
    if not os.path.exists(file_path):
        logger.error(f'source file {file_path} not exist!')
        logger.error(f'absolute path: {os.path.abspath(file_path)}')
        raise FileNotFoundError(file_path)
    try:
        prs = Presentation(file_path)
    except KeyError as err:
        if len(err.args) > 0 and re.match(r'There is no item named .*NULL.* in the archive', str(err.args[0])):
            logger.info('corrupted links found, trying to purge...')
            try:
                res_path = fix_null_rels(file_path)
                logger.info(f'purged file saved to {res_path}.')
                prs = Presentation(res_path)
            except:
                logger.error(
                    'failed to purge corrupted links, you can report this at https://github.com/ssine/pptx2md/issues')
                raise err
        else:
            logger.error('unknown error, you can report this at https://github.com/ssine/pptx2md/issues')
            raise err
    return prs


def prepare_titles(title_path: Path) -> dict[str, int]:
    titles: dict[str, int] = {}
    with open(title_path, 'r', encoding='utf8') as f:
        indent = -1
        for line in f.readlines():
            cnt = 0
            while line[cnt] == ' ':
                cnt += 1
            if cnt == 0:
                titles[line.strip()] = 1
            else:
                if indent == -1:
                    indent = cnt
                    titles[line.strip()] = 2
                else:
                    titles[line.strip()] = cnt // indent + 1
    return titles


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f'#{r:02x}{g:02x}{b:02x}'
