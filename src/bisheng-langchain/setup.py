# Copyright (c) 2020 bisheng_langchain Authors. All Rights Reserved.
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
import io
import os

import setuptools


def get_version():
    if os.getenv('RELEASE_VERSION'):
        version = os.environ['RELEASE_VERSION']
    else:
        version_file = os.path.join(os.path.dirname(__file__), 'version.txt')
        with open(version_file, 'r') as f:
            version = f.read().strip()
    return version.lstrip('v')


def read_requirements_file(filepath):
    with open(filepath) as fin:
        requirements = fin.read()
    return requirements


extras = {}
REQUIRED_PACKAGES = read_requirements_file('requirements.txt')


def read(*names, **kwargs):
    with io.open(os.path.join(os.path.dirname(__file__), *names), encoding=kwargs.get('encoding', 'utf8')) as fp:
        return fp.read()


def get_package_data_files(package, data, package_dir=None):
    """
    Helps to list all specified files in package including files in directories
    since `package_data` ignores directories.
    """
    if package_dir is None:
        package_dir = os.path.join(*package.split('.'))
    all_files = []
    for f in data:
        path = os.path.join(package_dir, f)
        if os.path.isfile(path):
            all_files.append(f)
            continue
        for root, _dirs, files in os.walk(path, followlinks=True):
            root = os.path.relpath(root, package_dir)
            for file in files:
                file = os.path.join(root, file)
                if file not in all_files:
                    all_files.append(file)
    return all_files


setuptools.setup(
    name='bisheng_langchain',
    version=get_version(),
    author='DataElem',
    author_email='contact@dataelem.com',
    description='bisheng langchain modules',
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    url='https://github.com/dataelement/bisheng',
    packages=setuptools.find_packages(exclude=('examples*', 'tests*', 'applications*', 'model_zoo*'),),
    package_data={
        "bisheng_langchain": ["rag/config/*"]
    },
    setup_requires=[],
    install_requires=REQUIRED_PACKAGES,
    entry_points={},
    extras_require=extras,
    python_requires='>=3.6',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
    ],
    license='Apache 2.0',
)
