#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import argparse
import pathlib

import numpy as np

# global settings
from GDPy import config
from GDPy.core.register import registers, import_all_modules_for_register


def main():
    # - register
    import_all_modules_for_register()

    description = "GDPy: Generating Deep Potential with Python\n"

    # - arguments 
    parser = argparse.ArgumentParser(
        prog="gdp", 
        description=description
    )

    parser.add_argument(
        "-d", "--directory", default=pathlib.Path.cwd(),
        help="working directory"
    )
    
    # the workflow tracker
    parser.add_argument(
        "-p", "--potential", default=None,
        help = "target potential related configuration (json/yaml)"
    )

    parser.add_argument(
        "-nj", "--n_jobs", default = 1, type=int,
        help = "number of processors"
    )

    parser.add_argument(
        "--debug", action="store_true",
        help = "debug mode that gives more information"
    )
    
    parser.add_argument(
        "--log", default="gdp.out",
        help = "logging output file"
    )
    
    # subcommands in the entire workflow 
    subparsers = parser.add_subparsers(
        title="available subcommands", 
        dest="subcommand", 
        help="sub-command help"
    )

    # - run session
    parser_session = subparsers.add_parser(
        "session", help="run gdpy session", 
        description=str(registers.variable)+"\n"+str(registers.operation), 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_session.add_argument(
        "SESSION", help="session configuration file (json/yaml)"
    )
    parser_session.add_argument(
        "-f", "--feed", default=None, nargs="+", 
        help="session placeholders"
    )
    
    # - build structures
    parser_build = subparsers.add_parser(
        "build", help="build structures",
        description=str(registers.builder), 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_build.add_argument(
        "CONFIG", help="builder configuration file (json/yaml)"
    )
    parser_build.add_argument(
        "-s", "--substrates", default=None,
        help="file that stores substrates (e.g. *.xyz)"
    )
    parser_build.add_argument(
        "-n", "--number", default=1, type=int,
        help="number of structures to build"
    )
    
    # - automatic training
    parser_train = subparsers.add_parser(
        "train", help="automatic training utilities",
        description=str(registers.trainer), 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_train.add_argument(
        "CONFIG", help="training configuration file (json/yaml)"
    )

    # --- compute interface
    parser_compute = subparsers.add_parser(
        "compute", help="compute structures with basic methods (MD, MIN, and ...)"
    )
    parser_compute.add_argument(
        "STRUCTURE",
        help="a structure file that stores one or more structures"
    )
    parser_compute.add_argument(
        "-b", "--batch", default=None, type=int,
        help="run selected batch number (useful when queue run)"
    )
    parser_compute.add_argument(
        "-o", "--output", default="last", choices=["last","traj"],
        help="retrieve last frame or entire trajectory"
    )

    # --- expedition interface
    parser_explore = subparsers.add_parser(
        "explore", help="explore structures with advanced methods (GA, MC, and ...)",
        description=str(registers.expedition),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_explore.add_argument(
        "CONFIG",
        help="json/yaml file that stores parameters for a task"
    )
    parser_explore.add_argument(
        "--wait", default=None, type=float,
        help="wait time after each run"
    )

    # selection
    parser_select = subparsers.add_parser(
        "select",
        help="apply various selection operations",
        description=str(registers.selector), 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_select.add_argument(
        "CONFIG", help="selection configuration file"
    )
    parser_select.add_argument(
        "-s", "--structure", required=True, 
        help="structure generator"
    )

    # --- validation
    parser_validation = subparsers.add_parser(
        "valid", help="validate properties with trained models",
        description=str(registers.validator), 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser_validation.add_argument(
        "CONFIG", help="validation configuration file"
    )
    
    # === execute 
    args = parser.parse_args()
    
    # - update global configuration
    if args.debug:
        config.logger.setLevel(logging.DEBUG)

    curr_wdir = pathlib.Path(args.directory)
    if not curr_wdir.exists():
        curr_wdir.mkdir(parents=True)

    if args.log:
        logfpath = curr_wdir/args.log
        if logfpath.exists():
            fh = logging.FileHandler(logfpath, mode="a")
        else:
            fh = logging.FileHandler(logfpath, mode="w")
        fh.setFormatter(config.formatter)
        config.logger.addHandler(fh)
    
    # -- set LOGO
    for line in config.LOGO_LINES:
        config._print(line)

    # -- set njobs
    config.NJOBS = args.n_jobs
    if config.NJOBS != 1:
        config._print(f"Use {config.NJOBS} processors.")

    # - potential
    from GDPy.utils.command import parse_input_file
    from GDPy.worker.interface import ComputerVariable
    potter = None
    if args.potential:
        params = parse_input_file(input_fpath=args.potential)
        potter = ComputerVariable(
            params["potential"], params.get("driver", {}), params.get("scheduler", {}),
            batchsize=params.get("batchsize", 1), use_single=params.get("use_single", False), 
        ).value[0]

    # - use subcommands
    if args.subcommand == "session":
        from GDPy.core.session import run_session
        run_session(args.SESSION, args.feed, args.directory)
    elif args.subcommand == "train":
        from GDPy.trainer import run_newtrainer
        run_newtrainer(args.CONFIG, args.directory)
    elif args.subcommand == "build":
        build_config = parse_input_file(args.CONFIG)
        from .builder.interface import build_structures
        build_structures(build_config, args.substrates, args.number, args.directory)
    elif args.subcommand == "select":
        from GDPy.selector.interface import run_selection
        run_selection(args.CONFIG, args.structure, args.directory, potter)
    elif args.subcommand == "compute":
        from GDPy.worker.interface import run_worker
        run_worker(args.STRUCTURE, args.directory, potter, args.output, args.batch)
    elif args.subcommand == "explore":
        from .expedition.interface import run_expedition
        params = parse_input_file(args.CONFIG)
        run_expedition(params, args.wait, args.directory, potter)
    elif args.subcommand == "valid":
        from GDPy.validator import run_validation
        params = parse_input_file(args.CONFIG)
        run_validation(params, args.directory, potter)
    else:
        ...


if __name__ == "__main__":
    main()
