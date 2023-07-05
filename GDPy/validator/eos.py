#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib

import numpy as np

import matplotlib
matplotlib.use("Agg") #silent mode
import matplotlib.pyplot as plt
try:
    plt.style.use("presentation")
except Exception as e:
    print("Used default matplotlib style.")

from ase.io import read, write
from ase.eos import EquationOfState 

from ..data.array import AtomsArray2D
from .validator import AbstractValidator

"""Validation on equation of states.
"""

def plot_eos(ref_volumes, ref_energies, pre_volumes, pre_energies, fig_fpath="./bm.png"):
    """"""
    # plot figure
    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(12,8))
    ax.set_title("Birch-Murnaghan (Constant-Volume Optimisation)")
    
    ax.set_xlabel("Volume/atom [Å^3/atom]")
    ax.set_ylabel("Energy/atom [eV/atom]")

    ax.scatter(ref_volumes, ref_energies, marker="*", label="reference")
    ax.scatter(pre_volumes, pre_energies, marker="*", label="prediction")

    ax.legend()

    plt.savefig(fig_fpath)

    return


class EquationOfStateValidator(AbstractValidator):

    def __init__(self, *args, **kwargs):
        """"""
        super().__init__(*args, **kwargs)

        return
    
    def run(self, dataset, worker=None, *args, **kwargs):
        """"""
        # - preprocess the dataset
        pre_dataset = dataset.get("prediction", None)
        if isinstance(pre_dataset, AtomsArray2D):
            pre_dataset = pre_dataset.get_marked_structures() # List[Atoms]
        ref_dataset = dataset.get("reference", None)
        if isinstance(ref_dataset, AtomsArray2D):
            ref_dataset = ref_dataset.get_marked_structures() # List[Atoms]
        
        # - 
        ref_natoms = np.array([len(a) for a in ref_dataset])
        ref_volumes = np.array([a.get_volume() for a in ref_dataset]) / ref_natoms
        ref_energies = np.array([a.get_potential_energy() for a in ref_dataset]) / ref_natoms

        pre_natoms = np.array([len(a) for a in pre_dataset])
        pre_volumes = np.array([a.get_volume() for a in pre_dataset]) / pre_natoms
        pre_energies = np.array([a.get_potential_energy() for a in pre_dataset]) / pre_natoms

        plot_eos(
            ref_volumes, ref_energies, pre_volumes, pre_energies, 
            fig_fpath=self.directory/"bm.png"
        )

        return


if __name__ == "__main__":
    ...