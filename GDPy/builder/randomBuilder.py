#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import warnings

from typing import List
from pathlib import Path

import numpy as np

import ase
from ase import Atoms
from ase.io import read, write

from ase.ga.utilities import get_all_atom_types, closest_distances_generator # get system composition (both substrate and top)
from ase.ga.utilities import CellBounds
from ase.ga.startgenerator import StartGenerator

from GDPy.builder.builder import StructureGenerator
from GDPy.builder.species import build_species

""" Generate structures randomly
"""


class RandomGenerator(StructureGenerator):

    supported_systems = ["bulk", "cluster", "surface"]

    MAX_FAILED = 10
    MAX_RANDOM_TRY = 100

    def __init__(self, params, directory=Path.cwd()):
        """"""
        super().__init__(directory)

        self.params = copy.deepcopy(params)
        self.generator = self._create_generator(self.params)

        return
    
    def _create_generator(self, params) -> None:
        """ create a random structure generator
        """
        # - parse composition
        # --- Define the composition of the atoms to optimize ---
        composition = params["composition"] # number of inserted atoms
        blocks = [(k,v) for k,v in composition.items()] # for start generator
        for k, v in blocks:
            species = build_species(k)
            if len(species) > 1:
                use_tags = True
                break
        else:
            use_tags = False
            #print("Perform atomic search...")

        atom_numbers = [] # atomic number of inserted atoms
        for species, num in composition.items():
            numbers = []
            for s, n in ase.formula.Formula(species).count().items():
                numbers.extend([ase.data.atomic_numbers[s]]*n)
            atom_numbers.extend(numbers*num)

        # unpack info
        system_type = params.get("type", "surface")
        assert system_type in self.supported_systems, f"{system_type} is not supported..."
        self.system_type = system_type

        cell = params.get("cell", []) # depands on system
        region = params.get("region", None) # 4x4 matrix, where place atoms
        splits = params.get("splits", None) # to repeat cell

        volume = params.get("volume", None)
        cell_bounds = None

        number_of_variable_cell_vectors =0
        if system_type == "bulk":
            slab = Atoms("", pbc=True)
            # - check number_of_variable_cell_vectors
            number_of_variable_cell_vectors = 3 - len(cell)
            box_to_place_in = None
            if number_of_variable_cell_vectors > 0:
                box_to_place_in = [[0.,0.,0.], np.zeros((3,3))]
                if len(cell) > 0:
                    box_to_place_in[1][number_of_variable_cell_vectors:] = cell
            # --- check volume
            if not volume:
                volume = 10.*len(atom_numbers) # AA^3
            # --- cell bounds
            cell_bounds = {}
            angles, lengths = ["phi", "chi", "psi"], ["a", "b", "c"]
            for k in angles:
                cell_bounds[k] = region.get(k, [15, 165])
            for k in lengths:
                cell_bounds[k] = region.get(k, [2, 60])
            cell_bounds = CellBounds(cell_bounds)
            # --- splits
            if splits:
                splits_ = {}
                for r, p in zip(splits["repeats"], splits["probs"]):
                    splits_[tuple(r)] = p
                splits = splits_

            # --- two parameters
            test_dist_to_slab = False
            test_too_far = True

        elif system_type == "cluster":
            if not cell:
                cell = np.ones(3)*20.
            else:
                cell = np.array(cell)
            slab = Atoms(cell = cell, pbc=True)
            
            # set box to explore
            # NOTE: shape (4,3), origin+3directions
            if region is None:
                region = np.zeros((4,3))
                region[1:,:] = 0.5*cell
            else:
                region = np.array(region)
            p0, v1, v2, v3 = region

            # parameters
            box_to_place_in = [p0, [v1, v2, v3]]
            test_dist_to_slab = False
            test_too_far = False

        elif system_type == "surface":
            # read substrate
            substrate_file = params["substrate"]
            self.params["substrate"] = str(Path(substrate_file).resolve())

            surfdis = params.get("surfdis", None)
            constraint = params.get("constraint", None)

            # create the surface
            slab = read(substrate_file) # NOTE: only one structure

            # define the volume in which the adsorbed cluster is optimized
            # the volume is defined by a corner position (p0)
            # and three spanning vectors (v1, v2, v3)
            pos = slab.get_positions()
            cell = slab.get_cell().complete()
            
            # create box for atoms to explore
            if region is None:
                assert surfdis is not None, "region and surfdis cant be undefined at the same time."
                p0 = np.array([0., 0., np.max(pos[:, 2]) + surfdis[0]]) # origin of the box
                v1, v2, v3 = cell.copy()
                v3[2] = surfdis[1]
                box_to_place_in = [p0, [v1, v2, v3]]
            else:
                region = np.array(region)
                if region.shape[0] == 3:
                    # auto add origin for [0, 0, 0]
                    p0 = [0., 0., 0.]
                    v1, v2, v3 = region
                elif region.shape[0] == 4:
                    p0, v1, v2, v3 = region
                box_to_place_in = [p0, [v1, v2, v3]]

            # two parameters
            test_dist_to_slab = True
            test_too_far = True

        # define the closest distance two atoms of a given species can be to each other
        unique_atom_types = get_all_atom_types(slab, atom_numbers)
        covalent_ratio = params.get("covalent_ratio", 0.8)
        blmin = closest_distances_generator(
            atom_numbers=unique_atom_types,
            ratio_of_covalent_radii = covalent_ratio # be careful with test too far
        )

        #print("colvent ratio is: ", covalent_ratio)
        #print("neighbour distance restriction")
        #self._print_blmin(blmin)

        # create the starting population
        #rng = np.random.default_rng(params.get("seed", 1112))
        np.random.seed(params.get("seed", 1112))
        rng = np.random # TODO: require rand function

        generator = StartGenerator(
            slab, 
            blocks, # blocks
            blmin,
            number_of_variable_cell_vectors=number_of_variable_cell_vectors,
            box_to_place_in=box_to_place_in,
            box_volume=volume,
            splits=splits,
            cellbounds=cell_bounds,
            test_dist_to_slab = test_dist_to_slab,
            test_too_far = test_too_far,
            rng = rng
        ) # structure generator

        # --- NOTE: we need some attributes to access
        self.slab = slab
        self.atom_numbers_to_optimise = atom_numbers

        self.use_tags = use_tags

        self.blmin = blmin
        self.cell_bounds = cell_bounds

        # - for output
        self.type = system_type
        self.number_of_variable_cell_vectors = number_of_variable_cell_vectors

        self.box_to_place_in = box_to_place_in

        self.covalent_ratio = covalent_ratio
        self.test_dist_to_slab = test_dist_to_slab
        self.test_too_far = test_too_far

        return generator

    def _print_blmin(self, blmin):
        """"""
        elements = []
        for k in blmin.keys():
            elements.extend(k)
        elements = set(elements)
        #elements = [ase.data.chemical_symbols[e] for e in set(elements)]
        nelements = len(elements)

        index_map = {}
        for i, e in enumerate(elements):
            index_map[e] = i
        distance_map = np.zeros((nelements, nelements))
        for (i, j), dis in blmin.items():
            distance_map[index_map[i], index_map[j]] = dis

        symbols = [ase.data.chemical_symbols[e] for e in elements]

        content =  "----- Bond Distance Minimum -----\n"
        content += "covalent ratio: {}\n".format(self.covalent_ratio)
        content += " "*4+("{:>6}  "*nelements).format(*symbols) + "\n"
        for i, s in enumerate(symbols):
            content += ("{:<4}"+"{:>8.4f}"*nelements+"\n").format(s, *list(distance_map[i]))
        content += "too_far: {}, dist_to_slab: {}\n".format(self.test_too_far, self.test_dist_to_slab)
        content += "note: default too far tolerance is 2 times\n"

        return content
    
    def run(self, ran_size) -> List[Atoms]:
        """"""
        nfailed = 0
        starting_population = []
        while len(starting_population) < ran_size:
            candidate = self.generator.get_new_candidate(maxiter=self.MAX_RANDOM_TRY)
            # TODO: add some geometric restriction here
            if candidate is None:
                # print(f"This creation failed after {maxiter} attempts...")
                nfailed += 1
            else:
                if self.system_type == "cluster":
                    region_centre = np.mean(self.generator.slab.get_cell().complete(), axis=0)
                    cop = np.mean(candidate.positions, axis=0)
                    candidate.positions += region_centre - cop
                starting_population.append(candidate)
            #print("now we have ", len(starting_population))
            if nfailed > int(np.ceil(ran_size*100)):
                warnings.warn(
                    f"Too many failed generations, {nfailed} nfailed, {len(starting_population)} ngenerated...", 
                    RuntimeWarning
                )
                break

        return starting_population
    
    def as_dict(self):
        """"""
        return copy.deepcopy(self.params)
    
    def __repr__(self):
        """"""
        content = ""
        content += "----- Generator Params -----\n"
        content += f"type :{self.type}\n"
        content += f"number_of_variable_cell_vectors: {self.number_of_variable_cell_vectors}\n"

        # output summary
        vec3_format = "{:>8.4f}  {:>8.4f}  {:>8.4f}\n"
        #content += "system cell\n"
        #content +=  "xxxxxx " + vec3_format.format(*list(cell[0]))
        #content += "xxxxxx " + vec3_format.format(*list(cell[1]))
        #content += "xxxxxx " + vec3_format.format(*list(cell[2]))
        box_to_place_in = self.box_to_place_in
        if not box_to_place_in:
            box_to_place_in = [[0.,0.,0.], np.zeros((3,3))]
        p0, [v1, v2, v3] = box_to_place_in
        content += "insertion region\n"
        content +=  "origin " + vec3_format.format(*list(p0))
        content += "xxxxxx " + vec3_format.format(*list(v1))
        content += "xxxxxx " + vec3_format.format(*list(v2))
        content += "xxxxxx " + vec3_format.format(*list(v3))

        content += self._print_blmin(self.blmin)

        return content


if __name__ == "__main__":
    params = dict(
        type = "surface",
        composition = dict(
            H2O = 6
        ),
        covalent_ratio= 0.8,
        substrate = dict(
            file = "/users/40247882/repository/GDPy/examples/expedition/dynamics/substrates.xyz",
            #constraint: "0:12 24:36" # python convention
            surfdis = [1.5, 6.5]
        )
    )

    generator = RandomGenerator(params)

    frames = generator.run(9)
    write("frames.xyz", frames)