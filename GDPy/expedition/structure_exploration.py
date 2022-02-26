#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from abc import ABC
from os import system
from pathlib import Path
import sys
import time
import json
import yaml
import warnings

from typing import Union, Callable

import numpy as np
from joblib import Parallel, delayed

from ase import Atoms
from ase.io import read, write
from ase.calculators.singlepoint import SinglePointCalculator

from collections import Counter

from GDPy.selector.abstract import Selector
from GDPy.utils.data import vasp_creator, vasp_collector

from GDPy.expedition.abstract import AbstractExplorer
from GDPy.machine.machine import SlurmMachine


class RandomExplorer(AbstractExplorer):

    """
    Quasi-Random Structure Search
        ASE-GA, USPEX, AIRSS
    Steps
        create -> collect -> select -> calc -> harvest
    """

    # select params
    method_name = "GA"

    # general parameters
    general_params = dict(
        ignore_exists = False
    )

    # collect parameters
    collect_params = dict(
        converged_force = 0.05,
        energy_difference = 3.0, # energy difference compared to the lowest
        esvar_tol = [0.02, 0.20], # energy standard variance tolerance per atom
        fsvar_tol = [0.05, 0.25], # force standard variance tolerance per atom
        num_lowest = 200 # minimum number of local minima considered
    )


    def __init__(self, pm, main_dict: str,):
        super().__init__(main_dict)

        self.pm = pm
        atypes = ""
        self.calc = pm.generate_calculator(atypes)

        self.type_list = main_dict["type_list"]

        # parse a few general parameters
        general_params = main_dict.get("general", self.general_params)
        self.ignore_exists = general_params.get("ignore_exists", self.general_params["ignore_exists"])
        print("IGNORE_EXISTS ", self.ignore_exists)

        # database path
        main_database = main_dict.get("dataset", None) #"/users/40247882/scratch2/PtOx-dataset"
        if main_database is None:
            raise ValueError("dataset should not be None")
        else:
            self.main_database = Path(main_database)

        return
    
    def icreate(self, exp_name, working_directory):
        """ create explorations
        """
        exp_dict = self.explorations[exp_name]
        exp_systems = exp_dict["systems"]

        create_params = exp_dict.get("creation", None)
        ga_input = Path(create_params["input"])
        job_script = Path(create_params["jobscript"])

        # TODO: add an interface for json or yaml
        with open(ga_input, "r") as fopen:
            ga_dict = yaml.safe_load(fopen)

        for slabel in exp_systems:
            system_path = working_directory / exp_name / slabel
            if system_path.exists():
                print("skip {}...".format(system_path))
                continue
            else:
                system_path.mkdir(parents=True)
            # prepare inputs
            # TODO: change parameters with user inputs
            cur_ga_dict = ga_dict.copy()
            cur_ga_dict["system"]["composition"]["O"] = self.systems[slabel]["composition"]["O"]
            cur_ga_dict["calculation"]["potential"]["file"] = self.pm.models[0]
            system_input = system_path / "ga.yaml"
            with open(system_input, "w") as fopen:
                yaml.safe_dump(cur_ga_dict, fopen, indent=4)
            # job scripts
            slurm = SlurmMachine(job_script)
            slurm.machine_dict["job-name"] = self.job_prefix + "-" + slabel + "-GA"
            slurm.write(system_path / job_script.name)

        return

    def icollect(self, exp_name, working_directory):
        """ collect configurations generated by exploration...
            workflow:
            1. check results
            2. check selection
            3. collect structures based on model energy deviation
        """
        exp_dict = self.explorations[exp_name]
        exp_systems = exp_dict["systems"]

        # parse parameters for collection
        collect_params = exp_dict.get("collection", self.collect_params)
        self.converged_force = collect_params.get("converged_force", self.collect_params["converged_force"])
        self.esvar_tol = collect_params.get("esvar_tol", self.collect_params["esvar_tol"])
        self.num_lowest = collect_params.get("num_lowest", self.collect_params["num_lowest"])

        for slabel in exp_systems:
            # get compositions 
            composition = self.systems[slabel]["composition"]
            cur_type_list = self.parse_specorder(composition)
            print(self.type_list)
            print(cur_type_list)

            # check results and selection directories
            system_path = working_directory / exp_name / slabel
            print(f"===== {system_path} =====")
            results_path = system_path / "results"
            if not results_path.exists():
                print("results not exists, and skip this system...")
                continue
            selection_path = system_path / "selection"
            if selection_path.exists():
                if not self.ignore_exists:
                    print("selection exists, and skip this system...")
                    continue
                else:
                    print("selection exists, and overwrite this system...")
            else:
                selection_path.mkdir()
            
            # start collection and first selection
            candidates = read(
                system_path / "results" / "all_candidates.xyz", ":"
            )
            min_energy = candidates[0].get_potential_energy() # NOTE: energies shall be sorted
            print("Lowest Energy: ", min_energy)

            # first select configurations with 
            nconverged = 0
            converged_energies, converged_frames = [], []
            devi_info = []
            for idx, atoms in enumerate(candidates): 
                # check energy if too large then skip
                confid = atoms.info["confid"]
                # cur_energy = atoms.get_potential_energy()
                # if np.fabs(cur_energy - min_energy) > self.ENERGY_DIFFERENCE:
                #     print("Skip high-energy structure...")
                #     continue
                # GA has no forces for fixed atoms
                forces = atoms.get_forces()
                max_force = np.max(np.fabs(forces))
                #print("max_force: ", max_force)
                if max_force < self.converged_force:
                    # TODO: check uncertainty, use DeviSel
                    self.calc.reset()
                    self.calc.calc_uncertainty = True
                    atoms.calc = self.calc
                    energy = atoms.get_potential_energy()
                    enstdvar = atoms.calc.results["en_stdvar"]
                    if enstdvar < self.esvar_tol[0]*len(atoms) or enstdvar > self.esvar_tol[1]*len(atoms):
                        # print(f"{idx} small svar {enstdvar} no need to learn")
                        continue
                    maxfstdvar = np.max(atoms.calc.results["force_stdvar"])
                    # print("Var_En: ", enstdvar)
                    devi_info.append(
                        [idx, confid, energy, enstdvar, maxfstdvar]
                    )
                    nconverged += 1
                    # save calc results
                    # results = atoms.calc.results.copy()
                    # new_calc = SinglePointCalculator(atoms, **results)
                    # atoms.calc = new_calc
                    converged_energies.append(energy)
                    converged_frames.append(atoms)
                    # print("converged")
                else:
                    print(f"{idx} found unconverged")
                #if nconverged == self.NUM_LOWEST:
                #    break
            #else:
            #    print("not enough converged structures...")
            
            # create deviation file
            devi_path = selection_path / "stru_devi.out"
            content = "# INDEX GAID Energy StandardVariance f_stdvar\n"
            for info in devi_info:
                content += "{:<8d} {:<8d}  {:>8.4f}  {:>8.4f}  {:>8.4f}\n".format(
                    *info
                )
            with open(devi_path, "w") as fopen:
                fopen.write(content)
            
            # boltzmann selection on minima
            # energies = [a.get_potential_energy for a in converged_frames]
            if len(converged_frames) < self.num_lowest:
                print(
                    "Number of frames is smaller than required. {} < {}".format(
                        len(converged_frames), self.num_lowest
                    )
                )
                ratio = 1.0
                num_sel = int(np.min([self.num_lowest, ratio*len(converged_frames)]))
                print(f"adjust number of selected to {num_sel}")
            else:
                num_sel = self.num_lowest
            if num_sel < 1:
                print("no suspects, skip this system...")
                continue
            selected_frames, selected_props = self.boltzmann_histogram_selection(
                converged_energies, converged_frames, num_sel, 3.0
            ) # converged_frames will be deleted during selection
            # TODO: save converged frames
            write(selection_path / "all-converged.xyz", selected_frames)

            # collect trajectories
            traj_devi_path = selection_path / "traj_devi.out"
            with open(traj_devi_path, "w") as fopen:
                fopen.write("# GAID TRAJID Energy StandardVariance f_stdvar\n")

            traj_frames = []
            traj_count = 0
            for atoms in selected_frames:
                confid = atoms.info["confid"]
                calc_dir = system_path / "tmp_folder" / ("cand"+str(confid))
                dump_file = calc_dir / "surface.dump"
                # TODO: remove zero number...
                frames = read(dump_file, ':-1', 'lammps-dump-text', specorder=cur_type_list) # not large frame
                traj_count += len(frames)
                unlearned_frames = []
                for traj_id, traj_atoms in enumerate(frames):
                   # TODO: check uncertainty, save uncertatinty?
                    self.calc.reset()
                    self.calc.calc_uncertainty = True
                    traj_atoms.calc = self.calc
                    energy = traj_atoms.get_potential_energy()
                    enstdvar = traj_atoms.calc.results["en_stdvar"]
                    maxfstdvar = np.max(atoms.calc.results["force_stdvar"])
                    with open(traj_devi_path, "a") as fopen:
                        fopen.write(
                            "{:<8d} {:<8d}  {:>8.4f}  {:>8.4f}  {:>8.4f}\n".format(
                                confid, traj_id, energy, enstdvar, maxfstdvar
                            )
                        )
                    if self.esvar_tol[0]*len(traj_atoms) < enstdvar < self.esvar_tol[1]*len(traj_atoms):
                        # print(f"{idx} large svar {enstdvar} need to learn")
                        unlearned_frames.append(traj_atoms)
                # print("trajectory length: ", len(frames))
                traj_frames.extend(unlearned_frames)
            # TODO: check traj frames uncertainty
            print("TOTAL TRAJ FRAMES: {} out of {}".format(len(traj_frames), traj_count))
            write(selection_path / "all-traj.xyz", traj_frames)

        return
    
    def boltzmann_histogram_selection(self, props, frames, num_minima, kT=-1.0):
        """"""
        # calculate minima properties 
    
        # compute desired probabilities for flattened histogram
        histo = np.histogram(props)
        min_prop = np.min(props)
    
        config_prob = []
        for H in props:
            bin_i = np.searchsorted(histo[1][1:], H)
            if histo[0][bin_i] > 0.0:
                p = 1.0/histo[0][bin_i]
            else:
                p = 0.0
            if kT > 0.0:
                p *= np.exp(-(H-min_prop)/kT)
            config_prob.append(p)
        
        assert len(config_prob) == len(props)
    
        selected_frames = []
        for i in range(num_minima):
            # TODO: rewrite by mask 
            config_prob = np.array(config_prob)
            config_prob /= np.sum(config_prob)
            cumul_prob = np.cumsum(config_prob)
            rv = np.random.uniform()
            config_i = np.searchsorted(cumul_prob, rv)
            #print(converged_trajectories[config_i][0])
            selected_frames.append(frames[config_i])
    
            # remove from config_prob by converting to list
            config_prob = list(config_prob)
            del config_prob[config_i]
    
            # remove from other lists
            del props[config_i]
            del frames[config_i]
            
        return selected_frames, props
    
    def iselect(self, exp_name, working_directory):
        """select data from single calculation"""
        exp_dict = self.explorations[exp_name]

        included_systems = exp_dict.get("systems", None)
        if included_systems is not None:
            exp_path = working_directory / exp_name

            selected_numbers = exp_dict["selection"]["num"]
            if isinstance(selected_numbers, list):
                assert len(selected_numbers) == len(included_systems), "each system must have a number"
            else:
                selected_numbers = selected_numbers * len(included_systems)

            # loop over systems
            for slabel, num in zip(included_systems, selected_numbers):
                # check valid
                if num <= 0:
                    print("selected number is zero...")
                    continue
                # select
                sys_prefix = exp_path / slabel
                print("checking system %s ..."  %sys_prefix)
                out_xyz = sys_prefix / "selection" / (slabel + "-GA.xyz")
                if out_xyz.exists():
                    print("already selected...")
                    continue
                # TODO: must include minima
                selected_frames = self.perform_cur(sys_prefix, slabel, exp_dict, num)
                if selected_frames is None:
                    print("No candidates in {0}".format(sys_prefix))
                else:
                    write(out_xyz, selected_frames)

        return
    
    def perform_cur(self, cur_prefix, slabel, exp_dict, num):
        """"""
        soap_parameters = exp_dict['selection']['soap']
        njobs = exp_dict['selection']['njobs']
        #zeta, strategy = exp_dict['selection']['selection']['zeta'], exp_dict['selection']['selection']['strategy']
        selection_dict = exp_dict["selection"]["selection"]

        # assert soap_parameters["species"] == self.type_list
        sorted_path = cur_prefix / "selection"

        selector = Selector(soap_parameters, selection_dict, sorted_path, njobs)

        print("===== selecting system %s =====" %cur_prefix)
        if sorted_path.exists():
            all_xyz = sorted_path / "all-traj.xyz"
            if all_xyz.exists():
                print('start cur selection')
                # TODO: if unconverged
                converged_xyz = sorted_path / ("all-converged.xyz")
                converged_frames = []
                nconverged = 0
                if converged_xyz.exists():
                    converged_frames = read(converged_xyz, ":")
                    nconverged = len(converged_frames)
                    print("find converged ", nconverged)
                    num = num - nconverged
                # read structures and calculate features 
                frames = read(all_xyz, ':')
                # TODO: adjust num
                num = np.min([int(len(frames)*0.2), num])
                if (num+nconverged) < 320:
                    num = 320 - nconverged
                print("number adjust to ", num)
                # cur decomposition 
                features = selector.calc_desc(frames)
                cur_scores, selected = selector.select_structures(features, num)

                selected_frames = []
                print("Writing structure file... ")
                for idx, sidx in enumerate(selected):
                    selected_frames.append(frames[int(sidx)])
                selected_frames.extend(converged_frames)
                #write(sorted_path / (slabel+'-sel.xyz'), selected_frames)
            else:
                # no candidates
                selected_frames = None
        else:
            # raise ValueError('miaow')
            # no candidates
            selected_frames = None
            warnings.warn("sorted directory doesnot exist...", UserWarning)
        
        return selected_frames

    def icalc(self, exp_name, working_directory):
        """calculate configurations with reference method"""
        exp_dict = self.explorations[exp_name]

        # some parameters
        calc_dict = exp_dict["calculation"]
        nstructures = calc_dict.get("nstructures", 100000) # number of structures in each calculation dirs
        incar_template = calc_dict.get("incar")

        prefix = working_directory / (exp_name + "-fp")
        if prefix.exists():
            warnings.warn("fp directory exists...", UserWarning)
        else:
            prefix.mkdir(parents=True)

        # start 
        included_systems = exp_dict.get('systems', None)
        if included_systems is not None:
            # MD exploration params
            selected_numbers = exp_dict["selection"]["num"]
            if isinstance(selected_numbers, list):
                assert len(selected_numbers) == len(included_systems), "each system must have a number"
            else:
                selected_numbers = selected_numbers * len(included_systems)

            for slabel, num in zip(included_systems, selected_numbers):
                if num <= 0:
                    print("selected number is zero...")
                    continue

                name_path = working_directory / exp_name / (slabel) # system directory
                # create all calculation dirs
                sorted_path = name_path / "selection" # directory with collected xyz configurations
                collected_path = sorted_path / (slabel + "-GA.xyz")
                if collected_path.exists():
                    print("use selected frames...")
                else:
                    print("use all candidates...")
                    collected_path = sorted_path / (slabel + "_ALL.xyz")
                if collected_path.exists():
                    #frames = read(collected_path, ":")
                    #print("There are %d configurations in %s." %(len(frames), collected_path))
                    vasp_creator.create_files(
                        Path(prefix),
                        "/users/40247882/repository/GDPy/GDPy/utils/data/vasp_calculator.py",
                        incar_template,
                        collected_path
                    )
                else:
                    warnings.warn("There is no %s." %collected_path, UserWarning)

        return

    def iharvest(self, exp_name, working_directory: Union[str, Path]):
        """harvest all vasp results"""
        # run over directories and check
        main_dir = Path(working_directory) / (exp_name + "-fp")
        vasp_main_dirs = []
        for p in main_dir.glob("*-"+self.method_name+"*"):
            # use this to check if calculated
            calc_file = p / "calculated_0.xyz"
            if p.is_dir() and calc_file.exists():
                vasp_main_dirs.append(p)
        vasp_main_dirs.sort()
        print(vasp_main_dirs)

        # TODO: optional parameters
        pot_gen = Path.cwd().name
        pattern = "vasp_0_*"
        njobs = 4
        vaspfile, indices = "vasprun.xml", "-1:"

        for d in vasp_main_dirs:
            print("\n===== =====")
            # check selected GA structures
            vasp_dirs = []
            for p in d.parent.glob(d.name+"*"): # TODO: ???
                if p.is_dir():
                    vasp_dirs.extend(vasp_collector.find_vasp_dirs(p, pattern))
            print('total vasp dirs: %d' %(len(vasp_dirs)))

            print("sorted by last integer number...")
            vasp_dirs_sorted = sorted(
                vasp_dirs, key=lambda k: int(k.name.split('_')[-1])
            ) # sort by name

            # check number of frames equal output?
            input_xyz = []
            for p in d.iterdir():
                if p.name.endswith("-GA.xyz"):
                    input_xyz.append(p)
                if p.name.endswith("_ALL.xyz"):
                    input_xyz.append(p)
            if len(input_xyz) == 1:
                input_xyz = input_xyz[0]
            else:
                raise ValueError(d, " has both GA and ALL xyz file...")
            nframes_input = len(read(input_xyz, ":"))

            sys_name_list = []
            atoms = read(input_xyz, "0")
            c = Counter(atoms.get_chemical_symbols())
            for s in self.type_list:
                sys_name_list.append(s)
                num = c.get(s, 0)
                sys_name_list.append(str(num))
            sys_name = exp_name.split("-")[-1] + "-" + "".join(sys_name_list) # the first section is the exploration name without method
            print("system name: ", sys_name)
            #print(sys_name)
            system_path = self.main_database / sys_name 
            if not system_path.exists():
                system_path.mkdir()
            out_name = system_path / (d.name + "-" + pot_gen + ".xyz")
            if out_name.exists():
                nframes_out = len(read(out_name, ":"))
                if nframes_input == nframes_out == len(vasp_dirs_sorted):
                    print(d, "already has been harvested...")
                    continue

            # start to collect...
            st = time.time()
            print("using num of jobs: ", njobs)
            cur_frames = Parallel(n_jobs=njobs)(delayed(vasp_collector.extract_atoms)(p, vaspfile, indices) for p in vasp_dirs_sorted)
            frames = []
            for f in cur_frames:
                frames.extend(f) # merge all frames

            et = time.time()
            print("cost time: ", et-st)

            # move structures to data path
            if len(frames) > 0:
                print("Number of frames: ", len(frames))
                # check system
                write(out_name, frames)
            else:
                print("No frames...")
            
        # check refined (accurate) optimisation trajectory
        vasp_main_dirs = []
        for p in main_dir.glob("*-"+"accurate"+"*"):
            # use this to check if calculated
            calc_file = p / "calculated_0.xyz"
            if p.is_dir() and calc_file.exists():
                vasp_main_dirs.append(p)
        vasp_main_dirs.sort()
        if len(vasp_main_dirs) > 0:
            print("harvest accurate structure optimisation trajectories...")

        for d in vasp_main_dirs:
            print("\n===== =====")
            # check selected GA structures
            vasp_dirs = []
            for p in d.parent.glob(d.name+"*"):
                if p.is_dir():
                    vasp_dirs.extend(vasp_collector.find_vasp_dirs(p, pattern))
            print('total vasp dirs: %d' %(len(vasp_dirs)))

            print("sorted by last integer number...")
            vasp_dirs_sorted = sorted(
                vasp_dirs, key=lambda k: int(k.name.split('_')[-1])
            ) # sort by name

            st = time.time()
            print("using num of jobs: ", njobs)
            cur_frames = Parallel(n_jobs=njobs)(delayed(vasp_collector.extract_atoms)(p, vaspfile, ":") for p in vasp_dirs_sorted)
            frames = []
            for f in cur_frames:
                frames.extend(f) # merge all frames

            et = time.time()
            print("cost time: ", et-st)

            # move structures to data path
            if len(frames) > 0:
                print("Number of frames: ", len(frames))
                # check system
                atoms = frames[0]
                c = Counter(atoms.get_chemical_symbols())
                #print(c)
                sys_name_list = []
                for s in self.type_list:
                    sys_name_list.append(s)
                    num = c.get(s, 0)
                    sys_name_list.append(str(num))
                sys_name = exp_name.split("-")[-1] + "-" + "".join(sys_name_list) # the first section is the exploration name without method
                print("system name: ", sys_name)
                #print(sys_name)
                system_path = self.main_database / sys_name 
                if not system_path.exists():
                    system_path.mkdir()
                out_name = system_path / (d.name + "-" + pot_gen + ".xyz")
                write(out_name, frames)
            else:
                print("No frames...")

        return


def run_exploration(pot_json, exp_json, chosen_step, global_params = None):
    from GDPy.potential.manager import create_manager
    pm = create_manager(pot_json)
    print(pm.models)

    # create exploration
    with open(exp_json, 'r') as fopen:
        exp_dict = json.load(fopen)
    
    scout = RandomExplorer(pm, exp_dict)

    # adjust global params
    print("optional params ", global_params)
    if global_params is not None:
        assert len(global_params)%2 == 0, "optional params must be key-pair"
        for first in range(0, len(global_params), 2):
            print(global_params[first], " -> ", global_params[first+1])
            scout.default_params[chosen_step][global_params[first]] = eval(global_params[first+1])

    # compute
    op_name = "i" + chosen_step
    assert isinstance(op_name, str), "op_nam must be a string"
    op = getattr(scout, op_name, None)
    if op is not None:
        scout.run(op, "./")
    else:
        raise ValueError("Wrong chosen step %s..." %op_name)

    return
    

if __name__ == "__main__":
    # test
    pot_json = "/mnt/scratch2/users/40247882/oxides/eann-main/reduce-12/validations/potential.json"
    exp_json = "/mnt/scratch2/users/40247882/oxides/eann-main/exp-ga22.json"
    #chosen_step = "collect"
    #chosen_step = "select"
    chosen_step = "calc"
    run_exploration(pot_json, exp_json, chosen_step)