#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import pathlib
from pathlib import Path
from typing import NoReturn, List, Union

import numpy as np

import matplotlib
matplotlib.use('Agg') #silent mode
import matplotlib.pyplot as plt
plt.style.use("presentation")

from ase import Atoms
from ase.io import read, write

from ase.calculators import calculator

import ase.optimize
from ase.optimize import BFGS
from ase.constraints import FixAtoms
from ase.constraints import UnitCellFilter
from ase.neb import NEB

from abc import ABC
from abc import abstractmethod

"""
Various properties to be validated

Atomic Energy and Crystal Lattice constant

Elastic Constants

Phonon Calculations

Point Defects (vacancies, self interstitials, ...)

Surface energies

Diffusion Coefficient

Adsorption, Reaction, ...
"""


class AbstractValidator(ABC):

    def __init__(self, validation: Union[str, pathlib.Path], *args, **kwargs):
        """"""
        with open(validation, 'r') as fopen:
            valid_dict = json.load(fopen)
        self.valid_dict = valid_dict

        self.tasks = valid_dict.get("tasks", None)
        
        self.__parse_outputs(valid_dict)
        # self.calc = self.__parse_calculator(valid_dict)
        
        return
    
    def __parse_outputs(self, input_dict: dict) -> NoReturn:
        """ parse and create ouput folders and files
        """
        self.output_path = pathlib.Path(input_dict.get("output", "miaow"))
        if not self.output_path.exists():
            self.output_path.mkdir(parents=True)

        return
    
    def __parse_calculator(self, input_dict: dict) -> calculator:
        """ parse and construct ase calculator
        """
        calc_dict = input_dict.get('calculator', None)
        if calc_dict is not None:
            calc_name = calc_dict.pop('name', None)
            if calc_name == "DP":
                pass
            elif calc_name == "EANN":
                # TODO: remove this and make eann in the path
                #import sys
                #sys.path.append('/users/40247882/repository/EANN')
                from eann.interface.ase.calculator import Eann
                calc = Eann(**calc_dict)
            else:
                raise ValueError('There is no calculator {}'.format(calc_name))
        else:
            raise KeyError('No calculator keyword...')

        return calc

    @abstractmethod
    def run(self, *args, **kwargs):
        return


class MinimaValidator(AbstractValidator):

    def __init__(self, validation: Union[str, pathlib.Path], pot_manager=None):
        """ run minimisation on various configurations and
            compare relative energy
            how to postprocess
        """
        super().__init__(validation)
        self.pm = pot_manager

        self.calc = self.__parse_calculator(self.valid_dict)

        return
    
    def __parse_calculator(self, input_dict: dict) -> calculator:

        return self.pm.generate_calculator()

    def __run_dynamics(
        self, atoms, dyn_cls, dyn_opts: dict
    ):
        """"""
        init_positions = atoms.get_positions().copy()

        self.calc.reset()
        atoms.calc = self.calc
        # check bulk optimisation
        check_bulk = atoms.info.get("constraint", None)
        if check_bulk is not None:
            print("use {}".format(check_bulk))
            atoms = UnitCellFilter(atoms, constant_volume=False)
        dyn = dyn_cls(atoms)
        dyn.run(**dyn_opts)

        opt_positions = atoms.get_positions().copy()
        rmse = np.sqrt(np.var(opt_positions - init_positions))

        return atoms, rmse
    
    def __parse_dynamics(self, dyn_dict: dict):
        """"""
        cur_dict = dyn_dict.copy()
        dyn_name = cur_dict.pop('name')

        return getattr(ase.optimize, dyn_name), cur_dict
    
    def _run_group(self, group_data: dict, dyn_dict: dict):
        """ run group of structures
        """
        group_output = [] # [[name, atoms],...,[]]
        if False:
            for stru_file, cons_data in zip(group_data['structures'], group_data['constraints']):
                atoms_name = pathlib.Path(stru_file).stem
                print('===== ', atoms_name, ' =====')
                frames = read(stru_file, ':')
                assert len(frames) == 1, 'only one structure at a time now'
                atoms = frames[0]
                atoms.calc = self.calc
                if cons_data[0] == "FixAtoms":
                    if cons_data[1] is not None:
                        cons = FixAtoms(
                            indices = [atom.index for atom in atoms if atom.z < cons_data[1]]
                        )
                        atoms.set_constraint(cons)
                        print('constraint: natoms', cons)
                    else:
                        pass
                elif cons_data[0] == "UnitCellFilter":
                    atoms = UnitCellFilter(atoms, constant_volume=False)
                    print('constraint: UnitcellFilter')
                else:
                    raise ValueError("unsupported constraint type.")
                dynamics = getattr(ase.optimize, dyn_data[0])
                dyn = dynamics(atoms)
                dyn.run(dyn_data[1], dyn_data[2])
                #if self.pot.uncertainty:
                #    print(atoms.calc.results['energy_stdvar'])
                group_output.append([atoms_name, atoms])
        else:
            # read structures
            frames = []
            if isinstance(group_data['structures'], list):
                for stru_file in group_data['structures']:
                    stru_name = pathlib.Path(stru_file).stem
                    cur_frames = read(stru_file, ':')
                    assert len(cur_frames) == 1, 'only one structure in this mode' 
                    atoms = cur_frames[0]
                    atoms.info['description'] = stru_name
                    frames.append(atoms)
            else:
                #print(group_data['structures'])
                cur_frames = read(group_data['structures'], ':')
                frames.extend(cur_frames)
            
            # parse dynamics inputs
            # optimise/dynamics class, run_params
            dyn_cls, dyn_opts = self.__parse_dynamics(dyn_dict)
            
            # start dynamics
            for i, atoms in enumerate(frames):
                atoms_name = atoms.info.get('description', 'structure %d' %i)
                print(
                    'calculating {} ...'.format(atoms_name)
                )
                opt_atoms, rmse = self.__run_dynamics(
                    atoms, dyn_cls, dyn_opts
                )
                print("Structure Deviation: ", rmse)
                if self.pm.uncertainty:
                    self.calc.reset()
                    self.calc.calc_uncertainty = True
                    opt_atoms.calc = self.calc
                    energy = opt_atoms.get_potential_energy()
                    stdvar = opt_atoms.calc.results["en_stdvar"]
                    print("Final energy: {:.4f} Deviation: {:.4f}".format(energy, stdvar))
                
                group_output.append([atoms_name, atoms])

        return group_output
    
    def run(self):
        self.my_references = []
        self.outputs = []
        for (task_name, task_data) in self.tasks.items():
            print('start task ', task_name)
            basics_output = self._run_group(task_data['basics'], task_data['dynamics'])
            composites_output = self._run_group(task_data['composites'], task_data['dynamics'])
            self.outputs.append({'basics': basics_output, 'composites': composites_output})

        return
    
    def analyse(self):
        # check data
        saved_frames = []
        for (task_name, task_data), output_data in zip(self.tasks.items(), self.outputs):
            print("\n\n===== Task {0} Summary =====".format(task_name))
            basics_output = output_data['basics']
            basics_energies = []
            for (atoms_name, atoms), coef in zip(basics_output, task_data['basics']['coefs']):
                basics_energies.append(atoms.get_potential_energy()*coef)
            composites_output = output_data['composites']
            composites_references = task_data['composites'].get('references', None)
            for idx, ((atoms_name, atoms), coef) in enumerate(zip(composites_output, task_data['composites']['coefs'])):
                assert len(basics_energies) == len(coef)
                relative_energy = atoms.get_potential_energy()
                for en, c in zip(basics_energies, coef):
                    relative_energy -= c*en
                saved_frames.append(atoms)
                if composites_references is not None:
                    #if self.pot.uncertainty > 1:
                    #    # print(atoms_name, relative_energy, atoms.info['energy_stdvar'], composites_references[idx])
                    #    print(atoms_name, relative_energy, composites_references[idx])
                    #else:
                    #    print(atoms_name, relative_energy, composites_references[idx])
                    print(
                        "{0:<20s}  {1:.4f}  {2:.4f}  {3:.4f}".format(
                            atoms_name, atoms.get_potential_energy(),
                            relative_energy, composites_references[idx]
                        )
                    )
                else:
                    print(atoms_name, relative_energy)
        write(self.output_path / 'saved.xyz', saved_frames)

        return


class ReactionValidator(AbstractValidator):

    def __init__(self, validation: Union[str, pathlib.Path], pot_manager=None):
        """ reaction formula
            how to postprocess
        """
        super().__init__(validation)
        self.pm = pot_manager

        self.calc = self.__parse_calculator(self.valid_dict)

        return
    
    def __parse_calculator(self, input_dict: dict) -> calculator:

        return self.pm.generate_calculator()

    def __run_dynamics(
        self, atoms, dyn_cls, dyn_opts: dict
    ):
        """"""
        init_positions = atoms.get_positions().copy()

        self.calc.reset()
        atoms.calc = self.calc
        dyn = dyn_cls(atoms)
        dyn.run(**dyn_opts)

        opt_positions = atoms.get_positions().copy()
        rmse = np.sqrt(np.var(opt_positions - init_positions))

        return atoms, rmse

    def __parse_dynamics(self, dyn_dict: dict):
        """"""
        cur_dict = dyn_dict.copy()
        dyn_name = cur_dict.pop('name')

        return getattr(ase.optimize, dyn_name), cur_dict
    
    def run(self):
        """run NEB calculation"""
        #prepared_images = read("./start_images.xyz", ":")
        for task in self.tasks:
            print("===== Run Task {} =====".format(task))
            # parse inputs
            task_dict = self.valid_dict["tasks"][task]
            output_path = task_dict.get("output", None)
            if output_path is None:
                output_path = self.output_path
            else:
                output_path = Path(output_path)
            if not output_path.exists():
                output_path.mkdir()

            stru_path = task_dict["structure"]
            prepared_images = read(stru_path, ":")

            # parse minimisation method
            dyn_cls, dyn_params = self.__parse_dynamics(task_dict["dynamics"])

            # minimise IS and FS
            print("start IS...")
            initial = prepared_images[0].copy()
            self.calc.reset()
            initial.calc = self.calc
            dyn = dyn_cls(initial)
            dyn.run(**dyn_params)
            print("IS energy: ", initial.get_potential_energy())

            final = prepared_images[-1].copy()
            self.calc.reset()
            final.calc = self.calc
            dyn = dyn_cls(initial)
            dyn.run(**dyn_params)
            print("FS energy: ", final.get_potential_energy())

            # prepare NEB
            nimages = task_dict["neb"]["nimages"]
            images = [initial]
            if len(prepared_images) == nimages:
                print("NEB calculation uses preminised structures...")
                images.extend(prepared_images[1:-1])
            else:
                print("NEB calculation uses two structures...")
                images += [initial.copy() for i in range(nimages-2)]
            images.append(final)

            # set calculator
            self.calc.reset()
            for atoms in images:
                atoms.calc = self.calc

            # start 
            print("start NEB calculation...")
            neb = NEB(
                images, 
                allow_shared_calculator=True,
                #k=0.1
                # dynamic_relaxation = False
            )
            if len(prepared_images) == 2:
                neb.interpolate() # interpolate configurations

            traj_path = str((output_path / "neb.traj").absolute())
            #traj_path =  "./neb.traj"
            qn = dyn_cls(neb, trajectory=traj_path)
            qn.run(**dyn_params)

            # recheck energy
            opt_images = read(traj_path, "-%s:" %nimages)
            energies, en_stdvars = [], []
            for a in opt_images:
                self.calc.reset()
                a.calc = self.calc
                # EANN uncertainty
                a.calc.calc_uncertainty = True
                __dummy = a.get_forces()
                energies.append(a.get_potential_energy())
                en_stdvars.append(a.calc.results["en_stdvar"])
            energies = np.array(energies)
            energies = energies - energies[0]
            print(energies)

            # save mep
            write(output_path / "neb_opt.xyz", opt_images)

            from ase.geometry import find_mic

            differences = np.zeros(len(opt_images))
            init_pos = opt_images[0].get_positions()
            for i in range(1,nimages):
                a = opt_images[i]
                vector = a.get_positions() - init_pos
                vmin, vlen = find_mic(vector, a.get_cell())
                differences[i] = np.linalg.norm(vlen)

            # save results to file
            neb_data = output_path / "neb.dat"
            content = ""
            for i in range(nimages):
                content += "{:4d}  {:10.6f}  {:10.6f}  {:10.6f}\n".format(
                    i, differences[i], energies[i], en_stdvars[i]
                )
            with open(neb_data, "w") as fopen:
                fopen.write(content)

        return
    
    def analyse(self):

        return


class RunCalculation():

    def __init__(self):

        return 
    
    def run(self, frames, func_name):
        """"""
        func = getattr(self, func_name)
        return func(frames)
    
    @staticmethod
    def dimer(frames):
        """turn xyz into dimer data"""
        data = []
        for atoms in frames:
            # donot consider minimum image
            distance = np.linalg.norm(atoms[0].position-atoms[1].position) 
            energy = atoms.get_potential_energy()
            data.append([distance,energy])
        data = np.array(data)
    
        return np.array(data[:,0]), np.array(data[:,1])

    @staticmethod
    def volume(frames):
        """turn xyz into eos data"""
        data = []
        for atoms in frames:
            # donot consider minimum image
            vol = atoms.get_volume()
            energy = atoms.get_potential_energy()
            data.append([vol,energy])
        data = np.array(data)

        return np.array(data[:,0]), np.array(data[:,1])


class SinglePointValidator(AbstractValidator):

    """
    calculate energies on each structures and save them to file
    """

    def __init__(self, validation: Union[str, pathlib.Path], pot_manager=None):
        """ run bulk validation
        """
        super().__init__(validation)
        self.pm = pot_manager

        self.calc = self.__parse_calculator(self.valid_dict)

        self.task = self.valid_dict.get("task", None) # TODO: move this to the main function
        #self.output_path = Path(self.valid_dict.get("output", "validation"))
        #if self.output_path.exists():
        #    raise FileExistsError("The output path for current validation exists.")
        #else:
        #    self.output_path.mkdir()
        
        self.structure_paths = self.valid_dict.get("structures", None)

        return
    
    def __parse_calculator(self, input_dict: dict) -> calculator:

        return self.pm.generate_calculator()
    
    def __calc_results(self, frames: List[Atoms]):

        return

    def run(self):
        """
        lattice constant
        equation of state
        """
        if self.task == "bulk":
            for stru_path in self.structure_paths:
                # set output file name
                stru_path = Path(stru_path)
                stru_name = stru_path.stem
                fname = self.output_path / (stru_name + "-valid.dat")
                pname = self.output_path / (stru_name + "-valid.png")

                # run dp calculation
                frames = read(stru_path, ":")
                volumes = [a.get_volume() for a in frames]
                dft_energies = [a.get_potential_energy() for a in frames]

                mlp_energies = []
                self.calc.reset()
                for a in frames:
                    a.calc = self.calc
                    mlp_energies.append(a.get_potential_energy())

                # save to data file
                data = np.array([volumes, dft_energies, mlp_energies]).T
                np.savetxt(fname, data, fmt="%12.4f", header="Prop DFT MLP")

                self.plot_dimer(
                    "Bulk EOS", volumes, 
                    {
                        "DFT": dft_energies, 
                        "MLP": mlp_energies
                    },
                    pname
                )

        return

    @staticmethod
    def plot_dimer(task_name, distances, energies: dict, pname):
        """"""
        fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(12,8))
        ax.set_title(
            task_name,
            fontsize=20, 
            fontweight='bold'
        )
    
        ax.set_xlabel('Distance [Å]', fontsize=16)
        ax.set_ylabel('Energyr [eV]', fontsize=16)

        for name, en in energies.items():
            ax.scatter(distances, en, label=name)
        ax.legend()

        plt.savefig(pname)

        return

    def analyse(self):        
        # plot
        """
        fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(16,12))
        plt.suptitle(
            #"Birch-Murnaghan (Constant-Volume Optimisation)"
            "Energy-Volume Curve"
        )
    
        ax.set_xlabel("Volume [Å^3/atom]")
        ax.set_ylabel("Energy [eV/atom]")

        ax.scatter(volumes/natoms_array, dft_energies/natoms_array, marker="*", label="DFT")
        ax.scatter(volumes/natoms_array, mlp_energies/natoms_array, marker="x", label="MLP")

        ax.legend()

        plt.savefig('bm.png')
        """

        return

def run_validation(
    input_json: Union[str, pathlib.Path],
    pot_json: Union[str, pathlib.Path]
):
    """ This is a factory to deal with various validations...
    """
    # parse potential
    from GDPy.potential.manager import create_manager
    pm = create_manager(pot_json)
    print(pm.models)

    with open(input_json, "r") as fopen:
        valid_dict = json.load(fopen)

    # test surface related energies
    method = valid_dict.get("method", "minima")
    if method == "minima":
        rv = MinimaValidator(input_json, pm)
    elif method == "reaction":
        rv = ReactionValidator(input_json, pm)
    elif method == "bulk":
        rv = SinglePointValidator(input_json, pm)
    rv.run()
    rv.analyse()

    return


if __name__ == "__main__":
    pass