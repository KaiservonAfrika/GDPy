#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import itertools
import pathlib
from typing import Union, List, NoReturn

from ase import Atoms
from ase.io import read, write

from GDPy.core.variable import Variable
from GDPy.core.operation import Operation
from GDPy.core.register import registers
from GDPy.worker.worker import AbstractWorker
from GDPy.data.array import AtomsArray2D
from GDPy.selector.selector import AbstractSelector, load_cache
from GDPy.selector.composition import ComposedSelector


@registers.variable.register
class SelectorVariable(Variable):

    def __init__(self, selection: List[dict], directory="./", *args, **kwargs) -> None:
        """"""
        selection = copy.deepcopy(selection)
        selectors = []
        for params in selection:
            method = params.pop("method", None)
            selector = registers.create("selector", method, convert_name=True, **params)
            selectors.append(selector)
        nselectors = len(selectors)
        if nselectors > 1:
            selector = ComposedSelector(selectors)
        else:
            selector = selectors[0]

        super().__init__(initial_value=selector, directory=directory)

        return


@registers.operation.register
class select(Operation):

    cache_fname = "selected_frames.xyz"

    def __init__(
        self, structure, selector, directory="./", *args, **kwargs
    ):
        """"""
        super().__init__(input_nodes=[structure,selector], directory=directory)

        return
    
    @Operation.directory.setter
    def directory(self, directory_) -> NoReturn:
        """"""
        super(select, select).directory.__set__(self, directory_)

        return
    
    def forward(self, structures: AtomsArray2D, selector: AbstractSelector) -> AtomsArray2D:
        """"""
        super().forward()
        selector.directory = self.directory

        cache_fpath = self.directory/self.cache_fname
        if not cache_fpath.exists():
            new_frames = selector.select(structures)
            write(cache_fpath, new_frames)
        else:
            raw_markers = load_cache(selector.info_fpath)
            structures.set_markers(raw_markers)
            new_frames = read(cache_fpath, ":")
        self.pfunc(f"nframes: {len(new_frames)}")
        
        self.status = "finished"

        return structures


def run_selection(
    param_file: Union[str,pathlib.Path], structure: Union[str,dict], 
    directory: Union[str,pathlib.Path]="./", potter: AbstractWorker=None
) -> None:
    """Run selection with input selector and input structures.
    """
    directory = pathlib.Path(directory)
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=False)

    from GDPy.utils.command import parse_input_file
    params = parse_input_file(param_file)

    selector = SelectorVariable(
        params["selection"], directory=directory, pot_worker=potter
    ).value
    selector.directory = directory

   # - read structures
    from GDPy.builder import create_builder
    builder = create_builder(structure)
    frames = builder.run()

    # TODO: convert to a bundle of atoms?
    data = AtomsArray2D.from_list2d([frames])

    # -
    selected_frames = selector.select(data)

    from ase.io import read, write
    write(directory/"selected_frames.xyz", selected_frames)

    return

if __name__ == "__main__":
    ...