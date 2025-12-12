#!/usr/bin/env python

from setuptools import find_packages, setup

setup_params = dict(
    name="dmAsync",
    version='1.0.0',
    description="Asynchronous compatibility package for DM",
    author="Dameng",
    author_email="",
    keywords='DM async',
    packages=find_packages(),
    include_package_data=True,
    install_requires=['dmPython'],
)

if __name__ == '__main__':
    setup(**setup_params)
