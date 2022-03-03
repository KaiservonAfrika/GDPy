#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from ast import parse
from pathlib import Path
import subprocess

from typing import Union

import json
import yaml

def run_command(directory, command, comment="", timeout=None):
    proc = subprocess.Popen(
        command, shell=True, cwd=directory, 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding = "utf-8"
    )
    if timeout is None:
        errorcode = proc.wait()
    else:
        errorcode = proc.wait(timeout=timeout)

    msg = "Message: " + "".join(proc.stdout.readlines())
    print(msg)
    if errorcode:
        raise ValueError("Error in %s at %s." %(comment, directory))
    
    return msg

def parse_indices(indices=None):
    """ parse indices for reading xyz by ase, get start for counting
        constrained indices followed by lammps convention
        "2:4 3:8"
        convert [1,2,3,6,7,8] to "1:3 6:8"
    """
    if indices is not None:
        start, end = indices.split(':')
    else:
        start = 0
        end = ''

    return (start,end)


def parse_input_file(
    input_fpath: Union[str, Path],
    write_json: bool = False # write readin dict to check if alright
):
    """"""
    input_dict = None
    
    if isinstance(input_fpath, str):
        input_file = Path(input_fpath)
    else:
        return None

    if input_file.suffix == ".json":
        with open(input_file, "r") as fopen:
            input_dict = json.load(fopen)
    elif input_file.suffix == ".yaml":
        with open(input_file, "r") as fopen:
            input_dict = yaml.safe_load(fopen)
    else:
        pass
        # raise ValueError("input file format should be json or yaml...")
    
    # TODO: recursive read internal json or yaml files
    if input_dict is not None:
        for key, value in input_dict.items():
            key_dict = parse_input_file(value, write_json=False)
            if key_dict is not None:
                input_dict[key] = key_dict

    if input_dict and write_json:
        with open(input_file.parent/"params.json", "w") as fopen:
            json.dump(input_dict, fopen, indent=4)
        print("See params.json for values of all parameters...")
    

    return input_dict

if __name__ == "__main__":
    # test input reader
    input_dict = parse_input_file("/mnt/scratch2/users/40247882/PtOx-dataset/systems.yaml")
    print(input_dict)
    pass