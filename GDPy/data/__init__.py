#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import pathlib

from ..core.register import registers

from .correction import correct
registers.operation.register(correct)



if __name__ == "__main__":
    ...