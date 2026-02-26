#!/usr/bin/env python3
"""
Step 2: Download Clinical Trial PDFs
Downloads 20 clinical trial protocol PDFs from ClinicalTrials.gov

Usage:
    python step2_download_clinical_trials.py
"""

import urllib.request
import ssl
import time
import os
import sys
from pathlib import Path


OUTPUT_FOLDER = "clinical_trials_20"

CLINICAL_TRIALS = [
    {"nct_id": "NCT04368728", "name": "Remdesivir_COVID"},
    {"nct_id": "NCT04470427", "name": "Pfizer_Vaccine"},
    {"nct_id": "NCT03235752", "name": "Ulcerative_Colitis"},
    {"nct_id": "NCT03961204", "name": "Classic_MS"},
    {"nct_id": "NCT03164772", "name": "Heart_Failure"},
    {"nct_id": "NCT04032704", "name": "CAR-T_Cell"},
    {"nct_id": "NCT03753074", "name": "Hepatitis_B_TAF"},
    {"nct_id": "NCT02014597", "name": "Scleroderma_Study"},
    {"nct_id": "NCT03181503", "name": "Lupus_Nephritis"},
    {"nct_id": "NCT03434379", "name": "Breast_Cancer"},
    {"nct_id": "NCT04652245", "name": "Janssen_COVID_Vax"},
    {"nct_id": "NCT04280705", "name": "Hydroxychloroquine_COVID"},
    {"nct_id": "NCT04614948", "name": "Moderna_Vaccine"},
    {"nct_id": "NCT03548935", "name": "Alzheimers_Trial"},
    {"nct_id": "NCT03155620", "name": "Parkinsons_Study"},
    {"nct_id": "NCT02968303", "name": "HIV_Treatment"},
    {"nct_id": "NCT03518606", "name": "Melanoma_Immuno"},
    {"nct_id": "NCT02863419", "name": "Lung_Cancer_NSCLC"},
    {"nct_id": "NCT02951156", "name": "Prostate_Cancer"},
    {"nct_id": "NCT03374254", "name": "Colon_Cancer"},
    {"nct_id": "NCT02788279", "name": "Leukemia_CAR_T"},
    {"nct_id": "NCT03544736", "name": "Multiple_Myeloma"},
    {"nct_id": "NCT03423992", "name": "Rheumatoid_Arthritis"},
    {"nct_id": "NCT02579382", "name": "Crohns_Disease"},
    {"nct_id": "NCT03662659", "name": "Type2_Diabetes"},
]


def download_trial_pdf(nct_id, name, target_folder):
    """Download clinical trial PDF."""
    suffix = nct_id[-2:]
    patterns = ["Prot_000.pdf", "Prot_SAP_000.pdf", "Prot_001.pdf", "Prot_002.pdf"]
    
    context = ssl._create_unverified_context()
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for pattern in patterns:
        url = f"https://cdn.clinicaltrials.gov/large-docs/{suffix}/{nct_id}/{pattern}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                content = response.read()
                if content.startswith(b'%PDF'):
                    filename = f"{nct_id}_{name}.pdf"
                    filepath = Path(target_folder) / filename
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    return True
        except:
            continue
    return False


def download_pdfs():
    """Download clinical trial PDFs."""
    print("\n" + "="*70)
    print("  STEP 2: DOWNLOADING CLINICAL TRIAL PDFs")
    print("="*70 + "\n")
    
    current_dir = Path(os.getcwd())
    output_folder = current_dir / OUTPUT_FOLDER
    output_folder.mkdir(exist_ok=True)
    
    print(f"Saving to: {output_folder}\n")
    
    downloaded = []
    for i, trial in enumerate(CLINICAL_TRIALS):
        print(f"[{i+1}/{len(CLINICAL_TRIALS)}] {trial['nct_id']}...", end=" ", flush=True)
        
        if download_trial_pdf(trial['nct_id'], trial['name'], output_folder):
            print("✅")
            downloaded.append(trial)
        else:
            print("❌")
        
        time.sleep(0.3)
        
        if len(downloaded) >= 20:
            print(f"\n✅ Got 20 PDFs - stopping!")
            break
    
    print(f"\n✅ Downloaded {len(downloaded)} PDFs\n")
    return len(downloaded)


def main():
    count = download_pdfs()
    
    if count >= 10:
        print("="*70)
        print("  ✅ Step 2 Complete")
        print("="*70 + "\n")
        print(f"Downloaded: {count} PDFs to {OUTPUT_FOLDER}/")
        print(f"Next: Run step3_upload_to_s3.py\n")
        sys.exit(0)
    else:
        print(f"⚠️  Only got {count} PDFs (expected 20)")
        print("Continue anyway or try again later.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
