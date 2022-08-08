#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import abc
import copy
import pathlib

from typing import Optional
from collections.abc import Iterable

import numpy as np

from ase.io import read, write


class AbstractDynamics(abc.ABC):

    delete = []
    keyword: Optional[str] = None
    special_keywords = {}

    def __init__(self, calc, directory, *args, **kwargs):

        self.calc = calc
        self.calc.reset()

        self._directory_path = pathlib.Path(directory)

        return

    def set_output_path(self, directory):
        """"""
        # main dynamics dir
        self._directory_path = pathlib.Path(directory)
        # TODO: for repeat, r0, r1, r2
        #self.calc.directory = self._directory_path / self.calc.name
        self.calc.directory = self._directory_path

        # extra files
        #self._logfile_path = self._directory_path / self.logfile
        #self._trajfile_path = self._directory_path / self.trajfile

        return
    
    def reset(self):
        """ remove results stored in dynamics calculator
        """
        self.calc.reset()

        return

    def delete_keywords(self, kwargs):
        """removes list of keywords (delete) from kwargs"""
        for d in self.delete:
            kwargs.pop(d, None)

        return

    def set_keywords(self, kwargs):
        # TODO: rewrite this method
        args = kwargs.pop(self.keyword, [])
        if isinstance(args, str):
            args = [args]
        elif isinstance(args, Iterable):
            args = list(args)

        for key, template in self.special_keywords.items():
            if key in kwargs:
                val = kwargs.pop(key)
                args.append(template.format(val))

        kwargs[self.keyword] = args

        return

    @abc.abstractmethod
    def run(self, atoms, **kwargs):
        """"""


        return 


def read_trajectories(
    action, res_dpath, traj_period,
    traj_frames_name, traj_indices_name,
    opt_dname, opt_frames_name
):
    """ read trajectories from several directories
        each dir is named by candx
    """
    # - act, retrieve trajectory frames
    # TODO: more general interface not limited to dynamics
    traj_frames_path = res_dpath / traj_frames_name
    traj_indices_path = res_dpath / traj_indices_name
    if not traj_frames_path.exists():
        traj_indices = [] # use traj indices to mark selected traj frames
        all_traj_frames = []
        tmp_folder = res_dpath / opt_dname
        optimised_frames = read(res_dpath/opt_frames_name, ":")
        # TODO: change this to joblib
        for atoms in optimised_frames:
            # --- read confid and parse corresponding trajectory
            confid = atoms.info["confid"]
            action.set_output_path(tmp_folder/("cand"+str(confid)))
            traj_frames = action._read_trajectory(label_steps=True)
            # --- generate indices
            # NOTE: last one should be always included since it may be converged structure
            cur_nframes = len(all_traj_frames)
            cur_indices = list(range(0,len(traj_frames)-1,traj_period)) + [len(traj_frames)-1]
            cur_indices = [c+cur_nframes for c in cur_indices]
            # --- add frames
            traj_indices.extend(cur_indices)
            all_traj_frames.extend(traj_frames)
        np.save(traj_indices_path, traj_indices)
        write(traj_frames_path, all_traj_frames)
    else:
        all_traj_frames = read(traj_frames_path, ":")
    print("ntrajframes: ", len(all_traj_frames))
            
    if traj_indices_path.exists():
        traj_indices = np.load(traj_indices_path)
        all_traj_frames = [all_traj_frames[i] for i in traj_indices]
        #print(traj_indices)
    print("ntrajframes: ", len(all_traj_frames), f" by {traj_period} traj_period")

    return all_traj_frames


if __name__ == "__main__":
    pass