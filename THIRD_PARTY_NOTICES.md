# Third-party notices

BuildMolecule bundles or depends on the following third-party components.
Their licenses apply to those components; the MIT license in `LICENSE` covers
this project's own source code.

| Component | Use | License / upstream |
| --- | --- | --- |
| [Ketcher](https://github.com/epam/ketcher) 3.4.0 | Structure editor (`mk_mole/assets/ketcher`) | Apache-2.0 |
| [3Dmol.js](https://github.com/3dmol/3Dmol.js) | 3D molecular viewer (`mk_mole/assets/3Dmol-min.js`) | BSD-3-Clause |
| [CHGNet](https://github.com/CederGroupHub/chgnet) | Optional structure relaxation engine | MIT (see upstream) |
| [PyTorch](https://pytorch.org/) | CHGNet runtime (installed separately in `chgnet_env`) | BSD-style |
| [ASE](https://wiki.fysik.dtu.dk/ase/) / [pymatgen](https://pymatgen.org/) | Structure I/O and CHGNet dependencies | LGPL-2.1+ / MIT |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) | Desktop UI | LGPLv3 / commercial |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) | CAS/compound lookup | NCBI usage policy |
| [DeepSeek API](https://platform.deepseek.com/) | LLM structure generation | DeepSeek terms of service |

The Ketcher/3Dmol assets are unmodified upstream build artifacts. The CHGNet
environment is not bundled in this repository; `install_chgnet.bat` installs it
locally from PyPI and the PyTorch package index.
