#!/usr/bin/env python

"""
setup.py file for dbtoolspy
"""
import importlib
import sys
# Use setuptools to include build_sphinx, upload/sphinx commands
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

long_description = open('README.rst').read()

spec = importlib.util.spec_from_file_location("_version", "dbtoolspy/_version.py")
if spec is None:
    raise ImportError("Failed to find module spec for _version.py!")

_version = importlib.util.module_from_spec(spec)
sys.modules["_version"] = _version
spec.loader.exec_module(_version)

setup(name='dbtoolspy',
      version=_version.__version__,
      description="""Python Module to Read EPICS Database File""",
      long_description=long_description,
      author="Xiaoqiang Wang",
      author_email="xiaoqiang.wang@psi.ch",
      url="https://github.com/paulscherrerinstitue/dbtoolspy",
      packages=["dbtoolspy"],
      entry_points={
          'console_scripts': [
              'generate-param-defs = dbtoolspy.paramdefs:generate_param_defs_cli',
          ],
      },
      license="BSD",
      classifiers=['Development Status :: 4 - Beta',
                   'Environment :: Console',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: BSD License',
                   'Programming Language :: Python :: 3',
                   ],
      )
