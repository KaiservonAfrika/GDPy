#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import copy
import json
import argparse
import subprocess 
import warnings
from typing import Union, List, NoReturn
from collections import Counter

import shutil

from pathlib import Path

import numpy as np 

from ase import Atoms 
from ase.io import read, write
from ase.constraints import FixAtoms

from GDPy.builder.constraints import parse_constraint_info
from GDPy.computation.utils import create_single_point_calculator
from GDPy.computation.driver import AbstractDriver

"""Driver for VASP."""


# vasp utils
def read_sort(directory):
    """Create the sorting and resorting list from ase-sort.dat.

    If the ase-sort.dat file does not exist, the sorting is redone.

    """
    sortfile = directory / 'ase-sort.dat'
    if os.path.isfile(sortfile):
        sort = []
        resort = []
        with open(sortfile, 'r') as fd:
            for line in fd:
                s, rs = line.split()
                sort.append(int(s))
                resort.append(int(rs))
    else:
        # warnings.warn(UserWarning, 'no ase-sort.dat')
        raise ValueError('no ase-sort.dat')

    return sort, resort

class VaspDriver(AbstractDriver):

    name = "vasp"

    # - defaults
    default_task = "min"
    supported_tasks = ["min", "md", "freq"]

    default_init_params = {
        "min": {
            "min_style": "bfgs", # ibrion
        },
        "md": {
            "md_style": "nvt",
            #"velocity_seed": 1112,
            "timestep": 1.0, # fs
            "temp": 300, # K
            #"Tdamp": 100, # fs
            #"pres": 1.0, # atm
            #"Pdamp": 100
        },
        "freq": dict(
            nsw = 1,
            ibrion = 5,
            nfree = 2,
            potim = 0.015
        )
    }

    default_run_params = {
        "min": {
            "fmax": 0.05,
            "steps": 0
        },
        "md": {
            "steps": 0
        }
    }

    param_mapping = {
        "min_style": "ibrion",
        "md_style": "smass",
        "timestep": "potim",
        "temp": "tebeg", # teend
        # nblock
        "fmax": "ediffg",
        "steps": "nsw"
    }

    # - system depandant params
    syswise_keys: List[str] = ["system", "kpts", "kspacing"]

    def _parse_params(self, params_: dict) -> NoReturn:
        """Parse different tasks, and prepare init and run params."""
        super()._parse_params(params_)

        # - update min
        if self.task == "min":
            if self.init_params["ibrion"] == "bfgs":
                self.init_params["ibrion"] = 1
            elif self.init_params["ibrion"] == "cg":
                self.init_params["ibrion"] = 2
            
            # TODO: convergence tolerance for force and energy?
            self.run_params["ediffg"] *= -1.
        
        # - update md
        if self.task == "md":
            self.init_params["ibrion"] = 0
            self.init_params["isif"] = 0
            md_style = self.init_params["smass"]
            if isinstance(md_style, str):
                if md_style == "nve":
                    pass
                elif md_style == "nvt":
                    #assert self.init_params["smass"] > 0, "NVT needs positive SMASS."
                    self.init_params["smass"] = 0.
                    self.init_params["teend"] = self.init_params["tebeg"]
                else:
                    raise NotImplementedError(f"{md_style} is not supported yet.")
            else:
                if md_style >= 0:
                    #assert self.init_params["smass"] > 0, "NVT needs positive SMASS."
                    self.init_params["teend"] = self.init_params["tebeg"]
                else:
                    raise NotImplementedError(f"SMASS {md_style} is not supported yet.")

        # - special settings
        self.run_params = self.__set_special_params(self.run_params)

        return 
    
    def __set_special_params(self, params: dict) -> dict:
        """Set several connected parameters."""

        return params
    
    def run(self, atoms_: Atoms, read_exists: bool=True, extra_info: dict=None, *args, **kwargs):
        """Run the simulation."""
        atoms = atoms_.copy()

        # - backup old params
        # TODO: change to context message?
        calc_old = atoms.calc 
        params_old = copy.deepcopy(self.calc.parameters)

        # - set special keywords
        self.delete_keywords(kwargs)
        self.delete_keywords(self.calc.parameters)

        # - run params
        kwargs = self._map_params(kwargs)

        run_params = self.run_params.copy()
        run_params.update(kwargs)

        # - init params
        run_params.update(**self.init_params)

        run_params = self.__set_special_params(run_params)

        cons_text = run_params.pop("constraint", None)
        mobile_indices, frozen_indices = parse_constraint_info(atoms, cons_text, ret_text=False)
        if frozen_indices:
            atoms._del_constraints()
            atoms.set_constraint(FixAtoms(indices=frozen_indices))
        #print("constraints: ", atoms.constraints)
        
        run_params["system"] = self.directory.name

        self.calc.set(**run_params)

        # BUG: ase 3.22.1 no special params in param_state
        #calc_params["inputs"]["lreal"] = self.calc.special_params["lreal"] 

        atoms.calc = self.calc

        # - run dynamics
        try:
            # NOTE: some calculation can overwrite existed data
            if read_exists:
                converged = False
                if (self.directory/"OUTCAR").exists():
                    converged = atoms.calc.read_convergence()
                if not converged:
                    _ = atoms.get_forces()
            else:
                _  = atoms.get_forces()
                converged = atoms.calc.read_convergence()
        except OSError:
            converged = False
        
        # NOTE: always use dynamics calc
        # TODO: should change positions and other properties for input atoms?
        traj_frames = self.read_trajectory()
        new_atoms = traj_frames[-1]

        if extra_info is not None:
            new_atoms.info.update(**extra_info)

        # - reset params
        self.calc.parameters = params_old
        self.calc.reset()
        if calc_old is not None:
            atoms.calc = calc_old

        return new_atoms
    
    def read_trajectory(self, *args, **kwargs) -> List[Atoms]:
        """Read trajectory in the current working directory.

        If the calculation failed, an empty atoms with errof info would be returned.

        """
        vasprun = self.directory / "vasprun.xml"

        # - read structures
        try:
            traj_frames_ = read(vasprun, ":")
            traj_frames = []

            # - sort frames
            sort, resort = read_sort(self.directory)
            for sorted_atoms in traj_frames_:
                input_atoms = create_single_point_calculator(sorted_atoms, resort, "vasp")
                traj_frames.append(input_atoms)
        except:
            atoms = Atoms()
            atoms.info["error"] = str(self.directory)
            traj_frames = [atoms]

        return traj_frames


if __name__ == "__main__": 
    pass