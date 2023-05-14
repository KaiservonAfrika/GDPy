#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
from typing import List

import numpy as np

from ase import Atoms
from ase import data, units
from ase.neighborlist import NeighborList, natural_cutoffs
from ase.ga.utilities import closest_distances_generator

from GDPy.builder.species import build_species
from GDPy.builder.group import create_a_group
from GDPy.mc.operators.move import MoveOperator


class SwapOperator(MoveOperator):

    def __init__(
        self, particles: List[str], region: dict={}, temperature: float = 300, pressure: float = 1, 
        covalent_ratio=[0.8,2.0], use_rotation: bool = True,
        *args, **kwargs
    ):
        """"""
        super().__init__(
            particles=particles, region=region, temperature=temperature, pressure=pressure, 
            covalent_ratio=covalent_ratio, use_rotation=use_rotation, *args, **kwargs
        )

        # NOTE: Prohibit swapping the same type of particles.
        assert len(set(self.particles)) == 2, f"f{self.__class__.__name__} needs two types of particles."

        return
    
    def run(self, atoms: Atoms, rng=np.random) -> Atoms:
        """"""
        super().run(atoms)

        # - basic
        cur_atoms = atoms
        chemical_symbols = cur_atoms.get_chemical_symbols()
        cell = cur_atoms.get_cell(complete=True)

        # -- neighbour list
        nl = NeighborList(
            self.covalent_max*np.array(natural_cutoffs(cur_atoms)), 
            skin=0.0, self_interaction=False, bothways=True
        )

        # -- TODO: init blmin?
        type_list = list(set(chemical_symbols))
        unique_atomic_numbers = [data.atomic_numbers[a] for a in type_list]
        self.blmin = closest_distances_generator(
            atom_numbers=unique_atomic_numbers,
            ratio_of_covalent_radii = self.covalent_min # be careful with test too far
        )

        # - swap the species
        for i in range(self.MAX_RANDOM_ATTEMPTS):
            # -- swap
            cur_atoms = atoms.copy()

            # -- pick an atom
            #   either index of an atom or tag of an moiety
            first_pick = self._select_species(cur_atoms, [self.particles[0]], rng=rng)
            second_pick = self._select_species(cur_atoms, [self.particles[1]], rng=rng)
            self._print(f"first: {first_pick} second: {second_pick}")

            # -- find tag atoms
            first_species = cur_atoms[first_pick] # default copy
            second_species = cur_atoms[second_pick]
            # TODO: deal with pbc
            first_cop = np.average(copy.deepcopy(first_species.get_positions()), axis=0)
            second_cop = np.average(copy.deepcopy(second_species.get_positions()), axis=0)

            self._print(f"origin: {first_species.symbols} {first_cop}")
            self._print(f"origin: {second_species.symbols} {second_cop}")

            # -- rotate and swap
            first_species = self._rotate_species(first_species, rng=rng)
            second_species = self._rotate_species(second_species, rng=rng)

            cur_atoms.positions[first_pick] += (second_cop - first_cop)
            cur_atoms.positions[second_pick] += (first_cop - second_cop)

            first_species = cur_atoms[first_pick]
            second_species = cur_atoms[second_pick]
            # TODO: deal with pbc
            first_cop = np.average(copy.deepcopy(first_species.get_positions()), axis=0)
            second_cop = np.average(copy.deepcopy(second_species.get_positions()), axis=0)

            self._print(f"swapped: {first_species.symbols} {first_cop}")
            self._print(f"swapped: {second_species.symbols} {second_cop}")

            # -- use neighbour list
            idx_pick = []
            idx_pick.extend(first_pick)
            idx_pick.extend(second_pick)
            if not self.check_overlap_neighbour(nl, cur_atoms, cell, idx_pick):
                self._print(f"succeed to random after {i+1} attempts...")
                break
        else:
            cur_atoms = None

        return cur_atoms

    def as_dict(self):
        """"""

        return

    def __repr__(self) -> str:
        """"""
        content = f"@Modifier {self.__class__.__name__}\n"
        content += f"temperature {self.temperature} [K] pressure {self.pressure} [bar]\n"
        content += "covalent ratio: \n"
        content += f"  min: {self.covalent_min} max: {self.covalent_max}\n"
        content += f"swapped groups: \n"
        content += f"  {self.particles[0]} <-> {self.particles[1]}\n"

        return content


if __name__ == "__main__":
    ...