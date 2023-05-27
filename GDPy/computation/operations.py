#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import itertools
import pathlib
import time
from typing import NoReturn, Union, List

from ase import Atoms
from ase.io import read, write

from GDPy.core.operation import Operation
from GDPy.core.register import registers
from GDPy.computation.worker.drive import (
    DriverBasedWorker, CommandDriverBasedWorker, QueueDriverBasedWorker
)

@registers.operation.register
class work(Operation):

    """Create a list of workers by necessary components (potter, drivers, and scheduler).
    """

    def __init__(self, potter, driver, scheduler, custom_wdirs=None, directory="./", *args, **kwargs) -> NoReturn:
        """"""
        super().__init__(input_nodes=[potter,driver,scheduler], directory=directory)

        # Custom worker directories.
        self.custom_wdirs = custom_wdirs

        return
    
    def forward(self, potter, drivers: List[dict], scheduler) -> List[DriverBasedWorker]:
        """"""
        super().forward()

        # - check if there were custom wdirs, and zip longest
        ndrivers = len(drivers)
        if self.custom_wdirs is not None:
            wdirs = [pathlib.Path(p) for p in self.custom_wdirs]
        else:
            wdirs = [self.directory/f"w{i}" for i in range(ndrivers)]
        
        nwdirs = len(wdirs)
        assert (nwdirs==ndrivers and ndrivers>1) or (nwdirs>=1 and ndrivers==1), "Invalid wdirs and drivers."
        pairs = itertools.zip_longest(wdirs, drivers, fillvalue=drivers[0])

        # - create workers
        # TODO: broadcast potters, schedulers as well?
        workers = []
        for wdir, driver_params in pairs:
            # workers share calculator in potter
            driver = potter.create_driver(driver_params)
            if scheduler.name == "local":
                worker = CommandDriverBasedWorker(potter, driver, scheduler)
            else:
                worker = QueueDriverBasedWorker(potter, driver, scheduler)
            # wdir is temporary as it may be reset by drive operation
            worker.directory = wdir
            workers.append(worker)
        
        self.status = "finished"

        return workers

@registers.operation.register
class zip_workers(Operation):

    def __init__(self, *args, **kwargs) -> NoReturn:
        """"""
        worker_node = args[0]
        self.target_wdirs = [pathlib.Path(p) for p in args[1:]]

        super().__init__(worker_node)
    
    def forward(self, workers):
        """"""
        super().forward()

        nworkers = len(workers)
        assert nworkers == 1, "Zip can only apply on one worker."

        worker = workers[0]

        new_workers = []
        for wdir in self.target_wdirs:
            curr_worker = []
            ...

        return

@registers.operation.register
class distill(Operation):

    def __init__(self, worker_node: work) -> NoReturn:
        """"""
        super().__init__([worker_node])
    
    def forward(self, workers: List[DriverBasedWorker]):
        """"""
        super().forward()
        worker = workers[0]
        print(worker.directory)
        ret = worker.retrieve(
            ignore_retrieved=False
        )

        return workers

@registers.operation.register
class drive(Operation):

    """Drive structures.
    """

    def __init__(
        self, builder, worker, batchsize: int=None, directory="./",
    ):
        """"""
        super().__init__(input_nodes=[builder, worker], directory=directory)

        self.batchsize = batchsize

        return
    
    def forward(self, frames, workers: List[DriverBasedWorker]) -> List[DriverBasedWorker]:
        """Run simulations with given structures and workers.

        Workers' working directory and batchsize are probably set.

        Returns:
            Workers with correct directory and batchsize.

        """
        super().forward()

        # - basic input candidates
        nframes = len(frames)

        # - create workers
        for i, worker in enumerate(workers):
            worker.directory = self.directory / f"w{i}"
            if self.batchsize is not None:
                worker.batchsize = self.batchsize
            else:
                worker.batchsize = nframes
        nworkers = len(workers)

        if nworkers == 1:
            workers[0].directory = self.directory

        # - run workers
        worker_status = []
        for i, worker in enumerate(workers):
            flag_fpath = worker.directory/"FINISHED"
            self.pfunc(f"run worker {i} for {nframes} nframes")
            if not flag_fpath.exists():
                worker.run(frames)
                worker.inspect(resubmit=True) # if not running, resubmit
                if worker.get_number_of_running_jobs() == 0:
                    with open(flag_fpath, "w") as fopen:
                        fopen.write(
                            f"FINISHED AT {time.asctime( time.localtime(time.time()) )}."
                        )
                    worker_status.append(True)
                else:
                    worker_status.append(False)
            else:
                with open(flag_fpath, "r") as fopen:
                    content = fopen.readlines()
                self.pfunc(content)
                worker_status.append(True)
        
        if all(worker_status):
            self.status = "finished"

        return workers

@registers.operation.register
class extract(Operation):

    """Extract dynamics trajectories from a drive-node's worker.
    """

    def __init__(
        self, drive: drive, 
        reduce_cand: bool=True, reduce_work: bool=False,
        read_traj=True, traj_period: int=1,
        include_first=True, include_last=True,
        directory="./"
    ) -> NoReturn:
        """"""
        super().__init__(input_nodes=[drive], directory=directory)

        self.reduce_cand = reduce_cand
        self.reduce_work = reduce_work

        self.read_traj = read_traj
        self.traj_period = traj_period

        self.include_first = include_first
        self.include_last = include_last

        return
    
    def forward(self, workers: List[DriverBasedWorker]):
        """
        Args:
            workers: ...
        
        Returns:
            reduce_cand is false and reduce_work is false -> List[List[List[Atoms]]]
            reduce_cand is true  and reduce_work is false -> List[List[Atoms]]
            reduce_cand is false and reduce_work is true  -> List[List[Atoms]]
            reduce_cand is true  and reduce_work is true  -> List[Atoms]
            
        """
        super().forward()

        self.pfunc(f"reduce_cand {self.reduce_cand} reduce_work {self.reduce_work}")
        
        # TODO: reconstruct trajs to List[List[Atoms]]
        self.workers = workers # for operations to access
        nworkers = len(workers)
        self.pfunc(f"nworkers: {nworkers}")
        #print(self.workers)
        worker_status = [False]*nworkers

        trajectories = [] # List[List[List[Atoms]]], worker->candidate->trajectory
        for i, worker in enumerate(workers):
            # TODO: How to save trajectories into one file?
            #       probably use override function for read/write
            #       i - worker, j - cand
            print("worker: ", worker.directory)
            cached_trajs_dpath = self.directory/f"{worker.directory.parent.name}-w{i}"
            if not cached_trajs_dpath.exists():
                if not (worker.get_number_of_running_jobs() == 0):
                    self.pfunc(f"{worker.directory.name} is not finished.")
                    break
                cached_trajs_dpath.mkdir(parents=True, exist_ok=True)
                curr_trajectories_ = worker.retrieve(
                    read_traj = self.read_traj, traj_period = self.traj_period,
                    include_first = self.include_first, include_last = self.include_last,
                    ignore_retrieved=False, # TODO: ignore misleads...
                    separate_candidates=True
                ) # List[List[Atoms]] or List[Atoms] depends on read_traj
                if self.reduce_cand:
                    curr_trajectories = list(itertools.chain(*curr_trajectories_))
                    write(cached_trajs_dpath/"reduced_candidates.xyz", curr_trajectories)
                else:
                    curr_trajectories = curr_trajectories_
                    for j, traj in enumerate(curr_trajectories_):
                        write(cached_trajs_dpath/f"cand{j}.xyz", traj)
            else:
                if self.reduce_cand:
                    curr_trajectories = read(cached_trajs_dpath/"reduced_candidates.xyz", ":")
                else:
                    cached_fnames = list(cached_trajs_dpath.glob("cand*"))
                    cached_fnames.sort()

                    curr_trajectories = []
                    for fpath in cached_fnames:
                        traj = read(fpath, ":")
                        curr_trajectories.append(traj)

            ntrajs = len(curr_trajectories)
            self.pfunc(f"worker_{i} ntrajectories {ntrajs}")
            trajectories.append(curr_trajectories)

            worker_status[i] = True

        structures = []
        if all(worker_status):
            if self.reduce_work:
                structures = list(itertools.chain(*trajectories))
            else:
                structures = trajectories
            nstructures = len(structures)
            self.pfunc(f"nstructures {nstructures}")
            self.status = "finished"
        else:
            ...

        return structures

@registers.operation.register
class separate(Operation):

    def __init__(self, extract, return_end: bool=False, traj_period: int=1) -> NoReturn:
        """"""
        super().__init__([extract])

        self.return_end = return_end
        self.traj_period = traj_period

        return
    
    def forward(self, structures):
        """"""
        super().forward()
        # - check dimensions of input structures
        d = 0
        curr_data_ = structures
        while True:
            if isinstance(curr_data_, Atoms):
                break
            else: # List
                curr_data_ = curr_data_[0]
                d += 1
        print("dimension: ", d)

        # - read full trajs
        if d == 3: # worker - cand - traj
            trajectories = list(itertools.chain(*structures))
            print("ntrajs: ", len(trajectories))
            end_frames, trj_frames = [], []
            for traj in trajectories:
                end_frames.append(traj[-1])
                trj_frames.extend(traj[1:-1:self.traj_period])
            write(self.directory/"end_frames.xyz", end_frames)
            write(self.directory/"trj_frames.xyz", trj_frames)
            print("end nframes: ", len(end_frames))
            print("trj nframes: ", len(trj_frames))
        else:
            ...
        
        self.status = "finished"

        if self.return_end:
            return end_frames
        else:
            return trj_frames


if __name__ == "__main__":
    ...
