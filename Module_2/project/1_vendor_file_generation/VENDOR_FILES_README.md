# Generated Vendor CSV Files - README

## 📁 Generated Files

### Product CSV Files (3 vendors)
1. **VEND001_20251221_034236.csv** - TechGear (Electronics) - 31 products
2. **VEND002_20251221_034236.csv** - StyleWear (Clothing) - 28 products  
3. **VEND003_20251221_034236.csv** - HomeEssentials (Home & Garden) - 34 products

### Vendor Master File
- **vendors_master.csv** - Contains vendor registration information

---

## 👥 Vendor Details

### Vendor 1: TechGear (VEND001)
**Business:** TechGear Solutions LLC
**Email:** contact@techgear.com
**Phone:** +1-555-0101
**Location:** San Francisco, CA

**Products:** 31 Electronics items
- Computer Accessories (keyboards, mice, stands, webcams)
- Audio Equipment (headphones, speakers, microphones)
- Mobile Accessories (chargers, cases, cables)
- Computer Storage (SSDs, USB drives, SD cards)

**Data Quality:** ✅ **High** - Clean data, no intentional errors
- All required fields present
- Valid price ranges
- Positive stock quantities
- Unique SKUs

---

### Vendor 2: StyleWear (VEND002)
**Business:** StyleWear Fashion Inc
**Email:** sales@stylewear.com
**Phone:** +1-555-0202
**Location:** New York, NY

**Products:** 28 Clothing items
- Men's Clothing (t-shirts, jeans, jackets, pants)
- Women's Clothing (dresses, yoga pants, blouses)
- Accessories (caps, belts, sunglasses, watches)

**Data Quality:** ⚠️ **Medium** - ~8% error rate
**Intentional Errors Include:**
- Some negative prices (validation test)
- Missing SKUs
- Invalid stock quantities
- Potential duplicate SKUs

---

### Vendor 3: HomeEssentials (VEND003)
**Business:** HomeEssentials Corp
**Email:** info@homeessentials.com
**Phone:** +1-555-0303
**Location:** Seattle, WA

**Products:** 34 Home & Garden items
- Kitchen (cookware, appliances, utensils)
- Bedroom (pillows, comforters, sheets)
- Bathroom (towels, mats, accessories)
- Living Room (decor, frames, candles)
- Garden (tools, hoses, pots)

**Data Quality:** ⚠️ **Mixed** - ~8% error rate
**Intentional Errors Include:**
- Negative prices
- Missing required fields
- Invalid stock quantities
- Duplicate SKUs

---

## 📊 CSV File Format

### Columns (14 total)

| Column | Type | Required | Example | Description |
|--------|------|----------|---------|-------------|
| `vendor_product_id` | String | ✅ Yes | PROD0001 | Vendor's internal product ID |
| `product_name` | String | ✅ Yes | Wireless Mouse - Model 651 | Product name |
| `category` | String | ✅ Yes | Computer Accessories | Primary category |
| `subcategory` | String | ❌ No | | Optional subcategory |
| `description` | Text | ❌ No | Ergonomic wireless mouse... | Product description |
| `sku` | String | ✅ Yes | CA-VEND001-0001 | Unique SKU across platform |
| `brand` | String | ❌ No | TechGear | Product brand |
| `price` | Decimal | ✅ Yes | 29.99 | Selling price (must be > 0) |
| `compare_at_price` | Decimal | ❌ No | 39.99 | Original/compare price |
| `stock_quantity` | Integer | ✅ Yes | 150 | Available stock (must be >= 0) |
| `unit` | String | ❌ No | piece | Unit of measurement |
| `weight_kg` | Decimal | ❌ No | 0.25 | Product weight in kg |
| `dimensions_cm` | String | ❌ No | 12x8x4 | Dimensions (LxWxH) |
| `image_url` | URL | ❌ No | https://cdn... | Product image URL |

---

## ✅ Sample Valid Record

```csv
PROD0001,Wireless Mouse - Model 651,Computer Accessories,,Wireless Mouse. Features: Wireless Ergonomic USB Receiver. Brand: TechGear. Perfect for everyday use.,CA-VEND001-0001,TechGear,19.57,49.99,192,piece,2.31,22x34x14,https://cdn.example.com/products/vend001/ca-vend001-0001.jpg
```

**Validation Status:** ✅ PASS
- All required fields present
- Price > 0 (19.57)
- Stock >= 0 (192)
- Valid SKU format
- Valid category

---

## ❌ Sample Error Records

### Error Type 1: Negative Price
```csv
PROD0050,ERROR: T-Shirt - Model 123,Men's Clothing,,...,MC-VEND002-0050,StyleWear,-10.00,34.99,100,...
```
**Validation Status:** ❌ FAIL
- **Error:** Price must be greater than 0
- **Value:** -10.00

### Error Type 2: Missing SKU
```csv
PROD0051,Jeans - Model 456,Men's Clothing,,...,,StyleWear,59.99,79.99,50,...
```
**Validation Status:** ❌ FAIL
- **Error:** Required field 'sku' is missing
- **Value:** (empty)

### Error Type 3: Negative Stock
```csv
PROD0052,Hoodie - Model 789,Men's Clothing,,...,MC-VEND002-0052,StyleWear,49.99,69.99,-5,...
```
**Validation Status:** ❌ FAIL
- **Error:** Stock quantity must be >= 0
- **Value:** -5

---

## 🎯 Usage in Project

### Step 1: Register Vendors
Use **vendors_master.csv** to register vendors in the system first.

```bash
# Via API (POST /vendors)
curl -X POST https://api.example.com/vendors \
  -H "Content-Type: application/json" \
  -d '{
    "vendor_id": "VEND001",
    "vendor_name": "TechGear",
    "email": "contact@techgear.com",
    ...
  }'
```

### Step 2: Upload Product CSVs
Once vendors are registered, upload their product CSV files.

```bash
# Via API (POST /upload)
curl -X POST https://api.example.com/upload \
  -F "vendor_id=VEND001" \
  -F "file=@VEND001_20251221_034236.csv"
```

### Step 3: Monitor Processing
Check upload status via API or view in DynamoDB.

```bash
# Via API (GET /upload-status/{upload_id})
curl https://api.example.com/upload-status/UPLOAD_20251221_034236
```

---

## 📈 Expected Validation Results

### VEND001 (TechGear)
- **Total Products:** 31
- **Expected Valid:** 31 (100%)
- **Expected Errors:** 0 (0%)
- **Status:** ✅ All products should pass validation

### VEND002 (StyleWear)
- **Total Products:** 28
- **Expected Valid:** ~26 (93%)
- **Expected Errors:** ~2 (7%)
- **Common Errors:**
  - 1-2 negative prices
  - 0-1 missing SKUs
  - 0-1 invalid stock

### VEND003 (HomeEssentials)
- **Total Products:** 34
- **Expected Valid:** ~31 (91%)
- **Expected Errors:** ~3 (9%)
- **Common Errors:**
  - 1-2 negative prices
  - 0-1 missing required fields
  - 0-1 duplicate SKUs
  - 0-1 invalid stock

---

## 🧪 Testing Scenarios

### Test 1: Valid Upload (VEND001)
**File:** VEND001_20251221_034236.csv
**Expected:**
- ✅ All 31 products inserted into RDS
- ✅ No error records
- ✅ No error CSV generated
- ✅ Success notification sent

### Test 2: Mixed Upload (VEND002)
**File:** VEND002_20251221_034236.csv
**Expected:**
- ✅ ~26 valid products inserted into RDS
- ❌ ~2 error records sent to SQS
- 📧 Error CSV generated and uploaded to S3
- 📧 Email notification with error report

### Test 3: Mixed Upload (VEND003)
**File:** VEND003_20251221_034236.csv
**Expected:**
- ✅ ~31 valid products inserted into RDS
- ❌ ~3 error records sent to SQS
- 📧 Error CSV generated
- 📧 Email notification

---

## 🔧 Regenerating Files

To generate new CSV files with different data:

```bash
python generate_vendor_csvs.py
```

**What it does:**
1. Generates realistic product data for 3 vendors
2. Creates CSV files with timestamp: `VEND00X_YYYYMMDD_HHMMSS.csv`
3. Adds intentional errors to VEND002 and VEND003 (~8% error rate)
4. Creates varied product names, prices, and stock quantities

---

## 📋 File Statistics

| Vendor | Products | Size | Errors | Quality |
|--------|----------|------|--------|---------|
| VEND001 | 31 | ~8 KB | 0 | High ✅ |
| VEND002 | 28 | ~7 KB | ~2 | Medium ⚠️ |
| VEND003 | 34 | ~9 KB | ~3 | Mixed ⚠️ |

**Total Products:** 93
**Total Expected Errors:** ~5

---

## 🎓 Learning Points

### For Students:

1. **Data Quality:**
   - See real-world scenarios with varying data quality
   - Learn to handle partial failures gracefully

2. **Validation:**
   - Practice implementing business rules
   - Handle multiple error types

3. **Error Handling:**
   - Collect and report errors effectively
   - Provide actionable feedback to vendors

4. **File Processing:**
   - Parse CSV files efficiently
   - Handle large batches (~100 records)

5. **Workflow Design:**
   - Separate ingestion from validation
   - Use streams for decoupling

---

## 📧 Support

For questions about the generated data:
- Check the validation rules in project documentation
- Review error patterns in VEND002 and VEND003
- Regenerate files if needed

**Happy Testing! 🚀**
