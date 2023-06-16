#!/usr/bin/env python3
# -*- coding: utf-8 -*

"""Some shared configuration parameters.
"""

from typing import Union, List

#: Number of parallel jobs for joblib.
NJOBS: int = 1

# - find default vasp settings
#gdpconfig = Path.home() / ".gdp"
#if gdpconfig.exists() and gdpconfig.is_dir():
#    # find vasp config
#    vasprc = gdpconfig / "vasprc.json"
#    with open(vasprc, "r") as fopen:
#        input_dict = json.load(fopen)
#else:
#    input_dict = {}

#: Model deviations by the committee model.
VALID_DEVI_FRAME_KEYS: List[str] = [
    "devi_te",
    "max_devi_v", "min_devi_v", "avg_devi_v",
    "max_devi_f", "min_devi_f", "avg_devi_f",
    "max_devi_ae", "min_devi_ae", "avg_devi_ae",
]

#: Model deviations by the committee model.
VALID_DEVI_ATOMIC_KEYS: List[str] = [
    "devi_f",
]

if __name__ == "__main__":
    ...