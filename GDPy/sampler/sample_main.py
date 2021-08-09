#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from math import frexp
import re
import shutil
import json
import sys
import warnings
import pathlib
import numpy as np
from numpy.core.fromnumeric import sort
from numpy.lib.type_check import common_type
import numpy.ma as ma

from ase.io import read, write
from ase.io.lammpsrun import read_lammps_dump_text
from ase.data import atomic_numbers, atomic_masses

from GDPy.calculator.ase_interface import AseInput
from GDPy.calculator.inputs import LammpsInput
from GDPy.selector.structure_selection import calc_feature, cur_selection

from GDPy.machine.machine import SlurmMachine


class Sampler():

    """
    Exploration Strategies
        1. random structure sampling
        2. samll pertubations on given structures
        3. molecular dynamics with surrogate potential
        4. molecular dynamics with uncertainty-aware potential
    
    Initial Systems
        initial structures must be manually prepared
    
    Units
        fs, eV, eV/AA
    """

    supported_potentials = ["reax", "deepmd", "eann"]

    # set default variables
    # be care with the unit
    default_variables = dict(
        nsteps = 0, 
        thermo_freq = 0, 
        dtime = 0.002, # ps
        temp = 300, # Kelvin
        pres = -1, # bar
        tau_t = 0.1, # ps
        tau_p = 0.5 # ps
    )

    def __init__(self, pm, main_dict: dict):
        """"""
        self.pot_manager = pm
        self.type_map = main_dict['type_map']
        self.explorations = main_dict['explorations']
        self.init_systems = main_dict['systems']

        assert self.pot_manager.type_map == self.type_map, 'type map should be consistent'

        return
    
    @staticmethod
    def map_md_variables(default_variables, exp_dict: dict, unit='default'):
        
        # update variables
        temperatures = exp_dict.pop('temperatures', None)
        pressures = exp_dict.pop('pressures', None)

        sample_variables = default_variables.copy()
        sample_variables['nsteps'] = exp_dict['nsteps']
        sample_variables['dtime'] = exp_dict['timestep']
        sample_variables['thermo_freq'] = exp_dict.get('freq', 10)
        sample_variables['tau_t'] = exp_dict.get('tau_t', 0.1)
        sample_variables['tau_p'] = exp_dict.get('tau_p', 0.5)

        return temperatures, pressures, sample_variables
    
    def create(self, working_directory):
        """create for all explorations"""
        working_directory = pathlib.Path(working_directory)
        for exp_name in self.explorations.keys():
            self.icreate(exp_name, working_directory)
        return

    def icreate(self, exp_name, working_directory):
        """create for each exploration"""
        exp_dict = self.explorations[exp_name]
        job_script = exp_dict.get('jobscript', None)
        included_systems = exp_dict.get('systems', None)
        if included_systems is not None:
            # check potential parameters
            #potential = exp_dict.pop("potential", None) 
            #if potential not in self.supported_potentials:
            #    raise ValueError("Potential %s is not supported..." %potential)

            # MD exploration params
            exp_params = exp_dict['params']
            thermostat = exp_params.pop('thermostat', None)
            temperatures, pressures, sample_variables = self.map_md_variables(self.default_variables, exp_params) # be careful with units
            # loop over systems
            for slabel in included_systems:
                system_dict = self.init_systems[slabel] # system name
                structure = system_dict['structure']
                scomp = system_dict['composition'] # system composition
                atypes = []
                for atype, number in scomp.items():
                    if number > 0:
                        atypes.append(atype)

                cons = system_dict.get('constraint', None)
                name_path = working_directory / exp_name / (slabel+'-'+thermostat)
                # create directories
                # check single data or a list of structures
                runovers = [] # [(structure,working_dir),...,()]
                if structure.endswith('.data'):
                    runovers.append((structure,name_path))
                else:
                    data_path = pathlib.Path(system_dict['structure'])
                    for f in data_path.glob(slabel+'*'+'.data'):
                        cur_path = name_path / f.stem
                        runovers.append((f, cur_path))
                # create all 
                calc_input = self.create_input(self.pot_manager, atypes, sample_variables) # use inputs with preset md params
                for (stru_path, work_path) in runovers:
                    self.create_exploration(
                        work_path, job_script, calc_input, stru_path, cons, temperatures, pressures
                    )

        return
    
    def create_input(
        self, pot_manager, 
        atypes: list,
        md_params: dict
    ):
        """ create calculation input object
        """
        # create calculation input object
        calc = pot_manager.generate_calculator(atypes)
        if pot_manager.backend == "ase":
            calc_input = AseInput(atypes, calc, md_params)
        elif pot_manager.backend == "lammps":
            calc_input = LammpsInput(atypes, calc, md_params)

        return calc_input
    
    def create_exploration(self, name_path, job_script, calc_input, structure, cons, temperatures, pressures):
        """"""
        try:
            name_path.mkdir(parents=True)
            print('create this %s' %name_path)
            # create job script
            if job_script is not None:
                job_script = pathlib.Path(job_script)
                ## shutil.copy(job_script, name_path / job_script.name)
                #with open(name_path / job_script.name, 'w') as fopen:
                #    fopen.write(create_test_slurm(name_path.name))
                slurm = SlurmMachine(job_script)
                slurm.machine_dict['job-name'] = name_path.name
                slurm.write(name_path / job_script.name)

            # TODO: transform this purepath to a slurm machine, maybe sumbit?

        except FileExistsError:
            print('skip this %s' %name_path)
            return
        
        # bind structure
        calc_input.bind_structure(structure, cons)
        
        # create input directories with various thermostats
        if calc_input.thermostat == 'nvt':
            for temp in temperatures:
                temp_dir = name_path / str(temp)
                try:
                    temp_dir.mkdir(parents=True)
                except FileExistsError:
                    print('skip this %s' %temp_dir)
                    continue
                calc_input.temp = temp
                calc_input.write(temp_dir)
        elif calc_input.thermostat == 'npt':
            for temp in temperatures:
                for pres in pressures:
                    temp_dir = name_path / (str(temp)+'_'+str(pres))
                    try:
                        temp_dir.mkdir(parents=True)
                    except FileExistsError:
                        print('skip this %s' %temp_dir)
                        continue
                    calc_input.temp = temp
                    calc_input.pres = pres
                    calc_input.write(temp_dir)
        else:
            raise NotImplementedError('no other thermostats')

        return
    
    def collect(self, working_directory):
        # backend and potential
        working_directory = pathlib.Path(working_directory)
        for exp_name in self.explorations.keys():
            exp_directory = working_directory / exp_name
            if exp_directory.exists():
                self.icollect(exp_name, working_directory)
            else:
                warnings.warn('there is no %s ...' %exp_directory, UserWarning)

        return

    def icollect(self, exp_name, working_directory, skipped_systems=[]):
        """collect data from single calculation"""
        exp_dict = self.explorations[exp_name]
        # deviation
        devi = exp_dict.get('deviation', None)

        included_systems = exp_dict.get('systems', None)
        if included_systems is not None:
            md_prefix = working_directory / exp_name
            print("checking system %s ..."  %md_prefix)
            exp_params = exp_dict['params']
            thermostat = exp_params.pop('thermostat', None)
            temperatures, pressures, sample_variables = self.map_md_variables(self.default_variables, exp_params) # be careful with units

            # loop over systems
            for slabel in included_systems:
                # TODO: make this into system
                if slabel in skipped_systems:
                    continue
                # TODO: better use OrderedDict
                system_dict = self.init_systems[slabel] # system name
                scomp = system_dict['composition'] # system composition
                elem_map = self.type_map.copy()
                for ele, num in scomp.items():
                    if num == 0:
                        elem_map.pop(ele, None)
                elements = list(elem_map.keys())
                # check thermostats
                if thermostat == 'nvt':
                    sys_prefix = md_prefix / (slabel+'-'+thermostat)
                    
                    if system_dict.get('structures', None):
                        # run over many structures
                        data_path = pathlib.Path(system_dict['structures'][0])
                        nconfigs = len(list(data_path.glob(slabel+'*'+'.data'))) # number of starting configurations
                        for i in range(nconfigs):
                            cur_prefix = sys_prefix / (slabel + '-' + str(i))
                            # make sort dir
                            sorted_path = cur_prefix / 'sorted'
                            print("===== collecting system %s =====" %cur_prefix)
                            if sorted_path.exists():
                                self.override = True
                                if self.override:
                                    warnings.warn('sorted_path removed in %s' %cur_prefix, UserWarning)
                                    shutil.rmtree(sorted_path)
                                    sorted_path.mkdir()
                                else:
                                    warnings.warn('sorted_path exists in %s' %cur_prefix, UserWarning)
                                    continue
                            else:
                                sorted_path.mkdir()
                            # extract frames
                            all_frames = []
                            for temp in temperatures:
                                # read dump
                                temp = str(temp)
                                dump_xyz = cur_prefix/temp/'traj.dump'
                                if dump_xyz.exists():
                                    frames = read(dump_xyz, ':', 'lammps-dump-text', specorder=elements)[1:]
                                else:
                                    dump_xyz = cur_prefix/temp/'traj.xyz'
                                    if dump_xyz.exists():
                                        frames = read(dump_xyz, ':')[1:]
                                    else:
                                        warnings.warn('no trajectory file in %s' %dump_xyz, UserWarning)
                                        continue
                                print('nframes at temp %sK: %d' %(temp,len(frames)))

                                frames = self.extract_deviation(cur_prefix/temp, frames, devi)

                                # sometimes all frames have small deviations
                                if frames:
                                    out_xyz = str(sorted_path/temp)
                                    write(out_xyz+'.xyz', frames)
                                    all_frames.extend(frames)

                            print('TOTAL NUMBER OF FRAMES %d in %s' %(len(all_frames),cur_prefix))
                            write(sorted_path/str(slabel+'_ALL.xyz'), all_frames)
                    else:
                        # make sort dir
                        sorted_path = sys_prefix / 'sorted'
                        print("===== collecting system %s =====" %sys_prefix)
                        if sorted_path.exists():
                            warnings.warn('sorted_path exists in %s' %sys_prefix, UserWarning)
                            continue
                        else:
                            sorted_path.mkdir()
                        # extract frames
                        all_frames = []
                        for temp in temperatures:
                            # read dump
                            temp = str(temp)
                            dump_xyz = sys_prefix/temp/'traj.dump'
                            if dump_xyz.exists():
                                frames = read(dump_xyz, ':', 'lammps-dump-text', specorder=elements)[1:]
                            else:
                                dump_xyz = sys_prefix/temp/'traj.xyz'
                                if dump_xyz.exists():
                                    frames = read(dump_xyz, ':')[1:]
                                else:
                                    warnings.warn('no trajectory file in %s' %dump_xyz, UserWarning)
                                    continue
                            print('nframes at temp %sK: %d' %(temp,len(frames)))

                            frames = self.extract_deviation(sys_prefix/temp, frames, devi)

                            # sometimes all frames have small deviations
                            if frames:
                                out_xyz = str(sorted_path/temp)
                                write(out_xyz+'.xyz', frames)
                                all_frames.extend(frames)

                        print('TOTAL NUMBER OF FRAMES %d in %s' %(len(all_frames),sys_prefix))
                        write(sorted_path/str(slabel+'_ALL.xyz'), all_frames)
                else:
                    raise NotImplementedError('no other thermostats')

        return
    
    def extract_deviation(self, cur_dir, frames, devi=None):
        # read deviation
        if devi is not None:
            low_devi, high_devi = devi
            devi_out = cur_dir / 'model_devi.out'
            # TODO: DP and EANN has different formats
            # max_fdevi = np.loadtxt(devi_out)[1:,4] # DP
            max_fdevi = np.loadtxt(devi_out)[1:,5] # EANN

            err =  '%d != %d' %(len(frames), max_fdevi.shape[0])
            assert len(frames) == max_fdevi.shape[0], err # not necessary

            max_fdevi = max_fdevi.flatten().tolist() # make it a list
            unlearned_generator = filter(
                lambda x: True if low_devi < x[1] < high_devi else False,
                zip(frames,max_fdevi)
            )
            unlearned_frames = [x[0] for x in list(unlearned_generator)]

            nlearned = len(list(filter(lambda x: True if x < low_devi else False, max_fdevi)))
            nfailed = len(list(filter(lambda x: True if x > high_devi else False, max_fdevi)))
            print(
                'learned: %d candidate: %d failed: %d\n' 
                %(nlearned,len(unlearned_frames),nfailed)
            )
            # print(unlearned_frames)
            frames = unlearned_frames
        else:
            pass

        return frames
    
    def select(self, working_directory):
        # backend and potential
        working_directory = pathlib.Path(working_directory)
        for exp_name in self.explorations.keys():
            exp_directory = working_directory / exp_name
            if exp_directory.exists():
                self.iselect(exp_name, working_directory)
            else:
                warnings.warn('there is no %s ...' %exp_directory, UserWarning)

        return
    
    def iselect(self, exp_name, working_directory):
        """select data from single calculation"""
        exp_dict = self.explorations[exp_name]

        pattern = "surf-9O*"

        included_systems = exp_dict.get('systems', None)
        if included_systems is not None:
            md_prefix = working_directory / exp_name
            print("checking system %s ..."  %md_prefix)
            exp_params = exp_dict['params']
            thermostat = exp_params.pop('thermostat', None)
            temperatures, pressures, sample_variables = LammpsInput.map_md_variables(exp_params)

            # loop over systems
            for slabel in included_systems:
                if re.match(pattern, slabel):
                    # TODO: better use OrderedDict
                    system_dict = self.init_systems[slabel] # system name
                    if thermostat == 'nvt':
                        sys_prefix = md_prefix / (slabel+'-'+thermostat)
                        if True: # run over configurations
                            sorted_dirs = []
                            for p in sys_prefix.glob(pattern):
                                sorted_dirs.append(p)
                            sorted_dirs.sort()

                            total_selected_frames = []
                            for p in sorted_dirs:
                                print(p)
                                selected_frames = self.perform_cur(p, slabel, exp_dict)
                                total_selected_frames.extend(selected_frames)
                            write(sys_prefix / (slabel + '-tot-sel.xyz'), total_selected_frames)

                        else:
                            selected_frames = self.perform_cur(sys_prefix, slabel, exp_dict)

                    else:
                        # TODO: npt
                        pass
                else:
                    warnings.warn('%s is not valid for the pattern %s.' %(slabel, pattern), UserWarning)

        return
    
    def perform_cur(self, cur_prefix, slabel, exp_dict):
        """"""
        soap_parameters = exp_dict['selection']['soap']
        njobs = exp_dict['selection']['njobs']
        num = exp_dict['selection']['num']
        zeta, strategy = exp_dict['selection']['selection']['zeta'], exp_dict['selection']['selection']['strategy']

        sorted_path = cur_prefix / 'sorted'
        print("===== selecting system %s =====" %cur_prefix)
        if sorted_path.exists():
            all_xyz = sorted_path / str(slabel+'_ALL.xyz')
            if all_xyz.exists():
                print('wang')
                # read structures and calculate features 
                frames = read(all_xyz, ':')
                features_path = sorted_path / 'features.npy'
                print(features_path.exists())
                if features_path.exists():
                    features = np.load(features_path)
                    assert features.shape[0] == len(frames)
                else:
                    print('start calculating features...')
                    features = calc_feature(frames, soap_parameters, njobs, features_path)
                    print('finished calculating features...')
                # cur decomposition 
                cur_scores, selected = cur_selection(features, num, zeta, strategy)
                content = '# idx cur sel\n'
                for idx, cur_score in enumerate(cur_scores):
                    stat = 'F'
                    if idx in selected:
                        stat = 'T'
                    content += '{:>12d}  {:>12.8f}  {:>2s}\n'.format(idx, cur_score, stat) 
                with open(sorted_path / 'cur_scores.txt', 'w') as writer:
                    writer.write(content)

                selected_frames = []
                print("Writing structure file... ")
                for idx, sidx in enumerate(selected):
                    selected_frames.append(frames[int(sidx)])
                write(sorted_path / (slabel+'-sel.xyz'), selected_frames)
                print('')
            else:
                pass
        else:
            raise ValueError('miaow')
        
        return selected_frames
    

def run_exploration(pot_json, exp_json, chosen_step):
    # create potential manager
    with open(pot_json, 'r') as fopen:
        pot_dict = json.load(fopen)
    from ..potential.manager import PotManager
    mpm = PotManager() # main potential manager
    pm = mpm.create_potential(
        pot_dict['name'], pot_dict['backend'], 
        **pot_dict['kwargs']
    )
    print(pm.models)

    # create exploration
    with open(exp_json, 'r') as fopen:
        exp_dict = json.load(fopen)
    
    scout = Sampler(pm, exp_dict)
    if chosen_step == 'create':
        scout.create('./')
    elif chosen_step == "collect":
        scout.collect("./")
    else:
        pass

    return


if __name__ == '__main__':
    import json
    with open('/users/40247882/repository/GDPy/templates/inputs/main.json', 'r') as fopen:
        main_dict = json.load(fopen)
    
    exp_dict = main_dict['explorations']['reax-surface-diffusion']
    md_prefix = pathlib.Path('/users/40247882/projects/oxides/gdp-main/reax-metad')
    init_systems = main_dict['systems']
    type_map = {'O': 0, 'Pt': 1}

    icollect_data(exp_dict, md_prefix, init_systems, type_map)
    pass
