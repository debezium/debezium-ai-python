-- Create database if not exists
CREATE DATABASE IF NOT EXISTS inventory_db;
USE inventory_db;

-- Grant permissions to Debezium CDC user
GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'debezium'@'%';
FLUSH PRIVILEGES;

-- Create products table
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(100) NOT NULL,
    stock_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed initial e-commerce catalog items
INSERT INTO products (name, description, price, category, stock_count) VALUES
('Quantum 4K Smart TV', '65-inch OLED display with ultra-high contrast and Dolby Atmos audio.', 899.99, 'Electronics', 15),
('Ergonomic Mechanical Keyboard', 'Hot-swappable RGB mechanical keyboard with tactile switches.', 129.50, 'Electronics', 40),
('Nordic Oak Dining Table', 'Solid natural oak dining table seating 6 people comfortably.', 549.00, 'Furniture', 8),
('Aerobic Treadmill Pro', 'Foldable smart treadmill with live speed tracking and incline.', 699.00, 'Fitness', 12),
('Insulated Camping Backpack', '45L waterproof adventure backpack with hydration pack slot.', 79.99, 'Outdoor', 25);
