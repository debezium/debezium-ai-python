-- Create mock items/products table
CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2),
    category VARCHAR(100)
);

-- Seed initial data
INSERT INTO items (name, description, price, category) VALUES
('Premium Wireless Headphones', 'Active noise cancelling headphones with 30-hour battery life.', 199.99, 'Electronics'),
('Ergonomic Office Chair', 'Breathable mesh chair with lumbar support and adjustable armrests.', 249.50, 'Furniture'),
('Stainless Steel Water Bottle', 'Double-walled vacuum insulated bottle keeping drinks cold for 24 hours.', 25.00, 'Outdoor');
