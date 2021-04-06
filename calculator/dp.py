"""An ASE calculator interface.

Example:
```python
from ase import Atoms
from deepmd.calculator import DP

water = Atoms('H2O',
              positions=[(0.7601, 1.9270, 1),
                         (1.9575, 1, 1),
                         (1., 1., 1.)],
              cell=[100, 100, 100],
              calculator=DP(model="frozen_model.pb"))
print(water.get_potential_energy())
print(water.get_forces())
```

Optimization is also available:
```python
from ase.optimize import BFGS
dyn = BFGS(water)
dyn.run(fmax=1e-6)
print(water.get_positions())
```
"""

import numpy as np

from ase.calculators.calculator import (
    Calculator, all_changes, PropertyNotImplementedError
)
import deepmd.DeepPot as DeepPot


class DP(Calculator):
    name = "DP"
    implemented_properties = ["energy", "forces", "virial", "stress"]

    def __init__(self, model, label="DP", type_dict=None, **kwargs):
        Calculator.__init__(self, label=label, **kwargs)
        if isinstance(model, str):
            model = [model] # compatiblity
        self.dp_models = [] 
        for m in model:
            self.dp_models.append(DeepPot(m))
        if type_dict:
            self.type_dict=type_dict
        else:
            self.type_dict = dict(zip(self.dp.get_type_map(), range(self.dp.get_ntypes())))
    
    def prepare_input(self, atoms=None):
        coord = atoms.get_positions().reshape([1, -1])
        if sum(atoms.get_pbc())>0:
           self.pbc = True
           cell = atoms.get_cell().reshape([1, -1])
        else:
           self.pbc = False
           cell = None
        symbols = atoms.get_chemical_symbols()
        atype = [self.type_dict[k] for k in symbols]

        self.dp_input = {'coords': coord, 'cells': cell, 'atom_types': atype}

        return 

    def icalculate(self, dp_model, properties=["energy", "forces", "virial"], system_changes=all_changes):
        """"""
        results = {}
        e, f, v = dp_model.eval(**self.dp_input)
        results['energy'] = e[0][0]
        results['forces'] = f[0]
        results['virial'] = v[0].reshape(3,3)

        # convert virial into stress for lattice relaxation
        if "stress" in properties:
            if self.pbc:
                # the usual convention (tensile stress is positive)
                # stress = -virial / volume
                stress = -0.5*(v[0].copy()+v[0].copy().T) / atoms.get_volume()
                # Voigt notation 
                results['stress'] = stress.flat[[0,4,8,5,2,1]] 
            else:
                raise PropertyNotImplementedError
        
        return results
    
    def calculate(self, atoms=None, properties=["energy", "forces", "virial"], system_changes=all_changes):
        """"""
        self.prepare_input(atoms)
        all_results = []
        for dp_model in self.dp_models:
            cur_results = self.icalculate(dp_model) # return current results
            all_results.append(cur_results)
        
        if len(self.dp_models) == 1:
            self.results = all_results[0]
        else:
            # average results
            results = {}
            energy_array = [r['energy'] for r in all_results]
            results['energy'] = np.mean(energy_array)
            forces_array = np.array([r['forces'] for r in all_results])
            results['forces'] = np.mean(forces_array, axis=0)
            if 'stress' in properties:
                if self.pbc:
                    stress_array = np.array([r['stress'] for r in all_results])
                    results['stress'] = np.mean(stress_array, axis=0)
                else:
                    raise PropertyNotImplementedError 
            # estimate standard variance
            results['energy_stdvar'] = np.sqrt(np.var(energy_array))
            results['forces_stdvar'] = np.sqrt(np.var(forces_array, axis=0))
            self.results = results

        return 