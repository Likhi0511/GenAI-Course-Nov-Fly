-- ============================================================================
-- E-Commerce Product Onboarding Platform - PostgreSQL DDL
-- ============================================================================
-- Database: ecommerce_platform
-- Purpose: Store vendors, products, and upload history
-- ACID Properties: Required for vendor registration and product catalog
-- ============================================================================

-- Drop existing tables (if re-running script)
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS upload_history CASCADE;
DROP TABLE IF EXISTS vendors CASCADE;

-- ============================================================================
-- TABLE 1: VENDORS
-- ============================================================================
-- Purpose: Store vendor registration information
-- Business Rule: Vendor MUST be registered BEFORE uploading products
-- ACID: Critical for business transactions (registration, status changes)
-- ============================================================================

CREATE TABLE vendors (
    -- Primary Key
    vendor_id VARCHAR(50) PRIMARY KEY,
    
    -- Basic Information
    vendor_name VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(20),
    
    -- Business Information
    business_name VARCHAR(200),
    tax_id VARCHAR(50),
    
    -- Address Information
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(50),
    country VARCHAR(50) DEFAULT 'USA',
    postal_code VARCHAR(20),
    
    -- Status Management
    status VARCHAR(20) NOT NULL DEFAULT 'active' 
        CHECK (status IN ('active', 'suspended', 'inactive', 'pending_approval')),
    
    -- Audit Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT vendors_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$')
);

-- Indexes for vendors table
CREATE INDEX idx_vendors_email ON vendors(email);
CREATE INDEX idx_vendors_status ON vendors(status);
CREATE INDEX idx_vendors_created_at ON vendors(created_at DESC);

-- Comments for vendors table
COMMENT ON TABLE vendors IS 'Vendor registration and information';
COMMENT ON COLUMN vendors.vendor_id IS 'Unique vendor identifier (e.g., VEND001)';
COMMENT ON COLUMN vendors.email IS 'Primary contact email - must be unique';
COMMENT ON COLUMN vendors.status IS 'Vendor account status: active, suspended, inactive, pending_approval';
COMMENT ON COLUMN vendors.created_at IS 'Vendor registration timestamp';


-- ============================================================================
-- TABLE 2: PRODUCTS
-- ============================================================================
-- Purpose: Store validated product catalog
-- Business Rule: Only validated products are inserted here
-- Source: DynamoDB Stream → Validator Lambda → RDS Products
-- ============================================================================

CREATE TABLE products (
    -- Primary Key (Auto-incrementing)
    product_id SERIAL PRIMARY KEY,
    
    -- Foreign Key to Vendors
    vendor_id VARCHAR(50) NOT NULL,
    
    -- Vendor's Product Identifier
    vendor_product_id VARCHAR(100) NOT NULL,
    
    -- Basic Product Information
    product_name VARCHAR(200) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    description TEXT,
    
    -- SKU (Stock Keeping Unit) - MUST be unique across platform
    sku VARCHAR(100) NOT NULL UNIQUE,
    brand VARCHAR(100),
    
    -- Pricing Information
    price DECIMAL(10, 2) NOT NULL CHECK (price > 0),
    compare_at_price DECIMAL(10, 2) CHECK (compare_at_price IS NULL OR compare_at_price >= price),
    
    -- Inventory Information
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    unit VARCHAR(20) DEFAULT 'piece',
    
    -- Physical Attributes
    weight_kg DECIMAL(8, 2) CHECK (weight_kg IS NULL OR weight_kg > 0),
    dimensions_cm VARCHAR(50),
    
    -- Media
    image_url TEXT,
    
    -- Status Management
    status VARCHAR(20) NOT NULL DEFAULT 'active' 
        CHECK (status IN ('active', 'inactive', 'out_of_stock', 'discontinued')),
    
    -- Upload Tracking
    upload_id VARCHAR(100),
    
    -- Audit Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Key Constraint
    CONSTRAINT fk_vendor 
        FOREIGN KEY (vendor_id) 
        REFERENCES vendors(vendor_id) 
        ON DELETE RESTRICT 
        ON UPDATE CASCADE,
    
    -- Unique Constraint: Vendor can't have duplicate product IDs
    CONSTRAINT unique_vendor_product 
        UNIQUE (vendor_id, vendor_product_id),
    
    -- Business Rule Constraints
    CONSTRAINT valid_price_comparison 
        CHECK (compare_at_price IS NULL OR compare_at_price >= price)
);

-- Indexes for products table
CREATE INDEX idx_products_vendor ON products(vendor_id);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_upload ON products(upload_id);
CREATE INDEX idx_products_created_at ON products(created_at DESC);
CREATE INDEX idx_products_price ON products(price);

-- Full-text search index for product search
CREATE INDEX idx_products_search ON products 
    USING gin(to_tsvector('english', product_name || ' ' || COALESCE(description, '')));

-- Comments for products table
COMMENT ON TABLE products IS 'Validated product catalog - only products that passed validation';
COMMENT ON COLUMN products.product_id IS 'Internal auto-incrementing product ID';
COMMENT ON COLUMN products.vendor_product_id IS 'Vendor''s own product identifier from CSV';
COMMENT ON COLUMN products.sku IS 'Unique SKU across entire platform - no duplicates allowed';
COMMENT ON COLUMN products.price IS 'Current selling price - must be greater than 0';
COMMENT ON COLUMN products.compare_at_price IS 'Original/compare price for discounts';
COMMENT ON COLUMN products.stock_quantity IS 'Available inventory - must be >= 0';
COMMENT ON COLUMN products.upload_id IS 'Tracks which upload created this product';


-- ============================================================================
-- TABLE 3: UPLOAD_HISTORY
-- ============================================================================
-- Purpose: Track all CSV upload attempts and their processing status
-- Used for: Vendor dashboard, analytics, troubleshooting
-- ============================================================================

CREATE TABLE upload_history (
    -- Primary Key
    upload_id VARCHAR(100) PRIMARY KEY,
    
    -- Foreign Key to Vendors
    vendor_id VARCHAR(50) NOT NULL,
    
    -- File Information
    file_name VARCHAR(255) NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    
    -- Processing Statistics
    total_records INTEGER DEFAULT 0,
    valid_records INTEGER DEFAULT 0,
    error_records INTEGER DEFAULT 0,
    
    -- Processing Status
    status VARCHAR(50) NOT NULL DEFAULT 'processing' 
        CHECK (status IN ('processing', 'completed', 'failed', 'partial')),
    
    -- Error File (if errors occurred)
    error_file_s3_key VARCHAR(500),
    
    -- Timestamps
    upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP,
    processing_completed_at TIMESTAMP,
    
    -- Processing Metrics
    processing_duration_seconds INTEGER,
    
    -- Additional Metadata (JSON)
    metadata JSONB,
    
    -- Foreign Key Constraint
    CONSTRAINT fk_upload_vendor 
        FOREIGN KEY (vendor_id) 
        REFERENCES vendors(vendor_id) 
        ON DELETE CASCADE 
        ON UPDATE CASCADE,
    
    -- Business Rule Constraints
    CONSTRAINT valid_record_counts 
        CHECK (valid_records + error_records = total_records),
    
    CONSTRAINT valid_error_file 
        CHECK (
            (error_records = 0 AND error_file_s3_key IS NULL) OR 
            (error_records > 0)
        )
);

-- Indexes for upload_history table
CREATE INDEX idx_upload_vendor ON upload_history(vendor_id);
CREATE INDEX idx_upload_status ON upload_history(status);
CREATE INDEX idx_upload_timestamp ON upload_history(upload_timestamp DESC);
CREATE INDEX idx_upload_processing_time ON upload_history(processing_duration_seconds);

-- Comments for upload_history table
COMMENT ON TABLE upload_history IS 'Tracks all CSV upload attempts and processing results';
COMMENT ON COLUMN upload_history.upload_id IS 'Unique upload identifier (e.g., UPLOAD_20241221_103045)';
COMMENT ON COLUMN upload_history.total_records IS 'Total products in CSV file';
COMMENT ON COLUMN upload_history.valid_records IS 'Products that passed validation';
COMMENT ON COLUMN upload_history.error_records IS 'Products that failed validation';
COMMENT ON COLUMN upload_history.status IS 'Upload processing status';
COMMENT ON COLUMN upload_history.error_file_s3_key IS 'S3 location of error CSV (if errors exist)';
COMMENT ON COLUMN upload_history.metadata IS 'Additional upload metadata in JSON format';


-- ============================================================================
-- TABLE 4: PRODUCT_CATEGORIES (Reference/Lookup Table)
-- ============================================================================
-- Purpose: Valid product categories for validation
-- Used by: Validator Lambda to check category whitelist
-- ============================================================================

CREATE TABLE product_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    parent_category VARCHAR(100),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert standard categories
INSERT INTO product_categories (category_name, parent_category, description) VALUES
    ('Electronics', NULL, 'Electronic devices and accessories'),
    ('Computer Accessories', 'Electronics', 'Keyboards, mice, monitors, etc.'),
    ('Audio Equipment', 'Electronics', 'Headphones, speakers, microphones'),
    ('Mobile Accessories', 'Electronics', 'Phone cases, chargers, cables'),
    ('Computer Storage', 'Electronics', 'SSDs, USB drives, SD cards'),
    ('Clothing', NULL, 'Apparel and fashion items'),
    ('Men''s Clothing', 'Clothing', 'Clothing for men'),
    ('Women''s Clothing', 'Clothing', 'Clothing for women'),
    ('Accessories', 'Clothing', 'Fashion accessories'),
    ('Home & Garden', NULL, 'Home improvement and garden supplies'),
    ('Kitchen', 'Home & Garden', 'Kitchen appliances and utensils'),
    ('Bedroom', 'Home & Garden', 'Bedroom furniture and accessories'),
    ('Bathroom', 'Home & Garden', 'Bathroom accessories'),
    ('Living Room', 'Home & Garden', 'Living room decor and furniture'),
    ('Garden', 'Home & Garden', 'Garden tools and supplies'),
    ('Sports & Outdoors', NULL, 'Sports equipment and outdoor gear'),
    ('Books', NULL, 'Books and publications'),
    ('Toys & Games', NULL, 'Toys and gaming products'),
    ('Health & Beauty', NULL, 'Health and beauty products'),
    ('Food & Beverage', NULL, 'Food and beverage items');

-- Index for categories
CREATE INDEX idx_categories_parent ON product_categories(parent_category);

COMMENT ON TABLE product_categories IS 'Valid product categories for validation';


-- ============================================================================
-- TABLE 5: VALIDATION_ERRORS (Error Tracking)
-- ============================================================================
-- Purpose: Store detailed validation error information for analytics
-- Used for: Error pattern analysis, vendor data quality scores
-- ============================================================================

CREATE TABLE validation_errors (
    error_id SERIAL PRIMARY KEY,
    
    -- Upload Reference
    upload_id VARCHAR(100) NOT NULL,
    vendor_id VARCHAR(50) NOT NULL,
    
    -- Record Information
    row_number INTEGER NOT NULL,
    vendor_product_id VARCHAR(100),
    
    -- Error Details
    error_type VARCHAR(50) NOT NULL,
    error_field VARCHAR(100),
    error_message TEXT NOT NULL,
    
    -- Original Data (for debugging)
    original_data JSONB,
    
    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Keys
    CONSTRAINT fk_error_upload 
        FOREIGN KEY (upload_id) 
        REFERENCES upload_history(upload_id) 
        ON DELETE CASCADE,
    
    CONSTRAINT fk_error_vendor 
        FOREIGN KEY (vendor_id) 
        REFERENCES vendors(vendor_id) 
        ON DELETE CASCADE
);

-- Indexes for validation_errors table
CREATE INDEX idx_errors_upload ON validation_errors(upload_id);
CREATE INDEX idx_errors_vendor ON validation_errors(vendor_id);
CREATE INDEX idx_errors_type ON validation_errors(error_type);
CREATE INDEX idx_errors_created_at ON validation_errors(created_at DESC);

COMMENT ON TABLE validation_errors IS 'Detailed validation error tracking for analytics';
COMMENT ON COLUMN validation_errors.error_type IS 'Error category: missing_field, invalid_price, duplicate_sku, etc.';


-- ============================================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================================

-- Function: Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update updated_at for vendors
CREATE TRIGGER update_vendors_updated_at
    BEFORE UPDATE ON vendors
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger: Auto-update updated_at for products
CREATE TRIGGER update_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- Function: Calculate processing duration
CREATE OR REPLACE FUNCTION calculate_processing_duration()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.processing_completed_at IS NOT NULL AND NEW.processing_started_at IS NOT NULL THEN
        NEW.processing_duration_seconds = EXTRACT(EPOCH FROM (NEW.processing_completed_at - NEW.processing_started_at))::INTEGER;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-calculate processing duration
CREATE TRIGGER update_upload_duration
    BEFORE UPDATE ON upload_history
    FOR EACH ROW
    EXECUTE FUNCTION calculate_processing_duration();


-- Function: Update product status based on stock
CREATE OR REPLACE FUNCTION update_product_stock_status()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.stock_quantity = 0 AND NEW.status = 'active' THEN
        NEW.status = 'out_of_stock';
    ELSIF NEW.stock_quantity > 0 AND NEW.status = 'out_of_stock' THEN
        NEW.status = 'active';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update product status based on stock
CREATE TRIGGER update_product_status_on_stock_change
    BEFORE INSERT OR UPDATE OF stock_quantity ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_product_stock_status();


-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: Vendor Summary Statistics
CREATE OR REPLACE VIEW vendor_summary AS
SELECT 
    v.vendor_id,
    v.vendor_name,
    v.email,
    v.status,
    COUNT(DISTINCT p.product_id) AS total_products,
    COUNT(DISTINCT CASE WHEN p.status = 'active' THEN p.product_id END) AS active_products,
    COUNT(DISTINCT uh.upload_id) AS total_uploads,
    MAX(uh.upload_timestamp) AS last_upload_date,
    COALESCE(SUM(uh.error_records), 0) AS total_errors,
    v.created_at
FROM vendors v
LEFT JOIN products p ON v.vendor_id = p.vendor_id
LEFT JOIN upload_history uh ON v.vendor_id = uh.vendor_id
GROUP BY v.vendor_id, v.vendor_name, v.email, v.status, v.created_at;

COMMENT ON VIEW vendor_summary IS 'Vendor statistics summary for dashboard';


-- View: Recent Upload Activity
CREATE OR REPLACE VIEW recent_uploads AS
SELECT 
    uh.upload_id,
    uh.vendor_id,
    v.vendor_name,
    uh.file_name,
    uh.total_records,
    uh.valid_records,
    uh.error_records,
    uh.status,
    uh.upload_timestamp,
    uh.processing_duration_seconds,
    ROUND((uh.valid_records::DECIMAL / NULLIF(uh.total_records, 0) * 100), 2) AS success_rate_percent
FROM upload_history uh
JOIN vendors v ON uh.vendor_id = v.vendor_id
ORDER BY uh.upload_timestamp DESC;

COMMENT ON VIEW recent_uploads IS 'Recent upload activity with success rates';


-- View: Product Catalog with Vendor Info
CREATE OR REPLACE VIEW product_catalog AS
SELECT 
    p.product_id,
    p.vendor_id,
    v.vendor_name,
    p.vendor_product_id,
    p.product_name,
    p.category,
    p.subcategory,
    p.sku,
    p.brand,
    p.price,
    p.compare_at_price,
    p.stock_quantity,
    p.status,
    p.created_at
FROM products p
JOIN vendors v ON p.vendor_id = v.vendor_id
WHERE p.status = 'active';

COMMENT ON VIEW product_catalog IS 'Active product catalog with vendor information';


-- ============================================================================
-- SAMPLE DATA (For Testing)
-- ============================================================================

-- Insert sample vendors (matching our generated CSV data)
INSERT INTO vendors (vendor_id, vendor_name, email, phone, business_name, tax_id, address, city, state, country, postal_code, status)
VALUES 
    ('VEND001', 'TechGear', 'contact@techgear.com', '+1-555-0101', 'TechGear Solutions LLC', '12-3456701', '789 Innovation Drive', 'San Francisco', 'CA', 'USA', '94105', 'active'),
    ('VEND002', 'StyleWear', 'sales@stylewear.com', '+1-555-0202', 'StyleWear Fashion Inc', '12-3456702', '456 Fashion Avenue', 'New York', 'NY', 'USA', '10001', 'active'),
    ('VEND003', 'HomeEssentials', 'info@homeessentials.com', '+1-555-0303', 'HomeEssentials Corp', '12-3456703', '123 Home Street', 'Seattle', 'WA', 'USA', '98101', 'active')
ON CONFLICT (vendor_id) DO NOTHING;


-- ============================================================================
-- GRANTS & PERMISSIONS (Adjust based on your setup)
-- ============================================================================

-- Create application user (if not exists)
-- CREATE USER ecommerce_app WITH PASSWORD 'your_secure_password';

-- Grant necessary permissions
-- GRANT CONNECT ON DATABASE ecommerce_platform TO ecommerce_app;
-- GRANT USAGE ON SCHEMA public TO ecommerce_app;
-- GRANT SELECT, INSERT, UPDATE ON vendors, products, upload_history, validation_errors TO ecommerce_app;
-- GRANT SELECT ON product_categories TO ecommerce_app;
-- GRANT SELECT ON vendor_summary, recent_uploads, product_catalog TO ecommerce_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ecommerce_app;


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify tables created
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

-- Verify vendors inserted
SELECT vendor_id, vendor_name, email, status 
FROM vendors 
ORDER BY vendor_id;

-- Verify categories inserted
SELECT category_name, parent_category, is_active 
FROM product_categories 
WHERE is_active = TRUE 
ORDER BY category_name;

-- Show table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;


-- ============================================================================
-- SCRIPT COMPLETE
-- ============================================================================

-- Summary
DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Database Schema Created Successfully!';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Tables Created:';
    RAISE NOTICE '  1. vendors (3 sample records)';
    RAISE NOTICE '  2. products (ready for validated products)';
    RAISE NOTICE '  3. upload_history (tracking table)';
    RAISE NOTICE '  4. product_categories (20 categories)';
    RAISE NOTICE '  5. validation_errors (error tracking)';
    RAISE NOTICE '';
    RAISE NOTICE 'Views Created:';
    RAISE NOTICE '  1. vendor_summary';
    RAISE NOTICE '  2. recent_uploads';
    RAISE NOTICE '  3. product_catalog';
    RAISE NOTICE '';
    RAISE NOTICE 'Ready for product uploads!';
    RAISE NOTICE '============================================================================';
END $$;
