#!/usr/bin/env python

"""
setup.py file for dbtoolspy
"""
import imp
import sys
# Use setuptools to include build_sphinx, upload/sphinx commands
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

long_description = open('README.rst').read()

_version = imp.load_source('_version','dbtoolspy/_version.py')

setup(name='dbtoolspy',
      version=_version.__version__,
      description="""Python Module to Read EPICS Database File""",
      long_description=long_description,
      author="Xiaoqiang Wang",
      author_email="xiaoqiang.wang@psi.ch",
      url="https://github.com/paulscherrerinstitue/dbtoolspy",
      packages=["dbtoolspy"],
      license="BSD",
      classifiers=['Development Status :: 4 - Beta',
                   'Environment :: Console',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: BSD License',
                   'Programming Language :: Python :: 2',
                   'Programming Language :: Python :: 3',
                   ],
      )
