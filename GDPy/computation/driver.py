#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import abc
import copy
import dataclasses
import pathlib
import re
import shutil
import warnings

from typing import Optional, NoReturn, List, Callable
from collections.abc import Iterable

import numpy as np

from ase import Atoms
from ase.constraints import FixAtoms
from ase.calculators.calculator import compare_atoms

from GDPy import config
from GDPy.builder.constraints import parse_constraint_info

#: Prefix of backup files
BACKUP_PREFIX_FORMAT: str = "gbak.{:d}."

#: Parameter keys used to init a minimisation task.
MIN_INIT_KEYS: List[str] = ["min_style", "min_modify", "dump_period"]

#: Parameter keys used to run a minimisation task.
MIN_RUN_KEYS: List[str] = ["steps", "fmax"]

#: Parameter keys used to init a molecular-dynamics task.
MD_INIT_KEYS: List[str] = [
    "md_style", "velocity_seed", "timestep", "temp", "Tdamp", 
    "press", "Pdamp", "dump_period"
]

#: Parameter keys used to run a molecular-dynamics task.
MD_RUN_KEYS: List[str] = ["steps"]

@dataclasses.dataclass
class DriverSetting:

    """These are geometric parameters. Electronic?
    """

    #: Simulation task.
    task: str = "min"

    #: Driver setting.
    backend: str = "external"

    #: 
    min_style: str = "bfgs"
    min_modify: str = "integrator verlet tmax 4"
    maxstep: float = 0.1

    #:
    md_style: str = "nvt"

    velocity_seed: int = None

    #: Whether ignore atoms' velocities and initialise it from the scratch.
    ignore_atoms_velocities: bool = False

    #: Whether remove rotation when init velocity.
    remove_rotation: bool = True

    #: Whether remove translation when init velocity.
    remove_translation: bool = True

    timestep: float = 1.0

    temp: float = 300.
    tend: float = None
    Tdamp: float = 100. # fs

    press: float = 1.0 # bar
    pend: float = None # bar
    Pdamp: float = 100.

    #: The interval steps to dump output files (e.g. trajectory).
    dump_period: int = 1

    #: The interval steps to save a check point that is used for restart.
    ckpt_period: int = 100

    #: run params
    etol: float = None # 5e-2
    fmax: float = None # 1e-5
    steps: int = 0

    constraint: str = None

    #: Parameters that are used to update 
    _internals: dict = dataclasses.field(default_factory=dict)

    #def __post_init__(self):
    #    """A dummy function that will be overridden by subclasses."""

    #    return
    
    def get_init_params(self):
        """"""

        return copy.deepcopy(self._internals)
    
    def get_run_params(self, *args, **kwargs):
        """"""
        raise NotImplementedError(f"{self.__class__.__name__} has no function for run params.")

class AbstractDriver(abc.ABC):

    #: Driver's name.
    name: str = "abstract"

    #: Atoms that is for state check.
    atoms: Optional[Atoms] = None

    #: Standard print.
    _print: Callable = config._print

    #: Standard debug.
    _debug: Callable = config._debug

    #: Whether check the dynamics is converged, and re-run if not.
    ignore_convergence: bool = False

    #: Driver setting.
    setting: DriverSetting = None

    #: List of output files would be saved when restart.
    saved_fnames: List[str] = []

    #: List of output files would be removed when restart.
    removed_fnames: List[str] = []

    #: Systemwise parameter keys.
    syswise_keys: list = []

    #: Parameters for PotentialManager.
    pot_params: dict = None

    def __init__(self, calc, params: dict, directory="./", ignore_convergence: bool=False, *args, **kwargs):
        """Init a driver.

        Args:
            calc: The ase calculator.
            params: Driver parameters.
            directory: Working directory.

        """
        self.calc = calc
        self.calc.reset()

        self._directory = pathlib.Path(directory)

        self.ignore_convergence = ignore_convergence

        self._org_params = copy.deepcopy(params)

        return
    
    @property
    @abc.abstractmethod
    def default_task(self) -> str:
        """Default simulation task."""

        return

    @property
    @abc.abstractmethod
    def supported_tasks(self) -> List[str]:
        """Supported simulation tasks"""

        return
    
    @property
    def directory(self):
        """Set working directory of this driver.

        Note:
            The attached calculator's directory would be set as well.
        
        """

        return self._directory
    
    @directory.setter
    def directory(self, directory_):
        self._directory = pathlib.Path(directory_)
        self.calc.directory = str(self.directory) # NOTE: avoid inconsistent in ASE

        return
    
    def _map_params(self, params):
        """Map params, avoid conflicts."""
        if hasattr(self, "param_mapping"):
            params_ = {}
            for key, value in params.items():
                new_key = self.param_mapping.get(key, None)
                if new_key is not None:
                    key = new_key
                params_[key] = value
        else:
            params_ = params

        return params_
    
    def get(self, key):
        """Get param value from init/run params by a mapped key name."""
        parameters = copy.deepcopy(self.init_params)
        parameters.update(copy.deepcopy(self.run_params))

        value = parameters.get(key, None)
        if not value:
            mapped_key = self.param_mapping.get(key, None)
            if mapped_key:
                value = parameters.get(mapped_key, None)

        return value
    
    def reset(self) -> None:
        """Remove results stored in dynamics calculator."""
        self.calc.reset()

        return

    def run(self, atoms, read_ckpt: bool=True, extra_info: dict=None, *args, **kwargs) -> Atoms:
        """Return the last frame of the simulation.

        Copy input atoms, and return a new atoms. Check whether the simulation is
        finished and retrieve stored results. If necessary, extra information could 
        be added to the atoms.info.

        The simulation should either run from the scratch or restart from a given 
        checkpoint...

        """
        # - compatibility
        read_exists = kwargs.get("read_exists", None)
        if read_exists is not None:
            read_ckpt = read_exists

        # - NOTE: input atoms from WORKER may have minimal properties as
        #         cell, pbc, positions, symbols, tags, momenta...
        atoms = atoms.copy()

        # - set driver's atoms to the current one
        if isinstance(self.atoms, Atoms):
            warnings.warn("Driver has attached atoms object.", RuntimeWarning)
            system_changes = compare_atoms(atoms1=self.atoms, atoms2=atoms, tol=1e-15)
            self._debug(f"system_changes: {system_changes}")
            self._debug(f"atoms to compare: {self.atoms} {atoms}")
            if len(system_changes) > 0:
                system_changed = True
            else:
                system_changed = False
        else:
            system_changed = False

        # - backup old params
        params_old = copy.deepcopy(self.calc.parameters)

        # - run dynamics
        curr_traj = None
        if not self._verify_checkpoint():
            # If there is no valid checkpoint, just run the simulation from the scratch
            self._debug(f"... start from the scratch @ {self.directory.name} ...")
            self.directory.mkdir(parents=True, exist_ok=True)
            self._irun(atoms, *args, **kwargs)
        else:
            # If there is valid checkpoints...
            if not system_changed:
                self._debug(f"... system not changed @ {self.directory.name} ...")
                converged = self.read_convergence() # TODO: this will read_trajectory?
                self._debug(f"... convergence {converged} ...")
                if not converged:
                    if read_ckpt:
                        ckpt_wdir = self._save_checkpoint()
                        # TODO: load_ckpt will read_trajectory?
                        atoms, resume_params = self._load_checkpoint(ckpt_wdir, *args, **kwargs)
                        kwargs.update(**resume_params)
                    self._cleanup()
                    self._irun(atoms, *args, **kwargs)
                else:
                    ...
            else:
                self._debug(f"... clean up @ {self.directory.name} ...")
                self._cleanup()
                self._irun(atoms, *args, **kwargs)
        
        # - if the simulation still failed?
        
        # - get results
        traj = self.read_trajectory()
        nframes = len(traj)
        if nframes > 0:
            new_atoms = traj[-1]
            if extra_info is not None:
                new_atoms.info.update(**extra_info)
        else:
            warnings.warn(f"The calculation at {self.directory.name} performed but failed.", RuntimeWarning)
            new_atoms = None

        # - reset params
        self.calc.parameters = params_old
        self.calc.reset()

        return new_atoms
    
    def _verify_checkpoint(self, *args, **kwargs) -> bool:
        """Check whether there is a previous calculation in the `self.directory`."""

        return self.directory.exists()
    
    def _save_checkpoint(self, *args, **kwargs):
        """Save the previous simulation to a checkpoint directory."""
        # - find previous runs...
        prev_wdirs = sorted(self.directory.glob(r"[0-9][0-9][0-9][0-9][.]run"))
        self._debug(f"prev_wdirs: {prev_wdirs}")
        curr_index = len(prev_wdirs)

        curr_wdir = self.directory/f"{str(curr_index).zfill(4)}.run"
        self._debug(f"curr_wdir: {curr_wdir}")

        # - backup files
        curr_wdir.mkdir()
        for x in self.directory.iterdir():
            if not re.match(r"[0-9]{4}\.run", x.name):
                if x.name in self.saved_fnames:
                    shutil.move(x, curr_wdir)
                else:
                    x.unlink()
            else:
                ...

        return curr_wdir
    
    def _load_checkpoint(self, atoms, *args, **kwargs):
        """"""
        atoms, resume_params = self._resume(atoms, *args, **kwargs)

        return atoms, resume_params
    
    @abc.abstractmethod
    def _irun(self, atoms: Atoms, *args, **kwargs):
        """Prepare input structure (atoms) and parameters and run the simulation."""

        return

    def _backup(self):
        """Backup output files and continue with lastest atoms."""
        for fname in self.saved_fnames:
            curr_fpath = self.directory/fname
            if curr_fpath.exists(): # TODO: check if file is empty?
                backup_fmt = (BACKUP_PREFIX_FORMAT+fname)
                # --- check backups
                idx = 0
                while True:
                    backup_fpath = self.directory/(backup_fmt.format(idx))
                    if not pathlib.Path(backup_fpath).exists():
                        shutil.copy(curr_fpath, backup_fpath)
                        break
                    else:
                        idx += 1

        return
    
    def _cleanup(self):
        """Remove unnecessary files.

        Some dynamics will not overwrite old files so cleanup is needed.

        """
        # retain calculator-related files
        for fname in self.removed_fnames:
            curr_fpath = self.directory/fname
            if curr_fpath.exists():
                curr_fpath.unlink()

        return
    
    def read_convergence(self, *args, **kwargs) -> bool:
        """Read output to check whether the simulation is converged.

        TODO:
            If not converged, specific params in input files should be updated.

        """
        if self.ignore_convergence:
            return True

        # - check whether the driver is coverged
        traj_frames = self.read_trajectory() # NOTE: DEAL WITH EMPTY FILE ERROR
        nframes = len(traj_frames)

        converged = False
        if nframes > 0:
            if self.setting.steps > 0:
                step = traj_frames[-1].info["step"]
                self._debug(f"nframes: {nframes}")
                if self.setting.task == "min":
                    # NOTE: check geometric convergence (forces)...
                    #       some drivers does not store constraints in trajectories
                    atoms = traj_frames[-1]
                    run_params = self.setting.get_run_params()
                    cons_text = run_params.pop("constraint", None)
                    mobile_indices, frozen_indices = parse_constraint_info(atoms, cons_text, ret_text=False)
                    if frozen_indices:
                        atoms._del_constraints()
                        atoms.set_constraint(FixAtoms(indices=frozen_indices))
                    # TODO: Different codes have different definition for the max force
                    maxfrc = np.max(np.fabs(atoms.get_forces(apply_constraint=True)))
                    if maxfrc <= self.setting.fmax or step+1 >= self.setting.steps:
                        converged = True
                    self._debug(
                        f"MIN convergence: {converged} STEP: {step+1} >=? {self.setting.steps} MAXFRC: {maxfrc} <=? {self.setting.fmax}"
                    )
                elif self.setting.task == "md":
                    #print("steps: ", step, self.setting.steps)
                    if step+1 >= self.setting.steps: # step startswith 0
                        converged = True
                    self._debug(f"MD convergence: {converged}")
                else:
                    raise NotImplementedError("Unknown task in read_convergence.")
            else:
                # just spc, only need to check force convergence
                if nframes == 1:
                    converged = True
        else:
            ...

        # TODO: if driver converged but force (scf) is not, return True
        #       and discard this structures which is due to DFT or ...
        force_converged = True
        if hasattr(self, "read_force_convergence"):
            force_converged = self.read_force_convergence()

        return (converged and force_converged)

    @abc.abstractmethod
    def read_trajectory(self, *args, **kwargs) -> List[Atoms]:
        """Read trajectory in the current working directory.
        """

        return
    
    def as_dict(self) -> dict:
        """Return parameters of this driver."""
        params = dict(
            backend = self.name,
            ignore_convergence = self.ignore_convergence
        )
        # NOTE: we use original params otherwise internal param names would be 
        #       written out and make things confusing
        #       org_params are merged params thatv have init and run sections
        org_params = copy.deepcopy(self._org_params)

        # - update some special parameters
        constraint = self.setting.constraint
        org_params["constraint"] = constraint

        params.update(org_params)

        return params


if __name__ == "__main__":
    pass