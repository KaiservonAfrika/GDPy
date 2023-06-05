#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import itertools
import numbers
import pathlib
from typing import NoReturn, List

import h5py

import numpy as np

from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator

from GDPy.data.array import AtomsArray, AtomsArray2D


class Trajectory(AtomsArray):

    """The base class of a List of ase.Atoms.
    """

    # MD and MIN settings... TODO: type?
    # dump period

    def __init__(self, images: List[Atoms], driver_config: dict, *args, **kwargs):
        """"""
        super().__init__(images=images)

        self.driver_config = driver_config

        self.task = driver_config["task"]

        return
    
    def read_convergence(self):
        """TODO? Check whether this traj is converged."""

        return
    
    def _save_to_hd5grp(self, grp):
        """"""
        super()._save_to_hd5grp(grp)

        # -
        if self.driver_config["task"] == "md":
            grp.attrs["task"] = "md"
            grp.attrs["temperature"] = self.driver_config["temp"]
            grp.attrs["timestep"] = self.driver_config["timestep"]
        elif self.driver_config["task"] == "min":
            grp.attrs["task"] = "min"
            grp.attrs["fmax"] = self.driver_config["fmax"]
        else:
            # TODO: ...
            ...

        return
    
    def __repr__(self) -> str:
        """"""

        return f"Trajectory(task={self.task}, shape={len(self)}, markers={self.markers})"


class Trajectories(AtomsArray2D):

    """The base class of a List of Trajectory.
    """

    name = "trajectories"

    def __init__(self, trajectories: List[Trajectory]=[]) -> None:
        """"""
        super().__init__(rows=trajectories)

        return
    
    def __repr__(self) -> str:
        """"""

        return f"Trajectories(number: {len(self)}, shape: {self.shape}, markers: {self.get_number_of_markers()})"


if __name__ == "__main__":
    ...