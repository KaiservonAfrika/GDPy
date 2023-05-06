#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Union, List, Mapping
from itertools import groupby

import numpy as np

from ase import Atoms
from ase.formula import Formula

from GDPy.builder.constraints import convert_indices
from GDPy.graph.creator import find_molecules

"""Utilities to create a group of atoms.

This module tries to mimic the behaviour of LAMMPS group command.

"""

class Group():

    def __init__(self) -> None:
        ...


def create_a_molecule_group(atoms: Atoms, group_command: str, use_tags=True) -> List[List[int]]:
    """Find molecules in the structure."""
    args = group_command.strip().split()
    #assert args[0] in ["tag", "molecule"], f"{args[0]} is not implemented."

    if args[0] in ["tags", "molecule"]:
        groups = []
        if args[0] == "tag":
            if "tags" in atoms.arrays:
                # --- find molecuels based on tags
                natoms = len(atoms)
                tags = atoms.get_tags() # copied already
                for k, g in groupby(range(natoms), key=lambda x: tags[x]):
                    atomic_indices = list(g)
                    #symbols = [atoms[i].symbol for i in atomic_indices]
                    #formula = Formula.from_list(symbols).format("hill")
                    if str(k) in args[1:]:
                        groups.append(atomic_indices)
            else:
                raise RuntimeError("Cant find tags in atoms.")
    
        if args[0] == "molecule":
            target_molecule = args[1]
            molecules = [target_molecule]
            # --- find molecules with graph connectivity
            #raise RuntimeError("No tags in atoms.")
            valid_symbols = []
            for m in molecules:
                valid_symbols.extend(list(Formula(m).count().keys()))
            valid_symbols = set(valid_symbols)
            atomic_indices = create_a_group(atoms, "symbol {}".format(" ".join(valid_symbols)))
            fragments = find_molecules(atoms, atomic_indices)
            if target_molecule in fragments:
                groups = fragments[target_molecule]
            else:
                raise RuntimeError(f"Cant find molecule {target_molecule} in atoms.")
    else:
        # NOTE: use atomic group that equals one molecule
        groups = [create_a_group(atoms, group_command)]

    return groups


def create_a_group(atoms: Atoms, group_command: str) -> List[int]:
    """Create a group of atoms from a structure based on rules.

    Args:
        atoms: Input structure.
        group_command: Command that defines the group.

    Returns:
        List of atomic indices subject to the group command.
    
    """
    #print(group_command)
    if isinstance(group_command, str):
        args = group_command.strip().split()
        assert args[0] in ["index", "id", "region", "symbol", "tag"], f"{args[0]} is not implemented."
        nargs = len(args)
    else: # indices
        assert isinstance(group_command, list), "group command is not a list of int."
        args = ["index"]
        args.extend(group_command)

    group_indices = []

    # - (direct) index
    if args[0] == "index":
        group_indices = args[1:]

    # - id (atom index)
    if args[0] == "id":
        # NOTE: input file should follow lammps convention
        #       i.e. the index starts from 1
        group_indices = convert_indices(" ".join(args[1:]))

    # - region
    if args[0] == "region":
        region = np.array(args[1:10], dtype=np.float32)
        (ox, oy, oz, xl, yl, zl, xh, yh, zh) = region
        for i, a in enumerate(atoms):
            pos = a.position
            if ( # TODO: support more regions, only cubic box now.
                (ox+xl <= pos[0] <= ox+xh) and
                (oy+yl <= pos[1] <= oy+yh) and
                (oz+zl <= pos[2] <= oz+zh)
            ):
                group_indices.append(i)

    # - symbol
    if args[0] == "symbol":
        selected_symbols = args[1:]
        for i, a in enumerate(atoms):
            if a.symbol in selected_symbols:
                group_indices.append(i)
    
    # - tag
    if args[0] == "tag":
        tag_indices = [int(i) for i in args[1:]]
        tags = atoms.get_tags()
        group_indices = [i for (i,t) in enumerate(tags) if t in tag_indices]

    return group_indices


def create_an_intersect_group(atoms, group_commands: List[str]) -> List[int]:
    """Create an intersect group of atoms based on commands.
    """
    # - init group from the first command
    group_indices = create_a_group(atoms, group_commands[0])

    # - intersect by other commands if have any
    for group_command in group_commands[1:]:
        cur_indices = create_a_group(atoms, group_command)
        # TODO: use data type set?
        temp_indices = [i for i in cur_indices if i in group_indices]
        group_indices = temp_indices
        ...

    return group_indices


if __name__ == "__main__":
    ...