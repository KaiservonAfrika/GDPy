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
from GDPy.worker.drive import (
    DriverBasedWorker, CommandDriverBasedWorker, QueueDriverBasedWorker
)
from GDPy.data.array import AtomsArray2D
from GDPy.data.trajectory import Trajectories


@registers.operation.register
class compute(Operation):

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

        if isinstance(frames, AtomsArray2D):
            frames = frames.get_marked_structures()

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
            self._print(f"run worker {i} for {nframes} nframes")
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
                self._print(content)
                worker_status.append(True)
        
        if all(worker_status):
            self.status = "finished"

        return workers


@registers.operation.register
class extract(Operation):

    """Extract dynamics trajectories from a drive-node's worker.
    """

    def __init__(self, drive, directory="./", *args, **kwargs) -> None:
        """"""
        super().__init__(input_nodes=[drive], directory=directory)

        return
    
    def forward(self, workers: List[DriverBasedWorker]) -> AtomsArray2D:
        """
        Args:
            workers: ...
        
        Returns:
            AtomsArray2D.
            
        """
        super().forward()

        # TODO: reconstruct trajs to List[List[Atoms]]
        self.workers = workers # for operations to access
        nworkers = len(workers)
        self._print(f"nworkers: {nworkers}")
        #print(self.workers)
        worker_status = [False]*nworkers

        trajectories = Trajectories()
        for i, worker in enumerate(workers):
            # TODO: How to save trajectories into one file?
            #       probably use override function for read/write
            #       i - worker, j - cand
            print("worker: ", worker.directory)
            cached_trajs_dpath = self.directory/f"{worker.directory.parent.name}-w{i}"
            if not cached_trajs_dpath.exists():
                # inspect again for using extract without drive
                worker.inspect(resubmit=False)
                if not (worker.get_number_of_running_jobs() == 0):
                    self._print(f"{worker.directory} is not finished.")
                    break
                cached_trajs_dpath.mkdir(parents=True, exist_ok=True)
                curr_trajectories = worker.retrieve(
                    include_retrieved=True, 
                )
                curr_trajectories.save_file(cached_trajs_dpath/"dataset.h5")
            else:
                #if self.reduce_cand:
                #    curr_trajectories = read(cached_trajs_dpath/"reduced_candidates.xyz", ":")
                #else:
                #    cached_fnames = list(cached_trajs_dpath.glob("cand*"))
                #    cached_fnames.sort()

                #    curr_trajectories = []
                #    for fpath in cached_fnames:
                #        traj = read(fpath, ":")
                #        curr_trajectories.append(traj)
                curr_trajectories = Trajectories.from_file(cached_trajs_dpath/"dataset.h5")

            self._print(f"worker_{i} {curr_trajectories}")
            trajectories.extend(curr_trajectories)

            worker_status[i] = True
        
        structures = []
        if all(worker_status):
            self._print(f"worker_: {trajectories}")
            self.status = "finished"
        else:
            ...

        return trajectories


if __name__ == "__main__":
    ...
