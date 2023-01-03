#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

import argparse
from pathlib import Path

import numpy as np

# global settings
from GDPy import config


def main():
    # arguments 
    parser = argparse.ArgumentParser(
        prog="gdp", 
        description="GDPy: Generating Deep Potential with Python"
    )

    parser.add_argument(
        "-d", "--directory", default=Path.cwd(),
        help="working directory"
    )
    
    # the workflow tracker
    parser.add_argument(
        "-p", "--potential", default=None,
        help = "target potential related configuration (json/yaml)"
    )

    parser.add_argument(
        "-r", "--reference", default=None,
        help = "reference potential related configuration (json/yaml)"
    )

    parser.add_argument(
        "-nj", "--n_jobs", default = 1, type=int,
        help = "number of processors"
    )
    
    # subcommands in the entire workflow 
    subparsers = parser.add_subparsers(
        title="available subcommands", 
        dest="subcommand", 
        help="sub-command help"
    )
    
    # - automatic training
    parser_train = subparsers.add_parser(
        "train", help="automatic training utilities"
    )

    # automatic training
    #parser_model = subparsers.add_parser(
    #    "model", help="model operations"
    #)
    #parser_model.add_argument(
    #    "INPUTS",
    #    help="a directory with input json files"
    #)
    #parser_model.add_argument(
    #    "-m", "--mode",
    #    help="[create/freeze] models"
    #)

    # explore
    parser_explore = subparsers.add_parser(
        "explore", help="exploration configuration file (json/yaml)"
    )
    parser_explore.add_argument(
        "EXPEDITION", 
        help="expedition configuration file (json/yaml)"
    )
    parser_explore.add_argument(
        "--run", default=None,
        help="running option"
    )

    # ----- data analysis -----
    parser_data = subparsers.add_parser(
        "data", help="data analysis"
    )
    parser_data.add_argument(
        "DATA", help = "data configuration file (json/yaml)"
    )
    parser_data.add_argument(
        "-r", "--run", default=None,
        help = "configuration for specific operation (json/yaml)"
    )
    parser_data.add_argument(
        "-c", "--choice", default="dryrun",
        choices = ["dryrun", "stat", "calc", "compress"],
        help = "choose data analysis mode"
    )
    parser_data.add_argument(
        "-n", "--name", default = "ALL",
        help = "system name"
    )
    parser_data.add_argument(
        "-p", "--pattern", default = "*.xyz",
        help = "xyz search pattern"
    )
    parser_data.add_argument(
        "-m", "--mode", default=None,
        help = "data analysis mode"
    )
    parser_data.add_argument(
        "-num", "--number", 
        default = -1, type=int,
        help = "number of selection"
    )
    parser_data.add_argument(
        "-etol", "--energy_tolerance", 
        default = 0.020, type = float,
        help = "energy tolerance per atom"
    )
    parser_data.add_argument(
        "-es", "--energy_shift", 
        default = 0.0, type = float,
        help = "add energy correction for each structure"
    )

    # --- worker interface
    parser_driver = subparsers.add_parser(
        "driver", help="run a driver (local worker)"
    )
    parser_driver.add_argument(
        "STRUCTURE",
        help="a structure file that stores one or more structures"
    )
    parser_driver.add_argument(
        "-o", "--output", default=None,
        help="output filename of all calculated structures"
    )

    parser_worker = subparsers.add_parser(
        "worker", help="run a worker"
    )
    parser_worker.add_argument(
        "STRUCTURE",
        help="a structure file that stores one or more structures"
    )
    parser_worker.add_argument(
        "-o", "--output", default=None,
        help="output filename of all calculated structures"
    )
    parser_worker.add_argument(
        "--local", action="store_false", 
        help="whether to perform local execution"
    )

    # --- task interface
    parser_task = subparsers.add_parser(
        "task", help="run a task (e.g. GA and MC)"
    )
    parser_task.add_argument(
        "params",
        help="json/yaml file that stores parameters for a task"
    )
    parser_task.add_argument(
        "--run", default=1, type=int,
        help="running options"
    )

    # selection
    parser_select = subparsers.add_parser(
        "select",
        help="apply various selection operations"
    )
    parser_select.add_argument(
        "CONFIG", help="selection configuration file"
    )
    parser_select.add_argument(
        "-s", "--structure", required=True, 
        help="structure generator"
    )

    # graph utils
    parser_graph = subparsers.add_parser(
        "graph",
        help="graph utils"
    )
    parser_graph.add_argument(
        "CONFIG", help="graph configuration file"
    )
    parser_graph.add_argument(
        "-f", "--structure_file", required=True,
        help="structure filepath (in xyz format)"
    )
    parser_graph.add_argument(
        "-i", "--indices", default=":",
        help="structure indices"
    )
    parser_graph.add_argument(
        "-m", "--mode", required=True,
        choices = ["diff", "add"],
        help="structure filepath (in xyz format)"
    )

    # --- validation
    parser_validation = subparsers.add_parser(
        "valid", help="validate properties with trained models"
    )
    parser_validation.add_argument(
        "INPUTS",
        help="input json/yaml file with calculation parameters"
    )
    
    # === execute 
    args = parser.parse_args()
    
    # update njobs
    config.NJOBS = args.n_jobs
    if config.NJOBS != 1:
        print(f"Run parallel jobs {config.NJOBS}")

    # always check the current workflow before continuing to subcommands 
    # also, the global logger will be initialised 
    # TODO: track the workflow 
    # tracker = track_workflow(args.status)

    # - potential
    from GDPy.potential.register import create_potter
    potter = None
    if args.potential:
        pot_config = args.potential # configuration file of potential
        potter = create_potter(pot_config) # register calculator, and scheduler if exists
    
    referee = None
    if args.reference:
        ref_config = args.reference # configuration file of potential
        referee = create_potter(ref_config) # register calculator, and scheduler if exists

    # - use subcommands
    if args.subcommand == "train":
        from GDPy.trainer import run_trainer
        run_trainer(potter, args.directory)
    elif args.subcommand == "select":
        from GDPy.selector import run_selection
        run_selection(args.CONFIG, args.structure, args.directory, potter)
    elif args.subcommand == "explore":
        from GDPy.expedition import run_expedition
        run_expedition(potter, referee, args.EXPEDITION)
    elif args.subcommand == "data":
        from GDPy.data import data_main
        data_main(
            args.DATA,
            potter, referee,
            args.run,
            #
            args.choice, args.mode,
            args.name, args.pattern,
            args.number, args.energy_tolerance, args.energy_shift
        )
    elif args.subcommand == "driver":
        from GDPy.computation.worker import run_driver
        run_driver(args.STRUCTURE, args.directory, potter, args.output)
    elif args.subcommand == "worker":
        from GDPy.computation.worker import run_worker
        run_worker(args.STRUCTURE, args.directory, args.local, potter, args.output)
    elif args.subcommand == "task":
        from GDPy.task.task import run_task
        run_task(args.params, potter, referee, args.run)
    elif args.subcommand == "valid":
        from GDPy.validator import run_validation
        run_validation(args.directory, args.INPUTS, potter)
    elif args.subcommand == "graph":
        from GDPy.graph.graph_main import graph_main
        graph_main(args.n_jobs, args.CONFIG, args.structure_file, args.indices, args.mode)
    else:
        pass


if __name__ == "__main__":
    main()
