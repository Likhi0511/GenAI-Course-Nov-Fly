"""
Post-Process text.md to Add Page Markers and Figure Descriptions
==================================================================

Takes existing text.md and figure_descriptions.json
Adds proper page markers and inserts figure descriptions

Usage:
    python fix_text_md.py extracted_documents/paper/
"""

import json
import re
import argparse
from pathlib import Path
from typing import List, Dict


def fix_text_md(doc_dir: Path):
    """
    Fix text.md by:
    1. Adding page markers at regular intervals
    2. Inserting figure descriptions after <!-- image --> markers
    """
    
    text_file = doc_dir / 'text.md'
    desc_file = doc_dir / 'figure_descriptions.json'
    
    if not text_file.exists():
        print(f"text.md not found in {doc_dir}")
        return
    
    if not desc_file.exists():
        print(f"figure_descriptions.json not found in {doc_dir}")
        return
    
    # Read files
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    with open(desc_file, 'r', encoding='utf-8') as f:
        descriptions = json.load(f)
    
    print(f"\n📄 Processing: {doc_dir.name}")
    print(f"   Text: {len(text):,} characters")
    print(f"   Descriptions: {len(descriptions)} figures")
    
    # Step 1: Add page markers
    text_with_pages = add_page_markers(text, descriptions)
    
    # Step 2: Insert figure descriptions  
    final_text = insert_figure_descriptions(text_with_pages, descriptions)
    
    # Save original
    backup_file = doc_dir / 'text_original_backup.md'
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"   ✓ Saved backup: text_original_backup.md")
    
    # Save fixed version
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write(final_text)
    print(f"   ✓ Saved fixed: text.md")
    
    # Print summary
    page_count = len(re.findall(r'<!-- PAGE \d+ -->', final_text))
    desc_count = len(re.findall(r'<!-- IMAGE_START', final_text))
    
    print(f"\nFixed!")
    print(f"   Page markers: {page_count}")
    print(f"   Figure descriptions: {desc_count}")


def add_page_markers(text: str, descriptions: List[Dict]) -> str:
    """
    Add page markers based on figure page numbers
    """
    
    # Get max page number from descriptions
    max_page = max((d.get('page', 0) or d.get('page_number', 0) or 0 
                    for d in descriptions), default=7)
    
    if max_page == 0:
        max_page = 7  # Default for 7-page PDF
    
    print(f"   Detected {max_page} pages")
    
    # Remove existing PAGE 1 marker if present
    text = re.sub(r'<!-- PAGE 1 -->\s*\n', '', text, count=1)
    
    # Split into lines
    lines = text.split('\n')
    
    # Estimate lines per page
    lines_per_page = len(lines) / max_page
    
    result = []
    current_page = 1
    
    # Add first page marker
    result.append(f'<!-- PAGE {current_page} -->\n')
    
    for i, line in enumerate(lines):
        # Calculate which page this line should be on
        estimated_page = min(max_page, max(1, int(i / lines_per_page) + 1))
        
        # Insert page marker when page changes
        # Do it at natural boundaries (headers or empty lines)
        if estimated_page > current_page:
            if (line.strip().startswith('#') or 
                line.strip() == '' or 
                'Exhibit' in line or
                '##' in line):
                current_page = estimated_page
                result.append(f'\n<!-- PAGE {current_page} -->\n')
        
        result.append(line)
    
    return '\n'.join(result)


def insert_figure_descriptions(text: str, descriptions: List[Dict]) -> str:
    """
    Insert figure descriptions after <!-- image --> markers
    
    Strategy: Match by sequential order
    """
    
    # Sort descriptions by figure number
    descriptions_sorted = sorted(descriptions, key=lambda x: x.get('figure_number', 0))
    
    # Find all <!-- image --> positions
    image_pattern = r'<!-- image -->'
    
    # Replace each <!-- image --> with image + description
    figure_index = 0
    
    def replace_image(match):
        nonlocal figure_index
        
        if figure_index < len(descriptions_sorted):
            desc = descriptions_sorted[figure_index]
            figure_index += 1
            
            # Build description block
            block = build_description_block(desc)
            
            return f'<!-- image -->\n{block}'
        else:
            return match.group(0)
    
    result = re.sub(image_pattern, replace_image, text)
    
    return result


def build_description_block(desc: Dict) -> str:
    """
    Build description block for a figure
    
    Format:
    <!-- IMAGE_START: Figure N -->
    **Caption:** ...
    **AI Description:** ...
    <!-- IMAGE_END -->
    """
    
    fig_num = desc.get('figure_number', '?')
    caption = desc.get('caption', '')
    description = desc.get('description', '')
    error = desc.get('error', '')
    
    lines = []
    lines.append(f'<!-- IMAGE_START: Figure {fig_num} -->')
    
    if caption:
        lines.append(f'**Caption:** {caption}')
    
    if description:
        lines.append(f'**AI Description:** {description}')
    elif error:
        lines.append(f'**Error:** {error}')
    else:
        lines.append('**Note:** No description available')
    
    lines.append('<!-- IMAGE_END -->')
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Fix text.md by adding page markers and figure descriptions'
    )
    parser.add_argument(
        'doc_dir',
        help='Directory containing text.md and figure_descriptions.json'
    )
    
    args = parser.parse_args()
    
    doc_dir = Path(args.doc_dir)
    
    if not doc_dir.is_dir():
        print(f"Not a directory: {doc_dir}")
        return
    
    fix_text_md(doc_dir)


if __name__ == '__main__':
    main()
