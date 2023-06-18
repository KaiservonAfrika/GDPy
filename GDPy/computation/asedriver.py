#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import copy
import dataclasses
import shutil
from pathlib import Path
import traceback
from typing import NoReturn, List, Tuple
import warnings

import numpy as np

from ase import Atoms
from ase import units

from ase.io import read, write
import ase.constraints
from ase.constraints import Filter, FixAtoms
from ase.optimize.optimize import Dynamics
from ase.md.velocitydistribution import (
    MaxwellBoltzmannDistribution, Stationary, ZeroRotation
)

from ase.calculators.singlepoint import SinglePointCalculator
from ase.calculators.mixing import MixedCalculator

from .. import config as GDPCONFIG
from GDPy.computation.driver import AbstractDriver, DriverSetting
from GDPy.computation.bias import create_bias_list
from GDPy.data.trajectory import Trajectory

from GDPy.md.md_utils import force_temperature

from GDPy.builder.constraints import parse_constraint_info
from .plumed import set_plumed_timestep


def retrieve_and_save_deviation(atoms, devi_fpath) -> NoReturn:
    """Read model deviation and add results to atoms.info if the file exists."""
    results = copy.deepcopy(atoms.calc.results)
    #devi_results = [(k,v) for k,v in results.items() if "devi" in k]
    devi_results = [(k,v) for k,v in results.items() if k in GDPCONFIG.VALID_DEVI_FRAME_KEYS]
    if devi_results:
        devi_names = [x[0] for x in devi_results]
        devi_values = np.array([x[1] for x in devi_results]).reshape(1,-1)

        if devi_fpath.exists():
            with open(devi_fpath, "a") as fopen:
                np.savetxt(fopen, devi_values, fmt="%18.6e")
        else:
            with open(devi_fpath, "w") as fopen:
                np.savetxt(
                    fopen, devi_values, fmt="%18.6e", header=("{:>18s}"*len(devi_names)).format(*devi_names)
                )

    return

def save_trajectory(atoms, log_fpath) -> NoReturn:
    """Create a clean atoms from the input and save simulation trajectory.

    We need an explicit copy of atoms as some calculators may not return all 
    necessary information. For example, schnet only returns required properties.
    If only energy is required, there are no forces.

    """
    # - save atoms
    atoms_to_save = Atoms(
        symbols=atoms.get_chemical_symbols(),
        positions=atoms.get_positions().copy(),
        cell=atoms.get_cell().copy(),
        pbc=copy.deepcopy(atoms.get_pbc())
    )
    if "tags" in atoms.arrays:
        atoms_to_save.set_tags(atoms.get_tags())
    if atoms.get_kinetic_energy() > 0.:
        atoms_to_save.set_momenta(atoms.get_momenta())
    results = dict(
        energy = atoms.get_potential_energy(),
        forces = copy.deepcopy(atoms.get_forces())
    )
    spc = SinglePointCalculator(atoms, **results)
    atoms_to_save.calc = spc

    # - save special keys and arrays from calc
    natoms = len(atoms)
    # -- add deviation
    for k, v in atoms.calc.results.items():
        if k in GDPCONFIG.VALID_DEVI_FRAME_KEYS:
            atoms_to_save.info[k] = v
    for k, v in atoms.calc.results.items():
        if k in GDPCONFIG.VALID_DEVI_ATOMIC_KEYS:
            atoms_to_save.arrays[k] = np.reshape(v, (natoms, -1))

    # -- check special metadata
    calc = atoms.calc
    if isinstance(calc, MixedCalculator):
        atoms_to_save.info["energy_contributions"] = copy.deepcopy(calc.results["energy_contributions"])
        atoms_to_save.arrays["force_contributions"] = copy.deepcopy(calc.results["force_contributions"])

    # - append to traj
    write(log_fpath, atoms_to_save, append=True)

    return

@dataclasses.dataclass
class AseDriverSetting(DriverSetting):

    driver_cls: Dynamics = None
    filter_cls: Filter = None

    fmax: float = 0.05 # eV/Ang

    def __post_init__(self):
        """"""
        # - task-specific params
        if self.task == "md":
            self._internals.update(
                velocity_seed = self.velocity_seed,
                ignore_atoms_velocities = self.ignore_atoms_velocities,
                md_style = self.md_style,
                timestep = self.timestep,
                temperature_K = self.temp,
                taut = self.Tdamp,
                pressure = self.press,
                taup = self.Pdamp,
            )
            # TODO: provide a unified class for thermostat
            if self.md_style == "nve":
                from ase.md.verlet import VelocityVerlet as driver_cls
            elif self.md_style == "nvt":
                #from GDPy.md.nosehoover import NoseHoover as driver_cls
                from ase.md.nvtberendsen import NVTBerendsen as driver_cls
            elif self.md_style == "npt":
                from ase.md.nptberendsen import NPTBerendsen as driver_cls
        
        if self.task == "min":
           # - to opt atomic positions
            from ase.optimize import BFGS
            if self.min_style == "bfgs":
                driver_cls = BFGS
            # - to opt unit cell
            #   UnitCellFilter, StrainFilter, ExpCellFilter
            # TODO: add filter params
            filter_names = ["unitCellFilter", "StrainFilter", "ExpCellFilter"]
            if self.min_style in filter_names:
                driver_cls = BFGS
                self.filter_cls = getattr(ase.constraints, self.min_style)

        if self.task == "rxn":
            # TODO: move to reactor
            try:
                from sella import Sella, Constraints
                driver_cls = Sella
            except:
                raise NotImplementedError(f"Sella is not installed.")
            ...
        
        try:
            self.driver_cls = driver_cls
        except:
            raise RuntimeError("Ase Driver Class is not defined.")

        # - shared params
        self._internals.update(
            loginterval = self.dump_period
        )

        # NOTE: There is a bug in ASE as it checks `if steps` then fails when spc.
        if self.steps == 0:
            self.steps = -1

        return
    
    def get_run_params(self, *args, **kwargs) -> dict:
        """"""
        run_params = dict(
            steps = kwargs.get("steps", self.steps),
            constraint = kwargs.get("constraint", self.constraint)
        )
        if self.task == "min" or self.task == "ts":
            run_params.update(
                fmax = kwargs.get("fmax", self.fmax),
            )
        run_params.update(**kwargs)

        return run_params


class AseDriver(AbstractDriver):

    name = "ase"

    # - defaults
    default_task = "min"
    supported_tasks = ["min", "rxn", "md"]

    # - other files
    log_fname = "dyn.log"
    traj_fname = "dyn.traj"
    xyz_fname = "traj.xyz"
    devi_fname = "model_devi-ase.dat"

    #: List of output files would be saved when restart.
    saved_fnames: List[str] = [log_fname, xyz_fname, devi_fname]

    #: List of output files would be removed when restart.
    removed_fnames: List[str] = [log_fname, traj_fname, xyz_fname, devi_fname]

    def __init__(
        self, calc=None, params: dict={}, directory="./", *args, **kwargs
    ):
        """"""
        super().__init__(calc, params, directory, *args, **kwargs)

        self.setting = AseDriverSetting(**params)

        self._log_fpath = self.directory / self.log_fname
        self._traj_fpath = self.directory / self.traj_fname

        return
    
    @property
    def log_fpath(self):
        """File path of the simulation log."""

        return self._log_fpath
    
    @property
    def traj_fpath(self):
        """File path of the simulation trajectory."""

        return self._traj_fpath
    
    @AbstractDriver.directory.setter
    def directory(self, directory_):
        """Set log and traj path regarding to the working directory."""
        # - main and calc
        super(AseDriver, AseDriver).directory.__set__(self, directory_)

        # - other files
        self._log_fpath = self.directory / self.log_fname
        self._traj_fpath = self.directory / self.traj_fname

        return 
    
    def _create_dynamics(self, atoms, *args, **kwargs) -> Tuple[Dynamics,dict]:
        """Create the correct class of this simulation with running parameters.

        Respect `steps` and `fmax` as restart.

        """
        # - overwrite 
        run_params = self.setting.get_run_params(*args, **kwargs)

        # NOTE: if have cons in kwargs overwrite current cons stored in atoms
        cons_text = run_params.pop("constraint", None)
        if cons_text is not None:
            atoms._del_constraints()
            mobile_indices, frozen_indices = parse_constraint_info(
                atoms, cons_text, ignore_ase_constraints=True, ret_text=False
            )
            if frozen_indices:
                atoms.set_constraint(FixAtoms(indices=frozen_indices))

        # - init driver
        if self.setting.task == "min":
            if self.setting.filter_cls:
                atoms = self.setting.filter_cls(atoms)
            driver = self.setting.driver_cls(
                atoms, 
                logfile=self.log_fpath,
                trajectory=str(self.traj_fpath)
            )
        elif self.setting.task == "ts":
            driver = self.setting.driver_cls(
                atoms,
                order = 1,
                internal = False,
                logfile=self.log_fpath,
                trajectory=str(self.traj_fpath)
            )
        elif self.setting.task == "md":
            # - adjust params
            init_params_ = copy.deepcopy(self.setting.get_init_params())
            velocity_seed = init_params_.pop("velocity_seed", np.random.randint(0,10000))
            rng = np.random.default_rng(velocity_seed)

            # - velocity
            if (not init_params_["ignore_atoms_velocities"] and atoms.get_kinetic_energy() > 0.):
                # atoms have momenta
                ...
            else:
                MaxwellBoltzmannDistribution(
                    atoms, temperature_K=init_params_["temperature_K"], rng=rng
                )
                if self.setting.remove_rotation:
                    ZeroRotation(atoms, preserve_temperature=False)
                if self.setting.remove_translation:
                    Stationary(atoms, preserve_temperature=False)
                # NOTE: respect constraints
                #       ase code does not consider constraints
                force_temperature(atoms, init_params_["temperature_K"], unit="K") 

            # - prepare args
            # TODO: move this part to setting post_init?
            md_style = init_params_.pop("md_style")
            if md_style == "nve":
                init_params_ = {k:v for k,v in init_params_.items() if k in ["loginterval", "timestep"]}
            elif md_style == "nvt":
                init_params_ = {
                    k:v for k,v in init_params_.items() 
                    if k in ["loginterval", "timestep", "temperature_K", "taut"]
                }
            elif md_style == "npt":
                init_params_ = {
                    k:v for k,v in init_params_.items() 
                    if k in ["loginterval", "timestep", "temperature_K", "taut", "pressure", "taup"]
                }
                init_params_["pressure"] *= (1./(160.21766208/0.000101325))

            init_params_["timestep"] *= units.fs

            # NOTE: plumed 
            set_plumed_timestep(self.calc, timestep=init_params_["timestep"])

            # - construct the driver
            driver = self.setting.driver_cls(
                atoms = atoms,
                **init_params_,
                logfile=self.log_fpath,
                trajectory=str(self.traj_fpath)
            )
        else:
            raise NotImplementedError(f"Unknown task {self.task}.")
        
        return driver, run_params

    def run(self, atoms_, read_exists: bool=True, extra_info: dict=None, *args, **kwargs) -> Atoms:
        """Run the driver.

        Additional output files would be generated, namely a xyz-trajectory and
        a deviation file if the calculator could estimate uncertainty.

        Note:
            Calculator's parameters will not change since it still performs 
            single-point calculations as the simulation goes.

        """
        atoms = copy.deepcopy(atoms_) # TODO: make minimal atoms object?

        if not self.directory.exists():
            self.directory.mkdir(parents=True)

        # - run
        converged = self.read_convergence()
        if not converged:
            # -- try to restart if it is not calculated before
            traj = self.read_trajectory()
            nframes = len(traj)
            if read_exists:
                # --- update atoms and driver settings
                # backup output files and continue with lastest atoms
                # dyn.log and dyn.traj are created when init so dont backup them
                for fname in self.saved_fnames:
                    curr_fpath = self.directory/fname
                    if curr_fpath.exists(): # TODO: check if file is empty?
                        backup_fmt = ("gbak.{:d}."+fname)
                        # --- check backups
                        idx = 0
                        while True:
                            backup_fpath = self.directory/(backup_fmt.format(idx))
                            if not Path(backup_fpath).exists():
                                shutil.copy(curr_fpath, backup_fpath)
                                break
                            else:
                                idx += 1
                # remove unnecessary files and start all over
                # retain calculator-related files
                for fname in self.removed_fnames:
                    curr_fpath = self.directory/fname
                    if curr_fpath.exists():
                        curr_fpath.unlink()
                if nframes > 0:
                    # --- update atoms
                    atoms = traj[-1]
                    # --- update run_params in settings
                    kwargs["steps"] = self.setting.get_run_params(*args, **kwargs)["steps"] + 1 - nframes
            else:
                ...
            # --- get run_params, respect steps and fmax from kwargs
            if nframes > 0:
                if not self.ignore_convergence:
                    # accept current results
                    self._irun(atoms, *args, **kwargs)
                else:
                    ...
            else:
                # not calculated before
                self._irun(atoms, *args, **kwargs)
        else:
            ...
        
        # - get results
        traj = self.read_trajectory()
        assert len(traj) > 0, "This error should not happen."

        new_atoms = traj[-1]
        if extra_info is not None:
            new_atoms.info.update(**extra_info)
        
        # - No need to reset calc params since calc is only for spc

        return new_atoms

    def _irun(self, atoms: Atoms, *args, **kwargs):
        """Run the simulation."""
        try:
            # - set calculator
            atoms.calc = self.calc

            # - set dynamics
            dynamics, run_params = self._create_dynamics(atoms, *args, **kwargs)

            # NOTE: traj file not stores properties (energy, forces) properly
            init_params = self.setting.get_init_params()
            dynamics.attach(
                save_trajectory, interval=init_params["loginterval"],
                atoms=atoms, log_fpath=self.directory/self.xyz_fname
            )
            # NOTE: retrieve deviation info
            dynamics.attach(
                retrieve_and_save_deviation, interval=init_params["loginterval"], 
                atoms=atoms, devi_fpath=self.directory/self.devi_fname
            )
            dynamics.run(**run_params)
        except Exception as e:
            self._debug(f"Exception of {self.__class__.__name__} is {e}.")
            self._debug(f"Exception of {self.__class__.__name__} is {traceback.format_exc()}.")

        return
    
    def read_force_convergence(self, *args, **kwargs) -> bool:
        """Check if the force is converged.

        Sometimes DFT failed to converge SCF due to improper structure.

        """
        # - check convergence of forace evaluation (e.g. SCF convergence)
        scf_convergence = False
        try:
            scf_convergence = self.calc.read_convergence()
        except:
            # -- cannot read scf convergence then assume it is ok
            scf_convergence = True
        if not scf_convergence:
            warnings.warn(f"{self.name} at {self.directory} failed to converge at SCF.", RuntimeWarning)
        #if not converged:
        #    warnings.warn(f"{self.name} at {self.directory} failed to converge.", RuntimeWarning)

        return scf_convergence
    
    def read_trajectory(self, *args, **kwargs):
        """Read trajectory in the current working directory."""
        traj_frames = []
        target_fpath = self.directory/self.xyz_fname
        backup_fmt = ("gbak.{:d}."+self.xyz_fname)
        if target_fpath.exists() and target_fpath.stat().st_size != 0:
            # read backups
            traj_frames = []
            idx = 0
            while True:
                backup_fname = backup_fmt.format(idx)
                backup_fpath = self.directory/backup_fname
                if backup_fpath.exists():
                    # skip last frame
                    traj_frames.extend(read(backup_fpath, index=":-1"))
                else:
                    break
                idx += 1
            # read current
            traj_frames.extend(read(self.directory/self.xyz_fname, index=":"))

            # - check the convergence of the force evaluation
            try:
                scf_convergence = self.calc.read_convergence()
            except:
                # -- cannot read scf convergence then assume it is ok
                scf_convergence = True
            if not scf_convergence:
                warnings.warn(f"{self.name} at {self.directory} failed to converge at SCF.", RuntimeWarning)
                traj_frames[0].info["error"] = f"Unconverged SCF at {self.directory}."

            init_params = self.setting.get_init_params()
            if self.setting.task == "md":
                #Time[ps]      Etot[eV]     Epot[eV]     Ekin[eV]    T[K]
                #0.0000           3.4237       2.8604       0.5633   272.4
                #data = np.loadtxt(self.directory/"dyn.log", dtype=float, skiprows=1)
                #if len(data.shape) == 1:
                #    data = data[np.newaxis,:]
                #timesteps = data[:, 0] # ps
                #steps = [int(s) for s in timesteps*1000/init_params["timestep"]]
                # ... infer from input settings
                for i, atoms in enumerate(traj_frames):
                    atoms.info["time"] = i*init_params["timestep"]
            elif self.setting.task == "min":
                # Method - Step - Time - Energy - fmax
                # BFGS:    0 22:18:46    -1024.329999        3.3947
                #data = np.loadtxt(self.directory/"dyn.log", dtype=str, skiprows=1)
                #if len(data.shape) == 1:
                #    data = data[np.newaxis,:]
                #steps = [int(s) for s in data[:, 1]]
                #fmaxs = [float(fmax) for fmax in data[:, 4]]
                for atoms in traj_frames:
                    atoms.info["fmax"] = np.max(np.fabs(atoms.get_forces(apply_constraint=True)))
            #assert len(steps) == len(traj_frames), f"Number of steps {len(steps)} and number of frames {len(traj_frames)} are inconsistent..."
            for step, atoms in enumerate(traj_frames):
                atoms.info["step"] = int(step)

            # - deviation stored in traj, no need to read from file
        else:
            ...

        return Trajectory(images=traj_frames, driver_config=dataclasses.asdict(self.setting))


if __name__ == "__main__":
    ...