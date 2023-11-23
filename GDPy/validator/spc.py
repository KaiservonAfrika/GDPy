#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import itertools
import warnings
import pathlib
from typing import List, Union

import numpy as np
import numpy.ma as ma

from ase import Atoms
from ase.io import read, write

import matplotlib as mpl
mpl.use("Agg") #silent mode
from matplotlib import pyplot as plt
try:
    plt.style.use("presentation")
except Exception as e:
    #print("Used default matplotlib style.")
    ...

from GDPy.validator.validator import AbstractValidator
from GDPy.worker.drive import DriverBasedWorker

from ..utils.comparision import get_properties, plot_parity, plot_distribution

from GDPy.utils.command import convert_indices


class SinglepointValidator(AbstractValidator):

    """Calculate energies on each structures and save them to file.
    """

    def __init__(self, groups: dict=None, *args, **kwargs):
        """Init a spc validator.

        Args:
            groups: Errors are estimated for given groups.

        """
        super().__init__(*args, **kwargs)
        self.groups = groups

        return

    def run(self, dataset, worker: DriverBasedWorker, *args, **kwargs):
        """"""
        super().run()

        data = []
        frame_pairs = []
        for prefix, frames in dataset["reference"]:
            pred_frames = self._irun(prefix, frames, None, worker)
            nframes, rmse_ret = self._plot_comparison(prefix, frames, pred_frames)
            frame_pairs.append([frames, pred_frames])
            data.append([prefix, nframes, rmse_ret])
        self.write_data(data)

        # - plot specific groups
        group_params = copy.deepcopy(self.groups)
        def run_selection():
            selected_prefixes, selected_groups = [], []
            for k, v in group_params.items():
                selected_prefixes.append(k)
                selected_groups.append(
                    convert_indices(v, index_convention="lmp")
                )
            self._debug(selected_groups)
            self._debug(selected_prefixes)

            for curr_prefix, curr_indices in zip(selected_prefixes,selected_groups):
                curr_ref = list(itertools.chain(*[frame_pairs[i][0] for i in curr_indices]))
                curr_pre = list(itertools.chain(*[frame_pairs[i][1] for i in curr_indices]))
                nframes, rmse_ret = self._plot_comparison(curr_prefix, curr_ref, curr_pre)
                self.write_data([[curr_prefix, nframes, rmse_ret]], f"{curr_prefix}-rmse.dat")
        
        if group_params is not None:
            run_selection()

        return

    def write_data(self, data, fname: str="rmse.dat"):
        """"""
        # - check data file
        keys = ["ene", "frc"]
        for rmse_ret in [x[2] for x in data]:
            for k in rmse_ret.keys():
                if k not in keys:
                    keys.append(k)
        content_fmt = "{:<24s}  {:>8d}  " + "{:>8.4f}  {:>8.4f}  "*len(keys) + "\n"

        header_fmt = "{:<24s}  {:>8s}  " + "{:>8s}  {:>8s}  "*len(keys) + "\n"
        header_data = ["#prefix", "nframes"]
        for k in keys:
            header_data.extend([f"{k}_rmse", f"{k}_std"])
        header = header_fmt.format(*header_data)
        
        content = header
        for prefix, nframes, rmse_ret in data:
            cur_data = [prefix, nframes]
            for k in keys:
                v = rmse_ret.get(k, None)
                if v is None:
                    cur_data.extend([np.nan, np.nan])
                else:
                    cur_data.extend([v["rmse"], v["std"]])
            content += content_fmt.format(*cur_data)
        
        with open(self.directory/fname, "w") as fopen:
            fopen.write(content)
        self._print("\n"+content)

        return

    def _irun(self, prefix: str, ref_frames: List[Atoms], pred_frames: List[Atoms], worker):
        """"""
        # - read structures
        nframes = len(ref_frames)
        if pred_frames is None:
            # NOTE: use worker to calculate
            # TODO: use cached data?
            self._print(f"Calculate reference frames {prefix} with potential...")
            cached_pred_fpath = self.directory / prefix / "pred.xyz"
            if not cached_pred_fpath.exists():
                worker.directory = self.directory / prefix
                worker.batchsize = nframes

                worker._share_wdir = True

                worker.run(ref_frames)
                worker.inspect(resubmit=True)
                if worker.get_number_of_running_jobs() == 0:
                    ret = worker.retrieve(
                        include_retrieved=True,
                    )
                    pred_frames = list(itertools.chain(*ret))
                else:
                    # TODO: ...
                    ...
                write(cached_pred_fpath, pred_frames)
            else:
                pred_frames = read(cached_pred_fpath, ":")
        else:
            ...
        
        return pred_frames
    
    def _plot_comparison(self, prefix, ref_frames: List[Atoms], pred_frames: List[Atoms]):
        """"""
        if not (self.directory/prefix).exists():
            (self.directory/prefix).mkdir(parents=True)

        nframes = len(ref_frames)
        ref_symbols, ref_energies, ref_forces = get_properties(ref_frames)
        ref_natoms = [len(a) for a in ref_frames]
        pred_symbols, pred_energies, pred_forces = get_properties(pred_frames)
        
        # - figure
        fig, axarr = plt.subplots(
            nrows=1, ncols=2,
            gridspec_kw={"hspace": 0.3}, figsize=(16, 9)
        )
        axarr = axarr.flatten()
        plt.suptitle(f"{prefix} with nframes {nframes}")

        # -- energies
        ene_rmse = plot_parity(
            axarr[0], ref_energies, pred_energies, x_name="ene", weights=ref_natoms
        )

        # -- forces
        frc_rmse = plot_parity(
            axarr[1], ref_forces, pred_forces, x_name="frc", x_types=ref_symbols
        )

        #if (self.directory/f"{prefix}.png").exists():
        #    warnings.warn(f"Figure file {prefix} exists.", UserWarning)
        plt.savefig(self.directory/prefix/"rmse.png")
        plt.close()

        # plot distributions
        fig, axarr = plt.subplots(
            nrows=1, ncols=2,
            gridspec_kw={"hspace": 0.3}, figsize=(16, 9)
        )
        axarr = axarr.flatten()
        plt.suptitle(f"{prefix} with nframes {nframes}")

        plot_distribution(
            axarr[0], ref_energies, pred_energies, x_name="ene", weights=ref_natoms
        )
        plot_distribution(
            axarr[1], ref_forces, pred_forces, x_name="frc", x_types=ref_symbols
        )

        plt.savefig(self.directory/prefix/"dist.png")
        plt.close()

        # - save results to data file
        rmse_ret = {}
        x_rmse, x_rmse_names = ene_rmse
        for _rms, rms_name in zip(x_rmse, x_rmse_names):
            rmse_ret[rms_name] = _rms
        x_rmse, x_rmse_names = frc_rmse
        for _rms, rms_name in zip(x_rmse, x_rmse_names):
            rmse_ret[rms_name] = _rms

        return nframes, rmse_ret


if __name__ == "__main__":
    ...