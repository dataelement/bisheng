#!/usr/bin/env python
"""
Setup for SQLAlchemy backend for DM
"""
from setuptools import find_packages, setup

setup_params = dict(
    name="dmSQLAlchemy",
    version='2.0.11',
    description="SQLAlchemy dialect for DM",
    author="Dameng",
    author_email="",
    keywords='DM SQLAlchemy',
    packages=find_packages(),
    include_package_data=True,
    entry_points={
        "sqlalchemy.dialects":
            ["dm = dmSQLAlchemy.dmPython:DMDialect_dmPython", "dm.dmPython = dmSQLAlchemy.dmPython:DMDialect_dmPython", "dm.dmAsync = dmSQLAlchemy.dmAsync:DMDialect_dmAsync"]
    },
    install_requires=['dmPython', 'sqlalchemy>1.4.54'],
)

if __name__ == '__main__':
    setup(**setup_params)
