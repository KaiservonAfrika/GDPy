#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import pathlib

from GDPy.selector.invariant import InvariantSelector
from GDPy.selector.traj import BoltzmannMinimaSelection
from GDPy.selector.descriptor import DescriptorBasedSelector
from GDPy.selector.uncertainty import DeviationSelector
from GDPy.selector.composition import ComposedSelector
from GDPy.selector.convergence import ConvergenceSelector

def create_selector(input_list: list, directory=pathlib.Path.cwd(), pot_worker=None):
    selectors = []

    if not input_list:
        selectors.append(InvariantSelector())

    for s in input_list:
        params = copy.deepcopy(s)
        method = params.pop("method", None)
        if method == "invariant":
            selectors.append(InvariantSelector(**params))
        elif method == "convergence":
            selectors.append(ConvergenceSelector(**params))
        elif method == "boltzmann":
            selectors.append(BoltzmannMinimaSelection(**params))
        elif method == "deviation":
            selectors.append(DeviationSelector(**params, pot_worker=pot_worker))
        elif method == "descriptor":
            selectors.append(DescriptorBasedSelector(**params))
        else:
            raise RuntimeError(f"Cant find selector with method {method}.")
    
    # - try a simple composed selector
    if len(selectors) > 1:
        selector = ComposedSelector(selectors, directory=directory)
    else:
        selector = selectors[0]
        selector.directory = directory

    return selector

if __name__ == "__main__":
    pass