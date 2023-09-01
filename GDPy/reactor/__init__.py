#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy

from ..core.register import registers


""" This submodule is for exploring, sampling, 
    and performing (chemical) reactions with
    various advanced algorithms.
"""

from .pathway import MEPFinder
registers.reactor.register("ase")(MEPFinder)

from .cp2k import Cp2kStringReactor
registers.reactor.register("cp2k")(Cp2kStringReactor)


if __name__ == "__main__":
    ...