"""
E-Commerce Product CSV Generator
=================================

Generates realistic product CSV files for 3 vendors with varying data quality.

Vendors:
1. VEND001 - TechGear (Electronics) - High quality data
2. VEND002 - StyleWear (Clothing) - Medium quality with some errors
3. VEND003 - HomeEssentials (Home & Garden) - Mixed quality with validation errors

Each vendor gets ~100 products with realistic data.
"""

import csv
import random
from datetime import datetime
from decimal import Decimal


# =============================================================================
# PRODUCT DATA TEMPLATES
# =============================================================================

# Vendor 1: TechGear - Electronics (High Quality)
TECHGEAR_PRODUCTS = {
    'categories': {
        'Computer Accessories': [
            ('Wireless Mouse', 'TechGear', 19.99, 49.99, ['Wireless', 'Ergonomic', 'USB Receiver']),
            ('USB-C Keyboard', 'TechGear', 79.99, 109.99, ['Mechanical', 'RGB Backlight', 'USB-C']),
            ('Laptop Stand', 'TechGear', 45.99, 59.99, ['Aluminum', 'Adjustable', 'Ergonomic']),
            ('Webcam HD', 'TechGear', 89.99, 119.99, ['1080p', 'Auto Focus', 'Built-in Mic']),
            ('USB Hub 7-Port', 'TechGear', 29.99, 39.99, ['7 Ports', 'USB 3.0', 'Powered']),
            ('Monitor Mount Dual', 'TechGear', 119.99, 149.99, ['Dual Monitor', 'VESA', 'Adjustable']),
            ('Cable Organizer', 'TechGear', 12.99, 19.99, ['Cable Management', 'Desk', 'Adhesive']),
            ('Laptop Cooling Pad', 'TechGear', 34.99, 44.99, ['LED Fans', 'Adjustable Height', 'USB Powered']),
            ('Wireless Presenter', 'TechGear', 24.99, 34.99, ['Red Laser', 'USB Receiver', 'Rechargeable']),
            ('Desk Lamp LED', 'TechGear', 39.99, 54.99, ['Touch Control', 'Dimmable', 'USB Charging']),
        ],
        'Audio Equipment': [
            ('Bluetooth Headphones', 'TechGear', 149.99, 199.99, ['Noise Cancelling', 'Wireless', '30hr Battery']),
            ('USB Microphone', 'TechGear', 89.99, 129.99, ['Condenser', 'USB', 'Pop Filter']),
            ('Desktop Speakers', 'TechGear', 69.99, 99.99, ['2.1 Channel', 'Bluetooth', 'Subwoofer']),
            ('Gaming Headset', 'TechGear', 79.99, 109.99, ['7.1 Surround', 'RGB', 'Detachable Mic']),
            ('Wireless Earbuds', 'TechGear', 59.99, 89.99, ['True Wireless', 'Charging Case', 'IPX7']),
            ('Soundbar', 'TechGear', 179.99, 249.99, ['Bluetooth', 'HDMI ARC', 'Wall Mountable']),
            ('Studio Headphones', 'TechGear', 199.99, 279.99, ['Professional', 'Closed Back', 'Detachable Cable']),
            ('Portable Speaker', 'TechGear', 49.99, 69.99, ['Waterproof', 'Bluetooth', '12hr Battery']),
        ],
        'Mobile Accessories': [
            ('Phone Stand', 'TechGear', 14.99, 24.99, ['Adjustable', 'Non-Slip', 'Foldable']),
            ('Wireless Charger', 'TechGear', 29.99, 39.99, ['Fast Charging', 'Qi Compatible', 'LED Indicator']),
            ('Phone Case Universal', 'TechGear', 19.99, 29.99, ['Shockproof', 'Clear', 'Slim']),
            ('Screen Protector Pack', 'TechGear', 9.99, 14.99, ['Tempered Glass', '3 Pack', 'Easy Install']),
            ('Car Phone Mount', 'TechGear', 24.99, 34.99, ['Dashboard', 'Windshield', 'Adjustable']),
            ('Power Bank 20000mAh', 'TechGear', 39.99, 54.99, ['Fast Charging', 'Dual USB', 'LED Display']),
            ('USB-C Cable 3-Pack', 'TechGear', 15.99, 24.99, ['Fast Charging', '6ft', 'Braided']),
            ('Phone Grip Ring', 'TechGear', 7.99, 12.99, ['360 Rotation', 'Magnetic', 'Kickstand']),
        ],
        'Computer Storage': [
            ('External SSD 1TB', 'TechGear', 129.99, 179.99, ['USB-C', '540MB/s', 'Portable']),
            ('USB Flash Drive 128GB', 'TechGear', 19.99, 29.99, ['USB 3.0', 'Keychain', 'Compact']),
            ('SD Card 256GB', 'TechGear', 34.99, 49.99, ['Class 10', 'UHS-I', 'High Speed']),
            ('Card Reader USB-C', 'TechGear', 16.99, 24.99, ['Multi-Card', 'USB 3.0', 'Compact']),
            ('External HDD 2TB', 'TechGear', 79.99, 109.99, ['USB 3.0', 'Portable', 'Backup Software']),
        ],
    }
}

# Vendor 2: StyleWear - Clothing (Medium Quality - Some Errors)
STYLEWEAR_PRODUCTS = {
    'categories': {
        'Men\'s Clothing': [
            ('Cotton T-Shirt', 'StyleWear', 24.99, 34.99, ['100% Cotton', 'Crew Neck', 'Classic Fit']),
            ('Denim Jeans', 'StyleWear', 59.99, 79.99, ['Straight Fit', 'Stretch', 'Classic Blue']),
            ('Polo Shirt', 'StyleWear', 34.99, 49.99, ['Pique Cotton', 'Short Sleeve', 'Casual']),
            ('Dress Shirt', 'StyleWear', 44.99, 64.99, ['Wrinkle-Free', 'Long Sleeve', 'Business']),
            ('Hoodie', 'StyleWear', 49.99, 69.99, ['Fleece', 'Pullover', 'Kangaroo Pocket']),
            ('Chino Pants', 'StyleWear', 54.99, 74.99, ['Slim Fit', 'Stretch', 'Business Casual']),
            ('Bomber Jacket', 'StyleWear', 89.99, 119.99, ['Water Resistant', 'Zip Front', 'Pockets']),
            ('Sweater Crew Neck', 'StyleWear', 39.99, 54.99, ['Knit', 'Ribbed Cuffs', 'Warm']),
            ('Athletic Shorts', 'StyleWear', 29.99, 39.99, ['Moisture Wicking', 'Elastic Waist', 'Pockets']),
            ('Track Pants', 'StyleWear', 44.99, 59.99, ['Jogger Style', 'Tapered', 'Zip Pockets']),
        ],
        'Women\'s Clothing': [
            ('Yoga Pants', 'StyleWear', 39.99, 54.99, ['High Waist', 'Stretchy', 'Moisture Wicking']),
            ('Casual Dress', 'StyleWear', 49.99, 69.99, ['Midi Length', 'A-Line', 'Sleeveless']),
            ('Blouse', 'StyleWear', 34.99, 49.99, ['Chiffon', 'V-Neck', 'Short Sleeve']),
            ('Cardigan', 'StyleWear', 44.99, 64.99, ['Open Front', 'Long Sleeve', 'Pockets']),
            ('Leggings', 'StyleWear', 29.99, 39.99, ['High Waist', 'Stretchy', 'Opaque']),
            ('Maxi Skirt', 'StyleWear', 39.99, 54.99, ['Flowy', 'Elastic Waist', 'Pockets']),
            ('Tank Top', 'StyleWear', 19.99, 29.99, ['Racerback', 'Fitted', 'Breathable']),
            ('Denim Jacket', 'StyleWear', 69.99, 89.99, ['Classic', 'Button Front', 'Pockets']),
            ('Sports Bra', 'StyleWear', 34.99, 44.99, ['High Support', 'Removable Pads', 'Moisture Wicking']),
            ('Jumpsuit', 'StyleWear', 59.99, 79.99, ['Sleeveless', 'Wide Leg', 'Belted']),
        ],
        'Accessories': [
            ('Baseball Cap', 'StyleWear', 19.99, 29.99, ['Adjustable', 'Cotton', 'Embroidered']),
            ('Leather Belt', 'StyleWear', 29.99, 39.99, ['Genuine Leather', 'Metal Buckle', 'Classic']),
            ('Scarf', 'StyleWear', 24.99, 34.99, ['Soft', 'Lightweight', 'Versatile']),
            ('Sunglasses', 'StyleWear', 39.99, 54.99, ['UV Protection', 'Polarized', 'Unisex']),
            ('Wrist Watch', 'StyleWear', 79.99, 109.99, ['Analog', 'Stainless Steel', 'Water Resistant']),
            ('Backpack', 'StyleWear', 54.99, 74.99, ['Laptop Compartment', 'Water Resistant', 'Padded Straps']),
            ('Wallet', 'StyleWear', 34.99, 44.99, ['Leather', 'RFID Blocking', 'Bifold']),
            ('Beanie', 'StyleWear', 16.99, 24.99, ['Knit', 'Warm', 'Cuffed']),
        ],
    }
}

# Vendor 3: HomeEssentials - Home & Garden (Mixed Quality - Validation Errors)
HOMEESSENTIALS_PRODUCTS = {
    'categories': {
        'Kitchen': [
            ('Cookware Set 10-Piece', 'HomeEssentials', 149.99, 199.99, ['Non-Stick', 'Dishwasher Safe', 'Induction Ready']),
            ('Knife Set 15-Piece', 'HomeEssentials', 89.99, 129.99, ['Stainless Steel', 'Block Included', 'Sharp']),
            ('Blender High-Speed', 'HomeEssentials', 79.99, 109.99, ['1000W', '6 Blades', 'BPA-Free']),
            ('Coffee Maker 12-Cup', 'HomeEssentials', 59.99, 79.99, ['Programmable', 'Auto Shutoff', 'Pause Serve']),
            ('Toaster 4-Slice', 'HomeEssentials', 44.99, 64.99, ['Wide Slots', 'Bagel Setting', 'Stainless Steel']),
            ('Mixing Bowl Set', 'HomeEssentials', 34.99, 49.99, ['Stainless Steel', 'Nesting', '5 Sizes']),
            ('Cutting Board Set', 'HomeEssentials', 29.99, 39.99, ['Bamboo', '3 Sizes', 'Juice Groove']),
            ('Dish Rack', 'HomeEssentials', 24.99, 34.99, ['Stainless Steel', 'Drainboard', 'Cutlery Holder']),
            ('Storage Container Set', 'HomeEssentials', 39.99, 54.99, ['BPA-Free', 'Airtight', '20 Piece']),
            ('Spice Rack', 'HomeEssentials', 34.99, 44.99, ['Rotating', '16 Jars', 'Wall Mountable']),
        ],
        'Bedroom': [
            ('Pillow Set Queen', 'HomeEssentials', 44.99, 64.99, ['Memory Foam', 'Cooling', '2 Pack']),
            ('Comforter King', 'HomeEssentials', 89.99, 119.99, ['Down Alternative', 'All Season', 'Machine Washable']),
            ('Sheet Set California King', 'HomeEssentials', 54.99, 74.99, ['Microfiber', 'Deep Pocket', '6 Piece']),
            ('Mattress Topper Queen', 'HomeEssentials', 79.99, 109.99, ['Memory Foam', '3 Inch', 'Cooling Gel']),
            ('Bedside Lamp', 'HomeEssentials', 34.99, 49.99, ['Touch Control', 'USB Port', 'LED']),
            ('Alarm Clock', 'HomeEssentials', 24.99, 34.99, ['Digital', 'USB Charging', 'Dual Alarm']),
            ('Curtains Blackout', 'HomeEssentials', 39.99, 54.99, ['Thermal Insulated', '2 Panels', 'Grommet Top']),
            ('Area Rug 5x7', 'HomeEssentials', 79.99, 109.99, ['Non-Slip', 'Machine Washable', 'Modern Design']),
        ],
        'Bathroom': [
            ('Towel Set 6-Piece', 'HomeEssentials', 44.99, 64.99, ['Cotton', 'Absorbent', 'Quick Dry']),
            ('Shower Curtain', 'HomeEssentials', 24.99, 34.99, ['Water Resistant', 'Hooks Included', 'Machine Washable']),
            ('Bath Mat Set', 'HomeEssentials', 29.99, 39.99, ['Memory Foam', 'Non-Slip', '2 Piece']),
            ('Soap Dispenser Set', 'HomeEssentials', 34.99, 44.99, ['Ceramic', '4 Piece', 'Pump Bottle']),
            ('Toilet Brush Set', 'HomeEssentials', 19.99, 29.99, ['Stainless Steel', 'Holder Included', 'Durable']),
            ('Bathroom Scale', 'HomeEssentials', 29.99, 39.99, ['Digital', 'Tempered Glass', '400lb Capacity']),
        ],
        'Living Room': [
            ('Throw Pillows 4-Pack', 'HomeEssentials', 39.99, 54.99, ['18x18', 'Decorative', 'Inserts Included']),
            ('Picture Frame Set', 'HomeEssentials', 34.99, 49.99, ['Wood', '7 Frames', 'Wall Gallery']),
            ('Decorative Vase', 'HomeEssentials', 24.99, 34.99, ['Ceramic', 'Modern', 'Tall']),
            ('Candle Set', 'HomeEssentials', 29.99, 39.99, ['Scented', '3 Pack', 'Soy Wax']),
            ('Wall Clock', 'HomeEssentials', 34.99, 44.99, ['Silent', 'Modern', '12 Inch']),
        ],
        'Garden': [
            ('Garden Tool Set', 'HomeEssentials', 49.99, 69.99, ['9 Piece', 'Ergonomic', 'Carry Bag']),
            ('Watering Can', 'HomeEssentials', 19.99, 29.99, ['2 Gallon', 'Removable Spout', 'Plastic']),
            ('Plant Pots Set', 'HomeEssentials', 34.99, 49.99, ['Ceramic', 'Drainage Holes', '5 Sizes']),
            ('Garden Hose 50ft', 'HomeEssentials', 39.99, 54.99, ['Heavy Duty', 'Spray Nozzle', 'Kink Resistant']),
            ('Outdoor Thermometer', 'HomeEssentials', 24.99, 34.99, ['Wireless', 'Indoor/Outdoor', 'LCD Display']),
        ],
    }
}


# =============================================================================
# DATA GENERATION FUNCTIONS
# =============================================================================

def generate_sku(vendor_id, category, index):
    """Generate unique SKU for product"""
    cat_code = ''.join([word[0].upper() for word in category.split()[:2]])
    return f"{cat_code}-{vendor_id}-{index:04d}"


def generate_product_id(vendor_id, index):
    """Generate vendor's product ID"""
    return f"PROD{index:04d}"


def add_intentional_errors(products, error_rate=0.05):
    """Add intentional errors to some products for testing validation"""
    error_products = []
    
    for i, product in enumerate(products):
        if random.random() < error_rate:
            # Add various types of errors
            error_type = random.choice(['negative_price', 'missing_field', 'invalid_stock', 'duplicate_sku'])
            
            product_copy = product.copy()
            
            if error_type == 'negative_price':
                product_copy['price'] = -10.00
                product_copy['product_name'] = f"ERROR: {product_copy['product_name']}"
            
            elif error_type == 'missing_field':
                product_copy['sku'] = ''
            
            elif error_type == 'invalid_stock':
                product_copy['stock_quantity'] = -5
            
            elif error_type == 'duplicate_sku' and i > 0:
                product_copy['sku'] = products[i-1]['sku']
            
            error_products.append(product_copy)
        else:
            error_products.append(product)
    
    return error_products


def generate_vendor_products(vendor_id, vendor_name, product_catalog, num_products=100, add_errors=False):
    """Generate products for a vendor"""
    products = []
    index = 1
    
    # Generate products from catalog
    for category, items in product_catalog['categories'].items():
        # Determine how many products for this category
        items_count = min(len(items), num_products // len(product_catalog['categories']))
        
        for i in range(items_count):
            item_template = items[i % len(items)]
            product_name, brand, base_price, compare_price, features = item_template
            
            # Add variation to prices and stock
            price = round(base_price * random.uniform(0.9, 1.1), 2)
            stock = random.randint(10, 500)
            weight = round(random.uniform(0.1, 5.0), 2)
            
            product = {
                'vendor_product_id': generate_product_id(vendor_id, index),
                'product_name': f"{product_name} - Model {random.randint(100, 999)}",
                'category': category.split("'")[0] if "'" in category else category,
                'subcategory': '',
                'description': f"{product_name}. Features: {', '.join(features)}. Brand: {brand}. Perfect for everyday use.",
                'sku': generate_sku(vendor_id, category, index),
                'brand': brand,
                'price': price,
                'compare_at_price': compare_price if random.random() > 0.3 else '',
                'stock_quantity': stock,
                'unit': 'piece',
                'weight_kg': weight,
                'dimensions_cm': f"{random.randint(10,50)}x{random.randint(10,40)}x{random.randint(5,30)}",
                'image_url': f"https://cdn.example.com/products/{vendor_id.lower()}/{generate_sku(vendor_id, category, index).lower()}.jpg"
            }
            
            products.append(product)
            index += 1
            
            if len(products) >= num_products:
                break
        
        if len(products) >= num_products:
            break
    
    # Add errors if requested
    if add_errors:
        products = add_intentional_errors(products, error_rate=0.08)
    
    return products[:num_products]


def write_csv(filename, products):
    """Write products to CSV file"""
    if not products:
        print(f"No products to write to {filename}")
        return
    
    fieldnames = [
        'vendor_product_id', 'product_name', 'category', 'subcategory',
        'description', 'sku', 'brand', 'price', 'compare_at_price',
        'stock_quantity', 'unit', 'weight_kg', 'dimensions_cm', 'image_url'
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)
    
    print(f"✓ Created {filename} with {len(products)} products")


# =============================================================================
# MAIN GENERATION
# =============================================================================

def main():
    """Generate CSV files for all 3 vendors"""
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print("\n" + "="*80)
    print("E-Commerce Product CSV Generator")
    print("="*80 + "\n")
    
    # Vendor 1: TechGear - High Quality (No Errors)
    print("Generating products for Vendor 1: TechGear (Electronics)...")
    vendor1_products = generate_vendor_products(
        vendor_id='VEND001',
        vendor_name='TechGear',
        product_catalog=TECHGEAR_PRODUCTS,
        num_products=100,
        add_errors=False  # Clean data
    )
    filename1 = f'VEND001_{timestamp}.csv'
    write_csv(filename1, vendor1_products)
    
    # Vendor 2: StyleWear - Medium Quality (Few Errors)
    print("\nGenerating products for Vendor 2: StyleWear (Clothing)...")
    vendor2_products = generate_vendor_products(
        vendor_id='VEND002',
        vendor_name='StyleWear',
        product_catalog=STYLEWEAR_PRODUCTS,
        num_products=100,
        add_errors=True  # Some errors
    )
    filename2 = f'VEND002_{timestamp}.csv'
    write_csv(filename2, vendor2_products)
    
    # Vendor 3: HomeEssentials - Mixed Quality (More Errors)
    print("\nGenerating products for Vendor 3: HomeEssentials (Home & Garden)...")
    vendor3_products = generate_vendor_products(
        vendor_id='VEND003',
        vendor_name='HomeEssentials',
        product_catalog=HOMEESSENTIALS_PRODUCTS,
        num_products=100,
        add_errors=True  # Some errors
    )
    filename3 = f'VEND003_{timestamp}.csv'
    write_csv(filename3, vendor3_products)
    
    # Summary
    print("\n" + "="*80)
    print("GENERATION SUMMARY")
    print("="*80)
    print(f"\nVendor 1 (TechGear):")
    print(f"  File: {filename1}")
    print(f"  Products: {len(vendor1_products)}")
    print(f"  Quality: High (Clean data)")
    print(f"  Categories: Computer Accessories, Audio Equipment, Mobile Accessories, Storage")
    
    print(f"\nVendor 2 (StyleWear):")
    print(f"  File: {filename2}")
    print(f"  Products: {len(vendor2_products)}")
    print(f"  Quality: Medium (~8% error rate)")
    print(f"  Categories: Men's Clothing, Women's Clothing, Accessories")
    
    print(f"\nVendor 3 (HomeEssentials):")
    print(f"  File: {filename3}")
    print(f"  Products: {len(vendor3_products)}")
    print(f"  Quality: Mixed (~8% error rate)")
    print(f"  Categories: Kitchen, Bedroom, Bathroom, Living Room, Garden")
    
    print("\n" + "="*80)
    print("Files ready for upload!")
    print("="*80 + "\n")


if __name__ == '__main__':
    main()
