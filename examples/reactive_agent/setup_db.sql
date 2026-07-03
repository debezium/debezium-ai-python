CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    quantity INT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial catalog data
INSERT INTO products (id, name, category, price, quantity) VALUES
('prod_001', 'Noise Cancelling Headphones', 'Electronics', 199.99, 10),
('prod_002', 'Smart Water Bottle', 'Fitness', 49.99, 5),
('prod_003', 'Ergonomic Office Chair', 'Office', 299.99, 0);
