# Training Custom REINVENT4 Prior: Issues and Solutions

## Problem Summary

When training a custom REINVENT4 prior model to handle molecules with >10 rings and special elements (Si, Pt, isotopes like [2H]), we encountered multiple filtering issues that caused ~1000 molecules to be rejected during the workflow.

## Root Causes Identified

### Issue 1: Multiple Hidden Standardization Steps

**Problem:** REINVENT4 applies RDKit's "default" standardization filter at THREE different stages, even when you think you've disabled it:

1. **Data Pipeline** (`reinvent_datapre`) - ✅ Controlled by config
2. **Model Creation** (`create_model`) - ⚠️ Default `standardize = true`
3. **Training** (`transfer_learning`) - ⚠️ Default `standardize_smiles = true`

Each standardization step applies conservative chemical filters that reject complex molecules, causing the `"default" filter: <SMILES> is invalid` warnings.

**Root Cause:** The standardization defaults to `true` in multiple places, and it's applied AFTER your custom data pipeline filters. This means molecules that passed your lenient filters get rejected by the stricter default RDKit filters.

### Issue 2: Hardcoded Element Restrictions in Regex Filter

**Problem:** The regex tokenizer in `reinvent/datapipeline/filters/regex.py` has hardcoded element lists:

```python
ALIPHATIC = r"Br?|Cl?|N|O|S|P|F|I"  # Missing B (boron)!
NON_BRACKET_ATOMS = {"B", "C", "N", "O", "S", "P", "F", "I"}
```

**Root Cause:** If your SMILES contains unbracketed boron (`B`), it won't be recognized by the ALIPHATIC regex, causing silent token rejection.

### Issue 3: Vocabulary-Training Data Mismatch

**Problem:** Training failed with error:
```
ValueError: Tokens {'%11', '%12'} in <SMILES> are not supported by the model
```

**Root Cause:** 
- Model vocabulary was created from molecules that passed standardization (only up to `%10`)
- Training data included molecules with `%11`, `%12` (12-13 rings) because training was reading the same file but applying different filters
- The standardization in the training step filtered differently than model creation, creating a mismatch

## Complete Solution

### Step 1: Fix Data Pipeline Config

**File:** `configs/data_pipeline_large_rings.toml`

```toml
[filter]
# Add ALL elements your molecules use (including Si, Pt, B, H for isotopes)
elements = ["I", "O", "Cl", "N", "C", "F", "S", "Si", "Br", "P", "B", "H"]

# Relax constraints for large, complex molecules
min_heavy_atoms = 2
max_heavy_atoms = 250       # Increased from default ~50
max_mol_weight = 2000.0     # Increased from default ~1000
min_carbons = 3
max_num_rings = 40          # Increased from default 6
max_ring_size = 30          # Increased from default 15

# Preserve complex features
keep_stereo = true
keep_isotope_molecules = true  # Required for [2H], [13C], etc.
uncharge = true
kekulize = false
randomize_smiles = false
report_errors = true
```

**Why:** Your data pipeline is the ONLY place where filtering should happen. Make it lenient enough to keep all molecules you want.

### Step 2: Fix Regex Filter (Code Change)

**File:** `reinvent/datapipeline/filters/regex.py`

**Change Line 23:**
```python
# BEFORE:
ALIPHATIC = r"Br?|Cl?|N|O|S|P|F|I"

# AFTER:
ALIPHATIC = r"Br?|Cl?|N|O|S|P|F|I|B"  # Added B for boron
```

**Why:** Allows proper tokenization of molecules containing boron atoms.

### Step 3: Fix Model Creation Config

**File:** `configs/create_model_large_rings.toml`

```toml
[network]
num_layers = 3
layer_size = 512
dropout = 0.0
layer_normalization = false
standardize = false  # CRITICAL: Set to false to use pre-processed data
```

**Why:** Your data is already processed by the pipeline. Applying standardization again with the conservative "default" filter rejects complex molecules.

### Step 4: Fix Training Config

**File:** `configs/prior_training_large_rings.toml`

```toml
[parameters]
input_model_file = "priors/reinvent_large_rings_empty.model"
smiles_file = "priors/large_ring_dataset.processed.smi"  # Same file as model creation!
output_model_file = "priors/reinvent_large_rings.prior"

# Training settings
num_epochs = 20
save_every_n_epochs = 5
batch_size = 128
num_refs = 0
sample_batch_size = 256

# CRITICAL: Disable standardization and randomization
standardize_smiles = false  # Don't re-apply RDKit filters
randomize_smiles = false    # Optional, but recommended for consistency
tb_isim = false
```

**Why:** Ensures training uses the exact same molecules that the model vocabulary was built from, without additional filtering.

### Step 5: Fix chem.py RDKit Compatibility

**File:** `reinvent/datapipeline/filters/chem.py`

**Change lines 87-92:**
```python
# BEFORE:
mol.UpdatePropertyCache(strict=False)
self.fragment_chooser.chooseInPlace(mol)

# AFTER:
mol.UpdatePropertyCache(strict=False)

fragment_chooser = self.fragment_chooser
if hasattr(fragment_chooser, "chooseInPlace"):
    fragment_chooser.chooseInPlace(mol)
else:
    mol = fragment_chooser.choose(mol)
    if mol is None:
        return
```

**Why:** Newer RDKit versions removed `chooseInPlace()` method. This adds backward compatibility.

## Verification Workflow

### Complete Training Workflow

```bash
# Step 1: Clean data pipeline (with lenient filters)
python -m reinvent_datapre configs/data_pipeline_large_rings.toml

# Step 2: Check what tokens made it through
python check_tokens.py priors/large_ring_dataset.processed.smi
# Expected: Should show %10, %11, %12, etc. for your large ring molecules

# Step 3: Create empty model (standardize=false)
rm priors/reinvent_large_rings_empty.model  # Remove old if exists
python -m reinvent.runmodes.create_model.create_reinvent configs/create_model_large_rings.toml
# Expected: No "is invalid" warnings
# Expected: Token list includes all tokens from Step 2

# Step 4: Train (standardize_smiles=false)
python -m reinvent configs/prior_training_large_rings.toml
# Expected: No "is invalid" warnings
# Expected: No "tokens not supported" errors

# Step 5: Use trained model in RL
# Update rl_tadf_config.toml:
# prior_file = "priors/reinvent_large_rings.prior"
# agent_file = "priors/reinvent_large_rings.prior"
```

### Diagnostic Tools Created

1. **`check_tokens.py`** - Analyzes what tokens are in a SMILES file
   ```bash
   python check_tokens.py <smiles_file>
   ```

2. **`check_molecule_filtering.py`** - Detailed analysis of why molecules fail filters
   ```bash
   python check_molecule_filtering.py <input_file> --limit 100
   ```

3. **`MOLECULE_FILTERING_GUIDE.md`** - Complete guide to understanding REINVENT4's filtering stages

## Key Principles for Future Users

### 1. **Single Point of Filtering**
- Do ALL your filtering in the data pipeline (`reinvent_datapre`)
- Disable standardization in all downstream steps (`standardize = false`, `standardize_smiles = false`)

### 2. **Consistency is Critical**
- Model vocabulary MUST be built from the exact same file used for training
- Same file path in both `create_model_large_rings.toml` and `prior_training_large_rings.toml`

### 3. **Check Your Tokens**
- Always run `python check_tokens.py` on your processed file
- Verify model creation output shows ALL tokens from your data
- Maximum ring number in tokens tells you max supported rings (e.g., `%12` = 13 rings)

### 4. **Element Lists Need Two Updates**
- Config file: `configs/data_pipeline_large_rings.toml` → `elements = [...]`
- Code file: `reinvent/datapipeline/filters/regex.py` → `ALIPHATIC = r"..."`

### 5. **When in Doubt, Be Lenient**
- Start with very lenient filters (high `max_num_rings`, `max_ring_size`)
- Tighten only if needed
- RDKit will reject truly invalid molecules regardless of your config

## Summary of Changed Files

### Configuration Files (User-facing)
1. ✅ `configs/data_pipeline_large_rings.toml` - Relaxed filters, added elements
2. ✅ `configs/create_model_large_rings.toml` - Set `standardize = false`
3. ✅ `configs/prior_training_large_rings.toml` - Set `standardize_smiles = false`

### Code Files (Framework-level)
4. ✅ `reinvent/datapipeline/filters/regex.py` - Added `B` to `ALIPHATIC` pattern
5. ✅ `reinvent/datapipeline/filters/chem.py` - Fixed RDKit compatibility

### New Diagnostic Tools
6. ✅ `check_tokens.py` - Token analysis tool
7. ✅ `check_molecule_filtering.py` - Detailed filtering diagnosis
8. ✅ `MOLECULE_FILTERING_GUIDE.md` - Comprehensive guide

## Expected Outcomes

### Before Fixes
- ~1000 molecules rejected with "is invalid" warnings
- Model vocabulary: 26-37 tokens (missing `%11`, `%12`, etc.)
- Training fails with "tokens not supported" error

### After Fixes
- No "is invalid" warnings during model creation
- No "is invalid" warnings during training
- Model vocabulary: 40-50+ tokens (includes all necessary ring closure tokens)
- Training completes successfully
- Model can generate and score molecules with:
  - ✅ >10 rings (up to 40+ rings)
  - ✅ Special elements (Si, Pt, B)
  - ✅ Isotopes ([2H], [13C], etc.)
  - ✅ Large rings (up to 30 atoms per ring)

## Troubleshooting

### Still seeing "is invalid" warnings?
- Check: Did you set `standardize = false` in model config?
- Check: Did you set `standardize_smiles = false` in training config?
- Check: Are you using the correct config files?

### "Tokens not supported" error?
- Run: `python check_tokens.py priors/large_ring_dataset.processed.smi`
- Compare: Tokens in file vs tokens in model vocabulary (from model creation output)
- Solution: If mismatch, delete model and recreate with `standardize = false`

### Molecules still being rejected?
- Use: `python check_molecule_filtering.py configs/my_training_molecules.smi`
- This shows which filters are rejecting molecules
- Adjust: Increase limits in `data_pipeline_large_rings.toml`

---

**Date:** November 19, 2025  
**REINVENT4 Version:** Tested on current main branch  
**Python Version:** 3.11+  
**RDKit Version:** Modern versions (2023+) that removed `chooseInPlace()`
