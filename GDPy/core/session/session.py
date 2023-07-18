#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import abc
import copy
import json
from typing import NoReturn, Union, List, Callable
import pathlib
import yaml

import numpy as np

from ase import Atoms
from ase.io import read, write

from GDPy import config
from GDPy.core.placeholder import Placeholder
from GDPy.core.variable import Variable
from .utils import traverse_postorder


class Session:

    #: Standard print function.
    _print: Callable = config._print

    #: Standard debug function.
    _debug: Callable = config._debug


    def __init__(self, directory="./") -> None:
        """"""
        self.directory = pathlib.Path(directory)

        return

    def run(self, operation, feed_dict: dict={}) -> None:
        """"""
        # - find forward order
        nodes_postorder = traverse_postorder(operation)
        #print(f"number_of_nodes: {len(nodes_postorder)}")
        #for n in nodes_postorder:
        #    print(n)
        #exit()
        self._print(
            "[{:^24s}] NUM_NODES: {} AT MAIN: {}".format(
                "START", len(nodes_postorder), str(self.directory)
            )
        )

        # - run nodes
        for i, node in enumerate(nodes_postorder):
            # NOTE: reset directory since it maybe changed
            prev_name = node.directory.name
            if not prev_name:
                prev_name = node.__class__.__name__
            node.directory = self.directory/f"{str(i).zfill(4)}.{prev_name}"
            if node.__class__.__name__.endswith("Variable"):
                node_type = "VX"
            else:
                node_type = "OP"
            self._print(
                "[{:^24s}] NAME: {} AT {}".format(
                    node_type, node.__class__.__name__.upper(), node.directory.name
                )
            )

            if isinstance(node, Placeholder):
                node.output = feed_dict[node]
            elif isinstance(node, Variable):
                node.output = node.value
            else: # Operation
                self._debug(f"node: {node}")
                if node.preward():
                    node.inputs = [input_node.output for input_node in node.input_nodes]
                    node.output = node.forward(*node.inputs)
                else:
                    self._print("wait previous nodes to finish...")
                    continue

        return


if __name__ == "__main__":
    ...
