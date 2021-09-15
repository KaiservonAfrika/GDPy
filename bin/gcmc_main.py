#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import yaml
import argparse
from pathlib import Path

from ase.io import read, write
from ase.constraints import FixAtoms

from GDPy.mc.gcmc import ReducedRegion, GCMC

"""
constraints are read from xyz property move_mask
"""

parser = argparse.ArgumentParser()
parser.add_argument(
    'INPUT', 
    default='gc.json', 
    help='grand canonical inputs'
)
parser.add_argument(
    '-r', '--run', action='store_true',
    help='run GA procedure'
)


args = parser.parse_args()

input_file = Path(args.INPUT)
# print(input_file.suffix)
if input_file.suffix == ".json":
    with open(input_file, "r") as fopen:
        gc_dict = json.load(fopen)
elif input_file.suffix == ".yaml":
    with open(input_file, "r") as fopen:
        gc_dict = yaml.safe_load(fopen)
else:
    raise ValueError("wrong input file format...")
with open("params.json", "w") as fopen:
    json.dump(gc_dict, fopen, indent=4)
print("See params.json for values of all parameters...")

# set initial structure - bare metal surface
atoms = read(gc_dict["structure"])

#res = Reservior(particle='O', temperature=300, pressure=1.0, mu=chemical_potential) # Kelvin, atm, eV

# set region
region = ReducedRegion(atoms.cell, caxis=gc_dict["region"]["caxis"], mindis=gc_dict["region"]["mindis"])

# start mc
transition_array = gc_dict["probabilities"] # move and exchange
gcmc = GCMC(gc_dict["type_list"], gc_dict["reservior"], atoms, region, transition_array)


if args.run:
    gcmc.run(gc_dict["nattempts"], gc_dict["calculation"])


if __name__ == "__main__":
    pass