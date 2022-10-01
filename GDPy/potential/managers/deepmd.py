#!/usr/bin/env python3
# -*- coding: utf-8 -*

import copy
from pathlib import Path
from typing import Union

import json

import numpy as np

from GDPy.potential.manager import AbstractPotentialManager
from GDPy.utils.command import run_command
from GDPy.trainer.train_potential import find_systems, generate_random_seed


class DeepmdManager(AbstractPotentialManager):

    name = "deepmd"

    implemented_backends = ["ase", "lammps"]

    valid_combinations = [
        ["ase", "ase"], # calculator, dynamics
        ["lammps", "ase"],
        ["lammps", "lammps"]
    ]

    def __init__(self, *args, **kwargs):
        """"""
        self.committee = None

        return
    
    def _parse_models(self):
        """"""
        if isinstance(self.models, str):
            pot_path = Path(self.models)
            pot_dir, pot_pattern = pot_path.parent, pot_path.name
            models = []
            for pot in pot_dir.glob(pot_pattern):
                models.append(str(pot/'graph.pb'))
            self.models = models
        else:
            for m in self.models:
                if not Path(m).exists():
                    raise ValueError('Model %s does not exist.' %m)

        return
    
    def _check_uncertainty_support(self):
        """"""
        self.uncertainty = False
        if len(self.models) > 1:
            self.uncertainty = True

        return
    
    def register_calculator(self, calc_params, *args, **kwargs):
        """ generate calculator with various backends
        """
        super().register_calculator(calc_params)

        # - some shared params
        command = calc_params.pop("command", None)
        directory = calc_params.pop("directory", Path.cwd())

        type_list = calc_params.pop("type_list", [])
        type_map = {}
        for i, a in enumerate(type_list):
            type_map[a] = i

        # - create specific calculator
        if self.calc_backend == "ase":
            # return ase calculator
            from deepmd.calculator import DP
            model = calc_params.get("model", None)
            if model and type_map:
                calc = DP(model=model, type_dict=type_map)
            else:
                calc = None
        elif self.calc_backend == "lammps":
            from GDPy.computation.lammps import Lammps
            #content += "pair_style      deepmd %s out_freq ${THERMO_FREQ} out_file model_devi.out\n" \
            #    %(' '.join([m for m in self.models]))

            pair_style = calc_params.get("pair_style", None)
            if pair_style:
                pair_style_name = pair_style.split()[0]
                assert pair_style_name == "deepmd", "Incorrect pair_style for deepmd..."
                calc = Lammps(command=command, directory=directory, **calc_params)
                # - update several params
                calc.units = "metal"
                calc.atom_style = "atomic"
            else:
                calc = None
        
        self.calc = calc

        return
    
    def register_trainer(self, train_params_: dict):
        """"""
        super().register_trainer(train_params_)
        # print(self.train_config)

        return
    
    def train(self, dataset=None, train_dir=Path.cwd()):
        """"""
        self._make_train_files(dataset, train_dir)

        return

    def _make_train_files(self, dataset=None, train_dir=Path.cwd()):
        """ make files for training
        """
        # - add dataset to config
        if not dataset: # NOTE: can be a path or a List[Atoms]
            dataset = self.train_dataset
        assert dataset, f"No dataset has been set for the potential {self.name}."

        # - convert dataset
        # --- custom conversion
        from GDPy.computation.utils import get_composition_from_atoms
        groups = {}
        for atoms in dataset:
            composition = get_composition_from_atoms(atoms)
            key = "".join([k+str(v) for k,v in composition])
            if key in groups:
                groups[key].append(atoms)
            else:
                groups[key] = [atoms]
        
        #for k, frames in groups.items():
        #    # - sort atoms
        #    pass
        # --- dpdata conversion
        import dpdata
        from ase.io import read, write
        train_set_dir = train_dir/"train"
        if not train_set_dir.exists():
            train_set_dir.mkdir()
        valid_set_dir = train_dir/"valid"
        if not valid_set_dir.exists():
            valid_set_dir.mkdir()
        for name, frames in groups.items():
            # --- NOTE: need convert forces to force
            frames_ = copy.deepcopy(frames) 
            for atoms in frames_:
                try:
                    forces = atoms.get_forces().copy()
                    del atoms.arrays["forces"]
                    atoms.arrays["force"] = forces
                except:
                    pass
                finally:
                    atoms.calc = None
            # --- split train and valid
            nframes = len(frames_)
            n_train = int(nframes*self.train_split_ratio)
            n_valid = int(nframes - n_train)
            if n_valid == 0:
                n_train = nframes - 1 # min_valid == 1
                n_valid = 1
            train_indices = np.random.choice(nframes, n_train, replace=False).tolist()
            valid_indices = [x for x in range(nframes) if x not in train_indices]
            train_frames = [frames_[x] for x in train_indices]
            valid_frames = [frames_[x] for x in valid_indices]
            assert len(train_frames)+len(valid_frames)==nframes, "train_valid_split failed..."
            with open(train_set_dir/f"{name}-info.txt", "w") as fopen:
                content = "# train-valid-split\n"
                content += "{}\n".format(" ".join([str(x) for x in train_indices]))
                content += "{}\n".format(" ".join([str(x) for x in valid_indices]))
                fopen.write(content)

            # --- convert data
            write(train_set_dir/f"{name}-train.xyz", train_frames)
            dsys = dpdata.MultiSystems.from_file(
                train_set_dir/f"{name}-train.xyz", fmt="quip/gap/xyz", 
                type_map = self.train_config["model"]["type_map"]
            )
            dsys.to_deepmd_npy(train_set_dir) # prec, set_size

            write(valid_set_dir/f"{name}-valid.xyz", valid_frames)
            dsys = dpdata.MultiSystems.from_file(
                valid_set_dir/f"{name}-valid.xyz", fmt="quip/gap/xyz", 
                type_map = self.train_config["model"]["type_map"]
            )
            dsys.to_deepmd_npy(valid_set_dir) # prec, set_size

        # - check train config
        # NOTE: parameters
        #       numb_steps, seed
        #       descriptor-seed, fitting_net-seed
        #       training - training_data, validation_data
        train_config = copy.deepcopy(self.train_config)

        train_config["model"]["descriptor"]["seed"] = np.random.randint(0,10000)
        train_config["model"]["fitting_net"]["seed"] = np.random.randint(0,10000)

        data_dirs = list(str(x.resolve()) for x in (train_dir/"train").iterdir() if x.is_dir())
        train_config["training"]["training_data"]["systems"] = data_dirs
        #train_config["training"]["batch_size"] = 32

        data_dirs = list(str(x.resolve()) for x in (train_dir/"valid").iterdir() if x.is_dir())
        train_config["training"]["validation_data"]["systems"] = data_dirs

        train_config["training"]["seed"] = np.random.randint(0,10000)

        # - write
        with open(train_dir/"config.json", "w") as fopen:
            json.dump(train_config, fopen, indent=2)

        return

    def freeze(self, train_dir=Path.cwd()):
        """ freeze model and return a new calculator
            that may have a committee for uncertainty
        """
        # - find subdirs
        train_dir = Path(train_dir)
        mdirs = []
        for p in train_dir.iterdir():
            if p.is_dir() and p.name.startswith("m"):
                mdirs.append(p.resolve())
        assert len(mdirs) == self.train_size, "Number of models does not equal model size..."

        # - find models and form committee
        models = []
        for p in mdirs:
            models.append(str(p/"graph.pb"))
        
        if self.calc_backend == "ase":
            committee = []
            for i, m in enumerate(models):
                calc_params = copy.deepcopy(self.calc_params)
                calc_params.update(backend=self.calc_backend)
                calc_params["file"] = m
                saved_calc_params = copy.deepcopy(calc_params)
                self.register_calculator(calc_params)
                self.calc.directory = Path.cwd()/f"c{i}"
                committee.append(self.calc)
            # NOTE: do not share calculator...
            self.register_calculator(saved_calc_params)
            if len(committee) > 1:
                self.committee = committee
        elif self.calc_backend == "lammps":
            calc_params = copy.deepcopy(self.calc_params)
            calc_params.update(backend=self.calc_backend)
            # - set out_freq and out_file in lammps
            calc_params["pair_style"] = "deepmd {}".format(" ".join(models))
            saved_calc_params = copy.deepcopy(calc_params)
            self.register_calculator(calc_params)
            # NOTE: do not share calculator...
            if len(models) > 1:
                self.committee = [self.register_calculator(saved_calc_params)]

        return

    def check_finished(self, model_path):
        """check if the training is finished"""
        converged = False
        model_path = Path(model_path)
        dpout_path = model_path / "dp.out"
        if dpout_path.exists():
            content = dpout_path.read_text()
            line = content.split('\n')[-3]
            print(line)
            #if 'finished' in line:
            #    converged = True

        return converged


if __name__ == "__main__":
    from ase.io import read, write
    frames = read("/mnt/scratch2/users/40247882/ZnCuOx/PtWater/deepmd-gpu/init-data.xyz", ":")

    potter = DeepmdManager()
    potter.train_config = dict(type_map={"H": 0, "O": 1, "Pt": 2})
    potter.train(dataset=frames, train_dir=Path.cwd()/"dptrain")
    pass