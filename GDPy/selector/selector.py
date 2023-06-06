#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import abc 
import copy
import itertools
import pathlib
from typing import Union, List, Callable, NoReturn

import numpy as np

from ase import Atoms

from GDPy import config
from GDPy.core.node import AbstractNode
from GDPy.computation.worker.drive import DriverBasedWorker
from GDPy.data.trajectory import Trajectories


"""Define an AbstractSelector that is the base class of any selector.
"""

def save_cache(fpath, data, random_seed: int=None):
    """"""
    header = ("#{:>11s}  {:>8s}  {:>8s}  {:>8s}  "+"{:>12s}"*4+"\n").format(
        *"index confid step natoms ene aene maxfrc score".split()
    )
    footer = f"random_seed {random_seed}"

    content = header
    for x in data:
        content += ("{:>12s}  {:>8d}  {:>8d}  {:>8d}  "+"{:>12.4f}"*4+"\n").format(*x)
    content += footer

    with open(fpath, "w") as fopen:
        fopen.write(content)

    return

def load_cache(fpath, random_seed: int=None):
    """"""
    with open(fpath, "r") as fopen:
        lines = fopen.readlines()

    # - header
    header = lines[0]

    # - data
    data = lines[1:-1] # TODO: test empty data

    raw_markers = []
    if data:
        # new_markers looks like [(0,1),(0,2),(1,0)]
        new_markers =[
            [int(x) for x in (d.strip().split()[0]).split(",")] for d in data
        ]
        raw_markers = group_markers(new_markers)

    # - footer
    footer = lines[-1]
    cache_random_seed = int(footer.strip().split()[-1])
    #assert cache_random_seed == random_seed

    return raw_markers

def group_markers(new_markers_unsorted):
    """"""
    new_markers = sorted(new_markers_unsorted, key=lambda x: x[0])
    raw_markers_unsorted = []
    for k, v in itertools.groupby(new_markers, key=lambda x: x[0]):
        raw_markers_unsorted.append([k,[x[1] for x in v]])

    # traj markers are sorted when set
    raw_markers = [[x[0],sorted(x[1])] for x in sorted(raw_markers_unsorted, key=lambda x:x[0])]

    return raw_markers


class AbstractSelector(AbstractNode):

    """The base class of any selector."""

    #: Selector name.
    name: str = "abstract"

    #: Default parameters.
    default_parameters: dict = dict(
        number = [4, 0.2], # number & ratio
        verbose = False
    )

    #: A worker for potential computations.
    worker: DriverBasedWorker = None

    #: Distinguish structures when using ComposedSelector.
    prefix: str = "selection"

    #: Output file name.
    _fname: str = "info.txt"

    logger = None #: Logger instance.

    _pfunc: Callable = print #: Function for outputs.
    indent: int = 0 #: Indent of outputs.

    #: Output data format (frames or trajectories).
    _out_fmt: str = "stru"

    def __init__(self, directory="./", *args, **kwargs) -> NoReturn:
        """Create a selector.

        Args:
            directory: Working directory.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        super().__init__(directory=directory, *args, **kwargs)

        self.fname = self.name+"-info.txt"
        
        if "random_seed" in self.parameters:
            self.set_rng(seed=self.parameters["random_seed"])

        #: Number of parallel jobs for joblib.
        self.njobs = config.NJOBS

        return

    @AbstractNode.directory.setter
    def directory(self, directory_) -> NoReturn:
        self._directory = pathlib.Path(directory_)
        self.info_fpath = self._directory/self._fname

        return 
    
    @property
    def fname(self):
        """"""
        return self._fname
    
    @fname.setter
    def fname(self, fname_):
        """"""
        self._fname = fname_
        self.info_fpath = self._directory/self._fname
        return
    
    def attach_worker(self, worker=None) -> NoReturn:
        """Attach a worker to this node."""
        self.worker = worker

        return

    def select(self, inp_dat: Trajectories, *args, **kargs) -> List[Atoms]:
        """Select trajectories.

        Based on used selction protocol

        Args:
            frames: A list of ase.Atoms or a list of List[ase.Atoms].
            index_map: Global indices of frames.
            ret_indices: Whether return selected indices or frames.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        
        Returns:
            List[Atoms] or List[int]: selected results

        """
        if self.logger is not None:
            self._pfunc = self.logger.info
        self.pfunc(f"@@@{self.__class__.__name__}")

        if not self.directory.exists():
            self.directory.mkdir(parents=True)
        #print("selector input: ", inp_dat)

        frames = inp_dat

        # - check if it is finished
        if not (self.info_fpath).exists():
            self.pfunc("run selection...")
            self._mark_structures(frames)
        else:
            # -- restart
            self.pfunc("use cached...")
            raw_markers = load_cache(self.info_fpath)
            frames.set_markers(raw_markers)
        self.pfunc(f"{self.name} nstructures {frames.nstructures} -> nselected {frames.get_number_of_markers()}")

        # - save cached results for restart
        self._write_cached_results(frames)

        # - add history
        marked_structures = inp_dat.get_marked_structures()
        for atoms in marked_structures:
            selection = atoms.info.get("selection", "")
            atoms.info["selection"] = selection+f"->{self.name}"

        return marked_structures
    
    @abc.abstractmethod
    def _mark_structures(self, frames, *args, **kwargs) -> None:
        """Mark structures subject to selector's conditions."""

        return

    def _parse_selection_number(self, nframes: int) -> int:
        """Compute number of selection based on the input number.

        Args:
            nframes: Number of input frames, sometimes maybe zero.

        """
        default_number, default_ratio = self.default_parameters["number"]
        number_info = self.parameters["number"]
        if isinstance(number_info, int):
            num_fixed, num_percent = number_info, default_ratio
        elif isinstance(number_info, float):
            num_fixed, num_percent = default_number, number_info
        else:
            assert len(number_info) == 2, "Cant parse number for selection..."
            num_fixed, num_percent = number_info
        
        if num_fixed is not None:
            if num_fixed > nframes:
                num_fixed = int(nframes*num_percent)
        else:
            num_fixed = int(nframes*num_percent)

        return num_fixed
    
    def pfunc(self, content, *args, **kwargs):
        """Write outputs to file."""
        content = self.indent*" " + content
        self._pfunc(content)

        return

    def _write_cached_results(self, frames: Trajectories, *args, **kwargs) -> None:
        """Write selection results into file that can be used for restart."""
        # - 
        raw_markers = frames.get_markers()
        new_markers = []
        for i, markers in raw_markers:
            for s in markers:
                new_markers.append((i,s))
            ...

        # - output
        data = []
        for i, j in new_markers:
            atoms = frames[i][j]
            # - gather info
            confid = atoms.info.get("confid", -1)
            step = atoms.info.get("step", -1) # step number in the trajectory
            natoms = len(atoms)
            try:
                ene = atoms.get_potential_energy()
                ae = ene / natoms
            except:
                ene, ae = np.NaN, np.NaN
            try:
                maxforce = np.max(np.fabs(atoms.get_forces(apply_constraint=True)))
            except:
                maxforce = np.NaN
            score = atoms.info.get("score", np.nan)
            #if index_map is not None:
            #    s = index_map[s]
            data.append([f"{str(i)},{str(j)}", confid, step, natoms, ene, ae, maxforce, score])

        if data:
            save_cache(self.info_fpath, data, self.random_seed)
        else:
            np.savetxt(
                self.info_fpath, [[np.NaN]*8],
                header="{:>11s}  {:>8s}  {:>8s}  {:>8s}  {:>12s}  {:>12s}  {:>12s}  {:>12s}".format(
                    *"index confid step natoms ene aene maxfrc score".split()
                ),
                footer=f"random_seed {self.random_seed}"
            )

        return


if __name__ == "__main__":
    ...