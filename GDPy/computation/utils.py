#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
from typing import List

import numpy as np

from ase import Atoms
from ase.io import read, write
from ase.calculators.singlepoint import SinglePointCalculator

from GDPy.computation.worker.drive import DriverBasedWorker
from GDPy.potential.register import PotentialRegister
from GDPy.utils.command import parse_input_file

def copy_minimal_frames(prev_frames: List[Atoms]):
    """Copy atoms without extra information.

    Do not copy atoms.info since it is a dict and does not maitain order.

    """
    curr_frames, curr_info = [], []
    for prev_atoms in prev_frames:
        # - copy geometry
        curr_atoms = Atoms(
            symbols=copy.deepcopy(prev_atoms.get_chemical_symbols()),
            positions=copy.deepcopy(prev_atoms.get_positions()),
            cell=copy.deepcopy(prev_atoms.get_cell(complete=True)),
            pbc=copy.deepcopy(prev_atoms.get_pbc())
        )
        curr_frames.append(curr_atoms)
        # - save info
        confid = prev_atoms.info.get("confid", -1)
        dynstep = prev_atoms.info.get("step", -1)
        prev_wdir = prev_atoms.info.get("wdir", "null")
        curr_info.append((confid,dynstep,prev_wdir))

    return curr_frames, curr_info

def make_clean_atoms(atoms_: Atoms, results: dict=None):
    """Create a clean atoms from the input."""
    atoms = Atoms(
        symbols=atoms_.get_chemical_symbols(),
        positions=atoms_.get_positions().copy(),
        cell=atoms_.get_cell().copy(),
        pbc=copy.deepcopy(atoms_.get_pbc())
    )
    if results is not None:
        spc = SinglePointCalculator(atoms, **results)
        atoms.calc = spc

    return atoms

def create_single_point_calculator(atoms_sorted, resort, calc_name):
    """ create a spc to store calc results
        since some atoms may share a calculator
    """
    atoms = atoms_sorted.copy()[resort]

    try:
        calc = SinglePointCalculator(
            atoms,
            energy=atoms_sorted.get_potential_energy(),
            forces=atoms_sorted.get_forces(apply_constraint=False)[resort]
            # TODO: magmoms?
        )
        calc.name = calc_name
        atoms.calc = calc
    except Exception as e:
        print(f"create_single_point_calculator: {e}")
        atoms = None

    return atoms

def parse_type_list(atoms):
    """parse type list for read and write structure of lammps"""
    # elements
    type_list = list(set(atoms.get_chemical_symbols()))
    type_list.sort() # by alphabet

    return type_list

def get_composition_from_atoms(atoms):
    """"""
    from collections import Counter
    chemical_symbols = atoms.get_chemical_symbols()
    composition = Counter(chemical_symbols)
    sorted_composition = sorted(composition.items(), key=lambda x:x[0])

    return sorted_composition

def get_formula_from_atoms(atoms):
    """"""
    from collections import Counter
    chemical_symbols = atoms.get_chemical_symbols()
    composition = Counter(chemical_symbols)
    sorted_composition = sorted(composition.items(), key=lambda x:x[0])

    return "".join([str(k)+str(v) for k,v in sorted_composition])


def read_trajectories(
    driver, traj_dirs,
    traj_period, traj_fpath, traj_ind_fpath,
    include_first=False, include_last=True
):
    """ read trajectories from several directories
    """
    # - act, retrieve trajectory frames
    # TODO: more general interface not limited to dynamics
    # TODO: change this to joblib?
    # TODO: check whether the existed files are empty
    if not traj_fpath.exists():
        traj_indices = [] # use traj indices to mark selected traj frames
        all_traj_frames = []
        for t_dir in traj_dirs:
            # --- read confid and parse corresponding trajectory
            driver.directory = t_dir
            traj_frames = driver.read_trajectory()
            #print("n_trajframes: ", len(traj_frames))
            n_trajframes = len(traj_frames)
            # --- generate indices
            first, last = 0, n_trajframes-1
            # NOTE: last one should be always included since it may be converged structure
            cur_indices = list(range(0,len(traj_frames),traj_period))
            if include_last:
                if last not in cur_indices:
                    cur_indices.append(last)
            if not include_first:
                cur_indices = cur_indices[1:]
            # ----- map indices to global ones
            cur_nframes = len(all_traj_frames)
            cur_indices = [c+cur_nframes for c in cur_indices]
            # --- add frames
            traj_indices.extend(cur_indices)
            all_traj_frames.extend(traj_frames)
        np.save(traj_ind_fpath, traj_indices)
        write(traj_fpath, all_traj_frames)
    else:
        all_traj_frames = read(traj_fpath, ":")
    print("ntrajframes: ", len(all_traj_frames))
    #print(len(traj_indices))
            
    #print(traj_ind_fpath)
    if traj_ind_fpath.exists():
        traj_indices = np.load(traj_ind_fpath)
    all_traj_frames = [all_traj_frames[i] for i in traj_indices]
        #print(traj_indices)
    print("ntrajframes: ", len(all_traj_frames), f" by {traj_period} traj_period")

    return all_traj_frames

if __name__ == "__main__":
    pass