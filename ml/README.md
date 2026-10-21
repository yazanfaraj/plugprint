# ml/ — the AI part of plugprint

Notebooks that teach a model to recognise appliances from the power signal (NILM).

| Notebook | What it does |
|---|---|
| `01_explore_ukdale.ipynb` | Load one UK-DALE house, plot a day, see what appliance on/off "jumps" look like |

## Data (not stored in this repo)

The data is far too big for GitHub, so download it yourself:

- **UK-DALE (2017 release), disaggregated 6-second data:** `ukdale.zip` (3.3 GB) from the UKERC Energy Data Centre:
  https://data.ceda.ac.uk/edc/d1/7d78f943-f9fe-413b-af52-1816f9d968b0 → `data/version_0/ukdale.zip`
- Unzip it anywhere outside the repo (e.g. `C:\Users\<you>\datasets\ukdale\`) and set `DATA_DIR` at the top of the notebook.

Citation: J. Kelly and W. Knottenbelt, "The UK-DALE dataset, domestic appliance-level electricity demand and whole-house demand from five UK homes", *Scientific Data* 2, 150007 (2015). Dataset DOI: 10.5286/UKERC.EDC.000004. Licence: CC-BY 4.0.

## Running

```
py -m pip install numpy pandas matplotlib scikit-learn notebook
cd path\to\plugprint\ml
py -m notebook
```
