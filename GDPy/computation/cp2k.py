#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import dataclasses
from typing import List
import pathlib
import traceback
import warnings

import numpy as np

from ase import units
from ase import Atoms
from ase.io import read, write
from ase.calculators.calculator import FileIOCalculator
from ase.calculators.singlepoint import SinglePointCalculator
from ase.calculators.cp2k import CP2K, parse_input, InputSection
from ase.constraints import FixAtoms

from .driver import DriverSetting, AbstractDriver
from ..builder.constraints import parse_constraint_info

"""Convert cp2k md outputs to ase xyz file.
"""

UNCONVERGED_SCF_FLAG: str = "*** WARNING in qs_scf.F:598 :: SCF run NOT converged ***"
ABORT_FLAG: str = "ABORT"

def read_cp2k_xyz(fpath):
    """Read xyz-like file by cp2k.

    Accept prefix-pos-1.xyz or prefix-frc-1.xyz.
    """
    # - read properties
    frame_steps, frame_times, frame_energies = [], [], []
    frame_symbols = []
    frame_properties = [] # coordinates or forces
    with open(fpath, "r") as fopen:
        while True:
            line = fopen.readline()
            if not line:
                break
            natoms = int(line.strip().split()[0])
            symbols, properties = [], []
            line = fopen.readline() # energy line
            frame_energies.append(line.strip().split()[-1])
            for i in range(natoms):
                line = fopen.readline()
                data_line = line.strip().split()
                symbols.append(data_line[0])
                properties.append(data_line[1:])
            frame_symbols.append(symbols)
            frame_properties.append(properties)

    return frame_symbols, frame_energies, frame_properties


def read_cp2k_md_outputs(wdir, prefix: str="cp2k") -> List[Atoms]:
    """"""
    wdir = pathlib.Path(wdir)

    # - positions
    pos_fpath = wdir / (prefix+"-pos-1.xyz")
    frame_symbols, frame_energies, frame_positions = read_cp2k_xyz(pos_fpath)
    # NOTE: cp2k uses a.u. and we use eV
    frame_energies = np.array(frame_energies, dtype=np.float64)
    frame_energies *= units.Hartree # 2.72113838565563E+01
    # NOTE: cp2k uses AA the same as we do
    frame_positions = np.array(frame_positions, dtype=np.float64)
    #frame_positions *= 5.29177208590000E-01
    print("shape of positions: ", frame_positions.shape)

    # - forces
    frc_fpath = wdir / (prefix+"-frc-1.xyz")
    _, _, frame_forces = read_cp2k_xyz(frc_fpath)
    # NOTE: cp2k uses a.u. and we use eV/AA
    frame_forces = np.array(frame_forces, dtype=np.float64)
    frame_forces *= units.Hartree/units.Bohr #(2.72113838565563E+01/5.29177208590000E-01)
    print("shape of forces: ", frame_forces.shape)

    # - simulation box
    # TODO: parse cell from inp or out
    box_fpath = wdir / (prefix+"-1.cell")
    with open(box_fpath, "r") as fopen:
        # Step   Time [fs]       
        # Ax [Angstrom]       Ay [Angstrom]       Az [Angstrom]       
        # Bx [Angstrom]       By [Angstrom]       Bz [Angstrom]       
        # Cx [Angstrom]       Cy [Angstrom]       Cz [Angstrom]      Volume [Angstrom^3]
        lines = fopen.readlines()
        data = np.array(
            [line.strip().split()[2:-1] for line in lines[1:]], dtype=np.float64
        )
    boxes = data

    # attach forces to frames, zip the shortest
    frames = []
    for symbols, box, positions, energy, forces in zip(
        frame_symbols, boxes, frame_positions, frame_energies, frame_forces
    ):
        atoms = Atoms(
            symbols, positions=positions,
            cell=box.reshape(3,3), 
            pbc=[1,1,1] # TODO: should determine in the cp2k input file
        )
        spc = SinglePointCalculator(
            atoms=atoms, energy=energy, 
            free_energy=energy, # TODO: depand on electronic method used
            forces=forces
        )
        atoms.calc = spc
        frames.append(atoms)
    #write(wdir/(prefix+"-MDtraj.xyz"), frames)

    return frames

@dataclasses.dataclass
class Cp2kDriverSetting(DriverSetting):

    def __post_init__(self):
        """"""
        pairs = [] # key-value pairs that avoid conflicts by same keys
        if self.task == "min":
            # - fmax and steps can be set on-the-fly, see get_run_params
            method = self.min_style.upper()
            pairs.extend(
                [
                    ("GLOBAL", "RUN_TYPE GEO_OPT"),
                    ("MOTION/GEO_OPT", "TYPE MINIMIZATION"),
                    #("MOTION/GEO_OPT", f"MAX_ITER {self.steps}"),
                    ("MOTION/GEO_OPT", f"OPTIMIZER {method}"),
                    ("MOTION/PRINT/RESTART_HISTORY/EACH", f"GEO_OPT {self.dump_period}"),
                ]
            )
            #if self.fmax is not None:
            #    pairs.append(
            #        ("MOTION/GEO_OPT", f"MAX_FORCE {self.fmax/(units.Hartree/units.Bohr)}")
            #    )
        
        if self.task == "md":
            # TODO:
            ... 
        
        # TODO: Move to manager? as we always need this outputs to convert calculation
        #       to a trajectory
        pairs.extend(
            [
                ("MOTION/PRINT/CELL", "_SECTION_PARAMETERS_ ON"),
                ("MOTION/PRINT/TRAJECTORY", "_SECTION_PARAMETERS_ ON"),
                ("MOTION/PRINT/FORCES", "_SECTION_PARAMETERS_ ON"),
            ]
        )
        self._internals["pairs"] = pairs

        return
    
    def get_run_params(self, *args, **kwargs):
        """"""
        # - convergence criteria
        fmax_ = kwargs.get("fmax", self.fmax)
        steps_ = kwargs.get("steps", self.steps)

        run_pairs = []
        if self.task == "min":
            run_pairs.append(
                ("MOTION/GEO_OPT", f"MAX_ITER {steps_}"),
            )
            if fmax_ is not None:
                run_pairs.append(
                    ("MOTION/GEO_OPT", f"MAX_FORCE {fmax_/(units.Hartree/units.Bohr)}")
                )
        if self.task == "md":
            ...

        # - add constraint
        run_params = dict(
            constraint = kwargs.get("constraint", self.constraint),
            run_pairs = run_pairs
        )

        return run_params

class Cp2kDriver(AbstractDriver):

    name = "cp2k"

    default_task = "min"
    supported_tasks = ["min", "md"]

    saved_fnames = []

    def __init__(self, calc, params: dict, directory="./", *args, **kwargs):
        """"""
        super().__init__(calc, params, directory, *args, **kwargs)

        self.setting = Cp2kDriverSetting(**params)

        return
    
    def _irun(self, atoms: Atoms, *args, **kwargs):
        """"""
        try:
            run_params = self.setting.get_run_params(**kwargs)
            run_params.update(**self.setting.get_init_params())

            # - update input template
            # GLOBAL section is automatically created...
            # FORCE_EVAL.(METHOD, POISSON)
            inp = self.calc.parameters.inp # string
            sec = parse_input(inp)
            for (k, v) in run_params["pairs"]:
                sec.add_keyword(k, v)
            for (k, v) in run_params["run_pairs"]:
                sec.add_keyword(k, v)

            # -- check constraint
            cons_text = run_params.pop("constraint", None)
            mobile_indices, frozen_indices = parse_constraint_info(atoms, cons_text, ret_text=False)
            if frozen_indices:
                #atoms._del_constraints()
                #atoms.set_constraint(FixAtoms(indices=frozen_indices))
                frozen_indices = sorted(frozen_indices)
                sec.add_keyword(
                    "MOTION/CONSTRAINT/FIXED_ATOMS", 
                    "LIST {}".format(" ".join([str(i+1) for i in frozen_indices]))
                )

            self.calc.parameters.inp = "\n".join(sec.write())

            #self.calc.set(**run_params)
            atoms.calc = self.calc

            _ = atoms.get_forces()

        except Exception as e:
            self._debug(e)
            self._debug(traceback.print_exc())

        return
    
    def read_trajectory(self, *args, **kwargs) -> List[Atoms]:
        """"""
        super().read_trajectory(*args, **kwargs)

        return

    
class Cp2kFileIO(FileIOCalculator):

    implemented_properties = ["energy", "free_energy", "forces", "stress"]
    command = None

    default_parameters = dict(
        auto_write=False,
        basis_set="DZVP-MOLOPT-SR-GTH",
        basis_set_file="BASIS_MOLOPT",
        pseudo_potential="GTH-PBE",
        potential_file="POTENTIAL",
        inp="",
        force_eval_method="Quickstep",
        charge=0,
        uks=False,
        stress_tensor=False,
        poisson_solver="auto",
        xc="PBE",
        max_scf=50,
        cutoff=400 * units.Rydberg,
        print_level="LOW"
    )

    """This calculator is consistent with v9.1 and v2022.1.
    """

    def __init__(self, restart=None, label="cp2k", atoms=None, command="cp2k.psmp", **kwargs):
        """Construct CP2K-calculator object"""
        super().__init__(restart=restart, label=label, atoms=atoms, command=command, **kwargs)

        # complete command
        command_ = self.command
        if "-i" in command_:
            ...
        else:
            label_name = pathlib.Path(self.label).name
            command_ += f" -i {label_name}.inp -o {label_name}.out"
        self.command = command_

        return

    def read_results(self):
        """"""
        super().read_results()

        label_name = pathlib.Path(self.label).name

        # check run_type
        run_type = "md"
        if run_type.upper() == "MD":
            trajectory = read_cp2k_md_outputs(self.directory, prefix=label_name)
        else:
            ... # GEO_OPT, CELL_OPT
        
        atoms = trajectory[-1]
        self.results["energy"] = atoms.get_potential_energy()
        self.results["free_energy"] = atoms.get_potential_energy(force_consistent=True)
        self.results["forces"] = atoms.get_forces()
        # TODO: stress
        
        scf_convergence = self.read_convergence()
        atoms.info["scf_convergence"] = scf_convergence
        if not scf_convergence:
            atoms.info["error"] = f"Unconverged SCF at {self.directory}."

        return
    
    def write_input(self, atoms, properties=None, system_changes=None):
        """"""
        super().write_input(atoms, properties, system_changes)

        label_name = pathlib.Path(self.label).name
        wdir = pathlib.Path(self.directory)
        with open(wdir/f"{label_name}.inp", "w") as fopen:
            fopen.write(self._generate_input())

        return
    
    def _generate_input(self):
        """Generates a CP2K input file"""
        p = self.parameters
        print(p)
        root = parse_input(p.inp)
        label_name = pathlib.Path(self.label).name
        root.add_keyword('GLOBAL', 'PROJECT ' + label_name)
        if p.print_level:
            root.add_keyword('GLOBAL', 'PRINT_LEVEL ' + p.print_level)
        #root.add_keyword("GLOBAL", "RUN_TYPE " + "CELL_OPT")
        if p.force_eval_method:
            root.add_keyword('FORCE_EVAL', 'METHOD ' + p.force_eval_method)
        if p.stress_tensor:
            root.add_keyword('FORCE_EVAL', 'STRESS_TENSOR ANALYTICAL')
            root.add_keyword('FORCE_EVAL/PRINT/STRESS_TENSOR',
                             '_SECTION_PARAMETERS_ ON')
        if p.basis_set_file:
            root.add_keyword('FORCE_EVAL/DFT',
                             'BASIS_SET_FILE_NAME ' + p.basis_set_file)
        if p.potential_file:
            root.add_keyword('FORCE_EVAL/DFT',
                             'POTENTIAL_FILE_NAME ' + p.potential_file)
        if p.cutoff:
            root.add_keyword('FORCE_EVAL/DFT/MGRID',
                             'CUTOFF [eV] %.18e' % p.cutoff)
        if p.max_scf:
            root.add_keyword('FORCE_EVAL/DFT/SCF', 'MAX_SCF %d' % p.max_scf)
            root.add_keyword('FORCE_EVAL/DFT/LS_SCF', 'MAX_SCF %d' % p.max_scf)

        if p.xc:
            legacy_libxc = ""
            for functional in p.xc.split():
                functional = functional.replace("LDA", "PADE")  # resolve alias
                xc_sec = root.get_subsection('FORCE_EVAL/DFT/XC/XC_FUNCTIONAL')
                # libxc input section changed over time
                if functional.startswith("XC_") and self._shell.version < 3.0:
                    legacy_libxc += " " + functional  # handled later
                elif functional.startswith("XC_") and self._shell.version < 5.0:
                    s = InputSection(name='LIBXC')
                    s.keywords.append('FUNCTIONAL ' + functional)
                    xc_sec.subsections.append(s)
                elif functional.startswith("XC_"):
                    s = InputSection(name=functional[3:])
                    xc_sec.subsections.append(s)
                else:
                    s = InputSection(name=functional.upper())
                    xc_sec.subsections.append(s)
            if legacy_libxc:
                root.add_keyword('FORCE_EVAL/DFT/XC/XC_FUNCTIONAL/LIBXC',
                                 'FUNCTIONAL ' + legacy_libxc)

        if p.uks:
            root.add_keyword('FORCE_EVAL/DFT', 'UNRESTRICTED_KOHN_SHAM ON')

        if p.charge and p.charge != 0:
            root.add_keyword('FORCE_EVAL/DFT', 'CHARGE %d' % p.charge)

        # add Poisson solver if needed
        if p.poisson_solver == 'auto' and not any(self.atoms.get_pbc()):
            root.add_keyword('FORCE_EVAL/DFT/POISSON', 'PERIODIC NONE')
            root.add_keyword('FORCE_EVAL/DFT/POISSON', 'PSOLVER  MT')

        # write coords
        syms = self.atoms.get_chemical_symbols()
        atoms = self.atoms.get_positions()
        for elm, pos in zip(syms, atoms):
            line = '%s %.18e %.18e %.18e' % (elm, pos[0], pos[1], pos[2])
            root.add_keyword('FORCE_EVAL/SUBSYS/COORD', line, unique=False)

        # write cell
        pbc = ''.join([a for a, b in zip('XYZ', self.atoms.get_pbc()) if b])
        if len(pbc) == 0:
            pbc = 'NONE'
        root.add_keyword('FORCE_EVAL/SUBSYS/CELL', 'PERIODIC ' + pbc)
        c = self.atoms.get_cell()
        for i, a in enumerate('ABC'):
            line = '%s %.18e %.18e %.18e' % (a, c[i, 0], c[i, 1], c[i, 2])
            root.add_keyword('FORCE_EVAL/SUBSYS/CELL', line)

        # determine pseudo-potential
        potential = p.pseudo_potential
        if p.pseudo_potential == 'auto':
            if p.xc and p.xc.upper() in ('LDA', 'PADE', 'BP', 'BLYP', 'PBE',):
                potential = 'GTH-' + p.xc.upper()
            else:
                msg = 'No matching pseudo potential found, using GTH-PBE'
                warnings.warn(msg, RuntimeWarning)
                potential = 'GTH-PBE'  # fall back

        # write atomic kinds
        subsys = root.get_subsection('FORCE_EVAL/SUBSYS').subsections
        kinds = dict([(s.params, s) for s in subsys if s.name == "KIND"])
        for elem in set(self.atoms.get_chemical_symbols()):
            if elem not in kinds.keys():
                s = InputSection(name='KIND', params=elem)
                subsys.append(s)
                kinds[elem] = s
            if p.basis_set:
                kinds[elem].keywords.append('BASIS_SET ' + p.basis_set)
            if potential:
                kinds[elem].keywords.append('POTENTIAL ' + potential)

        output_lines = ['!!! Generated by ASE !!!'] + root.write()
        return '\n'.join(output_lines)
    
    def read_convergence(self):
        """Read SCF convergence."""
        label_name = pathlib.Path(self.label).name
        cp2kout = pathlib.Path(self.directory) / f"{label_name}.out"

        converged = True
        with open(cp2kout, "r") as fopen:
            while True:
                line = fopen.readline()
                if not line:
                    break
                if line.strip() == UNCONVERGED_SCF_FLAG:
                    converged = False
                    break
                if ABORT_FLAG in line:
                    converged = False
                    break

        return converged


if __name__ == "__main__":
    # TODO: add an interface in main
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--wdir", default="./")
    parser.add_argument("-p", "--prefix", default="cp2k")
    args = parser.parse_args()

    wdir = pathlib.Path(args.wdir)
    prefix = args.prefix
    frames = read_cp2k_md_outputs(wdir, prefix)
    write(wdir/f"{prefix}-MDtraj.xyz", frames)
    ...
