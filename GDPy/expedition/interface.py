#!/usr/bin/env python3
# -*- coding: utf-8 -*

import pathlib
import time

from ..utils.command import parse_input_file
from ..core.operation import Operation
from ..core.register import registers
from ..worker.explore import ExpeditionBasedWorker
from ..scheduler.interface import SchedulerVariable


"""
"""

class explore(Operation):

    def __init__(self, expedition, worker, scheduler=None, wait_time=60, directory="./", *args, **kwargs) -> None:
        """"""
        if scheduler is None:
            scheduler = SchedulerVariable()
        input_nodes = [expedition, worker, scheduler]
        super().__init__(input_nodes, directory)

        self.wait_time = wait_time

        return

    def forward(self, expedition, dyn_worker, scheduler):
        """Explore an expedition and forward results for further analysis.

        Returns:
            Workers that store structures.
        
        """
        super().forward()

        # -
        if hasattr(expedition, "register_worker"):
            expedition.register_worker(dyn_worker)
        
        # - run expedition with a worker
        worker = ExpeditionBasedWorker(expedition, scheduler)
        worker.directory = self.directory
        worker.wait_time = self.wait_time

        worker.run()
        worker.inspect(resubmit=True)

        basic_workers = []
        if worker.get_number_of_running_jobs() == 0:
            basic_workers = worker.retrieve(include_retrieved=True)
            self._debug(f"basic_workers: {basic_workers}")
            # for w in basic_workers:
            #     print(w.directory)
            self.status = "finished"
        else:
            ...

        return basic_workers


def run_expedition(config_params: dict, wait: float=None, directory="./", potter=None):
    """"""
    directory = pathlib.Path(directory)

    method = config_params.pop("method")
    if potter is not None:
        config_params["worker"] = potter

    expedition = registers.create("variable", method, convert_name=True, **config_params).value
    expedition.directory = directory
    if hasattr(expedition, "register_worker"):
        expedition.register_worker(config_params["worker"])

    if wait is not None:
        for i in range(1000):
            expedition.run()
            if expedition.read_convergence():
                break
            time.sleep(wait)
            print(f"wait {wait} seconds...")
        else:
            ...
    else:
        expedition.run()
        ...

    return


if __name__ == "__main__":
    ...