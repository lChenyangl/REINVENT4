#!/usr/bin/env python3
"""
Clean SMILES dataset by removing molecules with unsupported tokens.
This script filters out SMILES that contain tokens not supported by REINVENT models.
"""

import sys
from pathlib import Path
from rdkit import Chem
from rdkit.Chem import AllChem
import argparse

def get_allowed_tokens():
    """Get the allowed tokens from the error message"""
    return {
        'o', '$', '9', '[N-]', 'Cl', '[O-]', '5', '-', 's', '6', '=', '7', 'O', '4', 
        ')', 'c', '#', '[n+]', '[nH]', 'n', '%10', '1', 'N', '^', '[S+]', '8', 'F', 
        '[N+]', 'C', '(', '3', '2', 'Br', 'S'
    }

def tokenize_smiles(smiles):
    """Simple tokenizer to extract SMILES tokens"""
    tokens = set()
    i = 0
    while i < len(smiles):
        if smiles[i] == '[':
            # Handle bracketed atoms
            end = smiles.find(']', i) + 1
            tokens.add(smiles[i:end])
            i = end
        elif smiles[i] == '%':
            # Handle double-digit ring numbers
            if i + 2 < len(smiles) and smiles[i+1:i+3].isdigit():
                tokens.add(smiles[i:i+3])
                i += 3
            else:
                tokens.add(smiles[i])
                i += 1
        else:
            tokens.add(smiles[i])
            i += 1
    return tokens

def is_valid_smiles(smiles, allowed_tokens):
    """Check if SMILES contains only allowed tokens"""
    try:
        # First check with RDKit
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False, "Invalid RDKit molecule"
        
        # Canonicalize to standard form
        canonical_smiles = Chem.MolToSmiles(mol)
        
        # Check tokens
        smiles_tokens = tokenize_smiles(canonical_smiles)
        unsupported_tokens = smiles_tokens - allowed_tokens
        
        if unsupported_tokens:
            return False, f"Unsupported tokens: {unsupported_tokens}"
        
        return True, canonical_smiles
        
    except Exception as e:
        return False, f"Error: {str(e)}"

def clean_smiles_file(input_file, output_file, report_file=None):
    """Clean SMILES file and generate report"""
    allowed_tokens = get_allowed_tokens()
    
    valid_count = 0
    invalid_count = 0
    invalid_reasons = {}
    
    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line_num, line in enumerate(infile, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            # Handle both "SMILES" and "SMILES NAME" formats
            parts = line.split(None, 1)
            smiles = parts[0]
            name = parts[1] if len(parts) > 1 else f"mol_{line_num}"
            
            is_valid, result = is_valid_smiles(smiles, allowed_tokens)
            
            if is_valid:
                outfile.write(f"{result}\t{name}\n")
                valid_count += 1
            else:
                invalid_count += 1
                reason = result
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                
            if line_num % 1000 == 0:
                print(f"Processed {line_num} molecules...")
    
    # Generate report
    print(f"\n=== CLEANING REPORT ===")
    print(f"Total processed: {valid_count + invalid_count}")
    print(f"Valid molecules: {valid_count}")
    print(f"Invalid molecules: {invalid_count}")
    print(f"Success rate: {valid_count/(valid_count + invalid_count)*100:.1f}%")
    
    if invalid_reasons:
        print(f"\nInvalid molecule reasons:")
        for reason, count in sorted(invalid_reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"  {count:5d} - {reason}")
    
    # Write detailed report if requested
    if report_file:
        with open(report_file, 'w') as f:
            f.write("SMILES Cleaning Report\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Input file: {input_file}\n")
            f.write(f"Output file: {output_file}\n")
            f.write(f"Total processed: {valid_count + invalid_count}\n")
            f.write(f"Valid molecules: {valid_count}\n")
            f.write(f"Invalid molecules: {invalid_count}\n")
            f.write(f"Success rate: {valid_count/(valid_count + invalid_count)*100:.1f}%\n\n")
            
            if invalid_reasons:
                f.write("Invalid molecule breakdown:\n")
                for reason, count in sorted(invalid_reasons.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {count:5d} - {reason}\n")

def main():
    parser = argparse.ArgumentParser(description='Clean SMILES dataset for REINVENT')
    parser.add_argument('input_file', help='Input SMILES file')
    parser.add_argument('output_file', help='Output cleaned SMILES file')
    parser.add_argument('--report', help='Generate detailed report file')
    
    args = parser.parse_args()
    
    if not Path(args.input_file).exists():
        print(f"Error: Input file {args.input_file} not found")
        sys.exit(1)
    
    print(f"Cleaning SMILES file: {args.input_file}")
    print(f"Output file: {args.output_file}")
    
    clean_smiles_file(args.input_file, args.output_file, args.report)
    
    print(f"\nCleaned dataset saved to: {args.output_file}")
    if args.report:
        print(f"Detailed report saved to: {args.report}")

if __name__ == "__main__":
    main()